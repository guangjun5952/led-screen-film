"""Single-shot renderer for B-roll MP4s and alpha overlays (PNG-in-MOV) + SFX tracks."""
import os, sys, math, subprocess, time, wave, multiprocessing as mp
import numpy as np, cv2
from engine import *
from film import *

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get('LED_OUT', os.path.join(os.getcwd(), 'out'))
TMP = os.environ.get('LED_TMP', os.path.join(OUT, '_tmp'))
os.makedirs(OUT, exist_ok=True); os.makedirs(TMP, exist_ok=True)
SR = 48000
MASTER = 0.55   # fixed SFX master gain so clips are mutually consistent


# ---------------------------------------------------------------- sfx
def sfx_track(events, dur, path):
    import sfx as A
    from pedalboard import Pedalboard, Limiter, Compressor
    buf = np.zeros((int((dur + 2) * SR), 2), np.float32)
    rng = np.random.default_rng(5)
    for ev in events:
        t, k = ev[0], ev[1]
        p = ev[2] if len(ev) > 2 else {}
        if k == 'wav':      # raw array
            A.add(buf, p['x'], t, p.get('g', 1.0), p.get('pan', 0.0)); continue
        fn, g = A.SFX[k]
        x = np.asarray(fn(p), np.float32)
        pan = p.get('pan', float(np.clip(rng.normal(0, 0.22), -0.5, 0.5)) if k in ('key', 'bit', 'tick', 'strobe', 'hop', 'blip') else 0.0)
        A.add(buf, x, t, g * p.get('g', 1.0), pan)
    buf = buf[:int(dur * SR)] * MASTER
    if len(buf) > int(0.02 * SR):
        n = int(0.02 * SR); buf[-n:] *= np.linspace(1, 0, n)[:, None]
    buf = Pedalboard([Compressor(threshold_db=-16, ratio=2.0, attack_ms=5, release_ms=120),
                      Limiter(threshold_db=-1.5)])(buf.T.copy(), SR).T
    buf = np.clip(buf, -0.97, 0.97)
    with wave.open(path, 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((buf * 32767).astype(np.int16).tobytes())
    return path


# ---------------------------------------------------------------- B-roll
_JOB = {}

def _seg_worker(args):
    k, a, b, path = args
    film = _JOB['film']
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}',
                          '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-preset', 'medium', '-crf', '12',
                          '-pix_fmt', 'yuv420p', '-profile:v', 'high', path], stdin=subprocess.PIPE)
    for fi in range(a, b):
        p.stdin.write(np.ascontiguousarray(film.render(fi)).tobytes())
    p.stdin.close(); p.wait()
    return k


def make_film(shots, flashes=(), glitches=()):
    t = 0.0
    for s in shots:
        s.start = t; t += s.dur
    last = shots[-1].dur
    f = Film(shots, flashes, glitches)
    shots[-1].dur = last
    f.duration = t
    return f


def render_clip(name, shots, events=(), flashes=(), glitches=(), procs=2, frames=None, still=None):
    """shots: list of Shot instances played back to back."""
    if not isinstance(shots, (list, tuple)):
        shots = [shots]
    film = make_film(list(shots), flashes, glitches)
    nfr = int(round(film.duration * FPS))
    if still is not None:   # quick still check
        im = film.render(int(still * FPS))
        cv2.imwrite(os.path.join(TMP, f'{name}_{still:.2f}.jpg'), im[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 88])
        return
    _JOB['film'] = film
    t0 = time.time()
    nseg = procs * 2
    bounds = [int(round(i * nfr / nseg)) for i in range(nseg + 1)]
    jobs = [(i, bounds[i], bounds[i + 1], os.path.join(TMP, f'{name}_s{i}.mp4')) for i in range(nseg) if bounds[i + 1] > bounds[i]]
    with mp.get_context('fork').Pool(procs) as pool:
        list(pool.imap_unordered(_seg_worker, jobs))
    lst = os.path.join(TMP, f'{name}_list.txt')
    with open(lst, 'w') as fh:
        for j in jobs:
            fh.write(f"file '{j[3]}'\n")
    wav = sfx_track(list(events), film.duration, os.path.join(TMP, f'{name}.wav'))
    out = os.path.join(OUT, f'{name}.mp4')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-i', wav,
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '320k', '-shortest', '-movflags', '+faststart', out], check=True)
    for j in jobs:
        os.remove(j[3])
    print(f'{name}: {nfr} frames {film.duration:.2f}s in {time.time() - t0:.0f}s', flush=True)
    return out


# ---------------------------------------------------------------- alpha overlays
def _overlay_post(img, P):
    """lighter post for overlays: bloom + ca + white-hot, no vignette/grain/band"""
    small = cv2.resize(img, (W // 4, H // 4), interpolation=cv2.INTER_AREA)
    b1 = cv2.GaussianBlur(small, (0, 0), 2.2)
    b1 = cv2.resize(b1, (W, H), interpolation=cv2.INTER_LINEAR)
    x = img + b1 * (0.30 * P.get('bloom', 1.0))
    mx = x.max(axis=2, keepdims=True)
    x += np.maximum(mx - 1.0, 0) * 0.35
    y = 1.0 - np.exp(-x * 1.25)
    ca = P.get('ca', 0.0016)
    for ch, s in ((0, 1 + ca), (2, 1 - ca)):
        M = np.float32([[s, 0, (1 - s) * W / 2], [0, s, (1 - s) * H / 2]])
        y[..., ch] = cv2.warpAffine(np.ascontiguousarray(y[..., ch]), M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    return y


class OverlayFilm:
    def __init__(self, ov):
        self.ov = ov
        self.surf = new_surface()

    def _content(self, t):
        c = self.surf.getCanvas(); c.clear(skia.ColorTRANSPARENT)
        self.ov.draw(c, t)
        raw = self.surf.makeImageSnapshot().toarray().astype(np.float32) * (1 / 255.0)
        return raw[..., :3] * (self.ov.gain * GAIN_SCALE), raw[..., 3]

    def render(self, fi):
        ov = self.ov
        t = fi / FPS
        half = ov.shutter / FPS / 2
        n = ov.sub
        accc = None; acca = None
        for k in range(n):
            ts = clamp(t - half + 2 * half * (k + 0.5) / n, 0, ov.dur - 1e-4)
            col, al = self._content(ts)
            cam = ov.cam(ts)
            v = led_view(col, cam)
            sx, sy = cam_maps(cam)
            m = cv2.remap(al, sx, sy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            accc = v if accc is None else accc + v
            acca = m if acca is None else acca + m
        col = _overlay_post(accc / n, ov.post(t))
        am = cv2.GaussianBlur(acca / n, (0, 0), 0.8)
        lum = col.max(axis=2)
        a = np.clip(np.maximum(am, lum * 1.05), 0, 1)
        straight = np.where(a[..., None] > 1e-3, col / np.maximum(a[..., None], 1e-3), 0)
        rgba = np.dstack([np.clip(straight, 0, 1), a])
        return (rgba * 255 + 0.5).astype(np.uint8)


def _ov_worker(args):
    k, a, b, d = args
    of = _JOB['of']
    for fi in range(a, b):
        im = of.render(fi)
        cv2.imwrite(os.path.join(d, f'f{fi:05d}.png'), cv2.cvtColor(im, cv2.COLOR_RGBA2BGRA))
    return k


def render_overlay(name, ov, events=(), procs=2, still=None):
    of = OverlayFilm(ov)
    nfr = int(round(ov.dur * FPS))
    if still is not None:
        im = of.render(int(still * FPS))
        # preview over a mid-grey checker so alpha is visible
        bg = np.full((H, W, 3), 0.42, np.float32)
        ck = ((np.indices((H, W)).sum(0) // 40) % 2)[..., None] * 0.08
        bg = bg + ck
        a = im[..., 3:4] / 255.0
        comp = im[..., :3] / 255.0 * a + bg * (1 - a)
        cv2.imwrite(os.path.join(TMP, f'{name}_{still:.2f}.jpg'), (comp[..., ::-1] * 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 88])
        return
    d = os.path.join(TMP, name + '_png'); os.makedirs(d, exist_ok=True)
    _JOB['of'] = of
    t0 = time.time()
    nseg = procs * 2
    bounds = [int(round(i * nfr / nseg)) for i in range(nseg + 1)]
    jobs = [(i, bounds[i], bounds[i + 1], d) for i in range(nseg)]
    with mp.get_context('fork').Pool(procs) as pool:
        list(pool.imap_unordered(_ov_worker, jobs))
    wav = sfx_track(list(events), ov.dur, os.path.join(TMP, f'{name}.wav'))
    out = os.path.join(OUT, f'{name}.mov')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', str(FPS), '-i', os.path.join(d, 'f%05d.png'), '-i', wav,
                    '-c:v', 'png', '-pix_fmt', 'rgba', '-c:a', 'pcm_s16le', '-shortest', out], check=True)
    subprocess.run(['rm', '-rf', d])
    print(f'{name}: {nfr} frames in {time.time() - t0:.0f}s', flush=True)
    return out


class Overlay:
    dur = 3.0
    gain = 1.5
    sub = 3
    shutter = 0.75
    def __init__(self, **kw):
        for k, v in kw.items(): setattr(self, k, v)
    def cam(self, t):
        return Cam(SW / 2, SH / 2, 1.0)
    def draw(self, c, t):
        pass
    def post(self, t):
        return {}
