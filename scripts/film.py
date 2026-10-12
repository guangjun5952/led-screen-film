"""Shot base class, typing component and per-frame renderer."""
import math, os
import numpy as np
from engine import *


class Shot:
    dur = 3.0
    gain = 1.6          # content -> light gain
    bg = (0.012, 0.012, 0.014)   # unlit LED glow
    sub = 3             # content sub-frames
    shutter = 0.75      # in frames
    chapter = None
    clock = None        # (v0, v1) message real-time seconds shown in HUD
    hud = True

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def cam(self, t):
        return Cam(SW / 2, SH / 2, 2.0)

    def draw(self, c, t):
        pass

    def post(self, t):
        return {}

    def events(self):
        return []

    def footage(self, t):
        return None

    def delegate(self, t):
        return self, t

    def L(self, abs_t):
        """absolute time -> local"""
        return abs_t - self.start


# ---------------------------------------------------------------- typing
def typed(c, text, x, y, size, t, t0, cps, col=TEXT_WHITE, accent=GREEN, tf=None, track=True,
          cursor=True, blink_after=True, seed=0, alpha=1.0, align='left', hatch_new=True,
          track_col=None, label_scale=1.0, char_times=None, track_every=2):
    """Draw text being typed. Returns (caret_x, caret_y_center, total_width).
    char_times: optional explicit per-char reveal times (overrides t0/cps)."""
    tf = tf or TF_CN
    layout, total = glyph_layout(text, tf, size)
    if align == 'center':
        x -= total / 2
    elif align == 'right':
        x -= total
    nchar = len(text)
    times = char_times or [t0 + i / cps for i in range(nchar)]
    top = y - size * 0.86
    h = size * 1.04
    n = sum(1 for tt in times if t >= tt)
    tc = track_col or WHITE
    pts = []
    for i in range(n):
        ch, cx, w = layout[i]
        age = t - times[i]
        k = smooth(age / 0.28)
        colr = mix(accent, col, k)
        a = alpha * (0.55 + 0.45 * smooth(age / 0.06))
        if ch.strip():
            draw_text(c, ch, x + cx, y, tf, size, colr, a)
        if hatch_new and age < 0.16 and ch.strip():
            hatch_rect(c, x + cx, top, w, h, mix(accent, WHITE, 0.4), alpha * (1 - age / 0.16) * 0.95,
                       period=4.5, width=1.6, phase=t * 30)
        if track and age < 1.1 and ch.strip() and i % track_every == 0:
            fa = alpha * (1 - smooth((age - 0.6) / 0.5))
            jx = int(vnoise(t * 9 + i, seed + i) * 9)
            jy = int(vnoise(t * 7 + i, seed + 50 + i) * 6)
            px, py = x + cx + w * 0.5 + jx * 0.15, top + h * 0.45 + jy * 0.15
            pts.append((px, py))
            lab = f"x: {int((x + cx) * 3 + 120 + jx)} y: {int(top * 3 + 40 + jy)}"
            mono(c, lab, x + cx + 1, top - 3 - (i % 3) * 9 * label_scale, tc, fa * 0.9, size=7 * label_scale)
    if len(pts) >= 2:
        polyline(c, pts, tc, alpha * 0.65, w=0.9)
    # caret + hatched block at the frontier
    caret_x = x + (layout[n - 1][1] + layout[n - 1][2] if n > 0 else 0)
    done = n >= nchar
    if cursor:
        show = True
        if done and blink_after:
            show = ((t - times[-1]) * 2.2) % 1.0 < 0.55
        if not done or show:
            if not done and n < nchar:
                ch, cx, w = layout[n]
                ph = (t - (times[n - 1] if n > 0 else times[0]))
                hatch_rect(c, x + cx, top, w, h, accent, alpha * 0.8, period=4.5, width=1.6, phase=t * 20)
            rect(c, caret_x + 1.0, top - size * 0.08, max(1.2, size * 0.05), h + size * 0.16, WHITE, alpha)
    return caret_x, top + h / 2, total


def label_box(c, s, x, y, col=WHITE, alpha=1.0, size=6.5):
    mono(c, s, x, y, col, alpha, size=size)


# ---------------------------------------------------------------- footage
_CLIPS = {}
def clip(name):
    m = _CLIPS.get(name)
    if m is None:
        p = os.path.join(HERE, 'clips', name + '.rgb')
        n = os.path.getsize(p) // (SW * SH * 3)
        m = np.memmap(p, dtype=np.uint8, mode='r', shape=(n, SH, SW, 3))
        _CLIPS[name] = m
    return m

_LUMA = np.array([0.299, 0.587, 0.114], np.float32)
def grade(name, t, tint=WHITE, amt=0.5, level=1.0, lo=0.06, gamma=1.35, src=0.0, speed=1.0, reverse=False):
    m = clip(name)
    fi = int((src + t * speed) * 30)
    if reverse:
        fi = len(m) - 1 - fi
    fi = int(clamp(fi, 0, len(m) - 1))
    f = m[fi].astype(np.float32) * (1 / 255.0)
    o = np.clip((f - lo) / (1 - lo), 0, 1) ** gamma
    l = o @ _LUMA
    duo = l[..., None] * np.array(tint[:3], np.float32)
    return (o * (1 - amt) + duo * amt) * level


# ---------------------------------------------------------------- renderer
class Film:
    def __init__(self, shots, flashes=(), glitches=()):
        self.shots = shots
        for a, b in zip(shots, shots[1:]):
            a.dur = b.start - a.start
        self.duration = shots[-1].start + shots[-1].dur
        self.flashes = flashes      # (time, dur, col)
        self.glitches = glitches    # (time, dur, amount)
        self.surf = new_surface()
        self.hud_surf = new_surface()
        self._hud_cam = Cam(SW / 2, SH / 2, 1.0)

    def shot_at(self, t):
        for s in self.shots:
            if s.start <= t < s.start + s.dur:
                return s
        return self.shots[-1]

    def content(self, shot, tl):
        shot, tl = shot.delegate(tl)
        c = self.surf.getCanvas()
        c.clear(skia.ColorTRANSPARENT)
        c.save()
        shot.draw(c, tl)
        c.restore()
        raw = self.surf.makeImageSnapshot().toarray()
        a = raw[..., :3].astype(np.float32) * (shot.gain * GAIN_SCALE / 255.0)
        ft = shot.footage(tl)
        if ft is not None:
            al = raw[..., 3:4].astype(np.float32) * (1 / 255.0)
            a += ft * (1.0 - al)
        a += np.array(shot.bg, np.float32)
        return a

    def cam_of(self, shot, tl):
        s2, t2 = shot.delegate(tl)
        return s2.cam(t2)

    def render(self, fi):
        t = fi / FPS
        shot = self.shot_at(t)
        tl = t - shot.start
        half = shot.shutter / FPS / 2
        lo, hi = 0.0, shot.dur - 1e-4
        ta, tb = clamp(tl - half, lo, hi), clamp(tl + half, lo, hi)
        ca, cb = self.cam_of(shot, ta), self.cam_of(shot, tb)
        disp = cam_corner_disp(ca, cb)
        ncam = int(clamp(math.ceil(disp / 3.0), 1, 18))
        if ncam == 1:
            acc = None
            n = shot.sub
            for k in range(n):
                ts = ta + (tb - ta) * ((k + 0.5) / n) if n > 1 else tl
                ct = self.content(shot, ts)
                acc = ct if acc is None else acc + ct
            acc /= n
            img = led_view(acc, self.cam_of(shot, tl))
        else:
            n = max(ncam, shot.sub)
            img = None
            for k in range(n):
                ts = ta + (tb - ta) * ((k + 0.5) / n)
                v = led_view(self.content(shot, ts), self.cam_of(shot, ts))
                img = v if img is None else img + v
            img /= n
        # HUD
        if shot.hud and (shot.clock is not None or shot.chapter):
            hc = self.hud_surf.getCanvas(); hc.clear(skia.ColorBLACK)
            self.draw_hud(hc, shot, tl, t)
            h = surf_to_float(self.hud_surf) * 1.25
            img += led_view(h, self._hud_cam)
        P = {'dof': 0.35}
        s2, t2 = shot.delegate(tl)
        P.update(s2.post(t2))
        P.update(shot.post(tl) if s2 is not shot else {})
        for (ft, fd, fc) in self.flashes:
            if ft <= t < ft + fd:
                P['flash'] = max(P.get('flash', 0), 1.0 - 0.35 * (t - ft) / fd)
                P['flash_col'] = fc
        for (gt, gd, ga) in self.glitches:
            if gt <= t < gt + gd:
                P['glitch'] = max(P.get('glitch', 0), ga)
                P['ca'] = max(P.get('ca', 0.0025), 0.008 * ga + 0.003)
        return post(img, t, P)

    def draw_hud(self, c, shot, tl, t):
        if shot.clock is not None:
            v0, v1 = shot.clock
            k = clamp(tl / shot.dur)
            v = v0 + (v1 - v0) * k
            a = 0.85
            mono(c, "REAL TIME", 22, 26, WHITE, a * 0.5, size=7)
            mono(c, f"T+ {v:5.3f} s", 22, 46, mix(WHITE, AMBER, 0.6), a, size=14)
            rect(c, 22, 50, 70 * clamp(v / 0.45), 1.0, AMBER, 0.8)
        if shot.chapter:
            num, cn, en = shot.chapter
            mono(c, num + " / " + en.upper(), SW - 22, 26, WHITE, 0.5, size=7, align='right')
            draw_text(c, cn, SW - 22, 54, TF_CN, 24, WHITE, 0.9, align='right')


# ---------------------------------------------------------------- 3D (v2)
class Cam3:
    """virtual 3D camera projecting into LED panel cells."""
    def __init__(self, yaw=0.0, pitch=0.25, dist=600.0, f=520.0, cx=SW / 2, cy=SH / 2, target=(0, 0, 0), near=140.0):
        self.yaw, self.pitch, self.dist, self.f, self.cx, self.cy, self.tg, self.near = yaw, pitch, dist, f, cx, cy, target, near
        self._cy, self._sy = math.cos(yaw), math.sin(yaw)
        self._cp, self._sp = math.cos(pitch), math.sin(pitch)
    def project(self, p):
        x, y, z = p[0] - self.tg[0], p[1] - self.tg[1], p[2] - self.tg[2]
        x, z = self._cy * x + self._sy * z, -self._sy * x + self._cy * z
        y, z = self._cp * y - self._sp * z, self._sp * y + self._cp * z
        z += self.dist
        if z < self.near:
            return None
        s = self.f / z
        return (self.cx + x * s, self.cy - y * s, s)

def depth_a(s, k=1.3):
    return clamp(s * k)

def line3(c, cam3, a, b, col, alpha=1.0, w=1.0):
    pa, pb = cam3.project(a), cam3.project(b)
    if pa and pb:
        line(c, pa[0], pa[1], pb[0], pb[1], col, alpha * depth_a(min(pa[2], pb[2])), w)

def poly3(c, cam3, pts, col, alpha=1.0, w=1.0, closed=False):
    pr = [cam3.project(p) for p in pts]
    if closed:
        pr.append(pr[0])
    seg = []
    for p in pr:
        if p is None:
            if len(seg) > 1:
                polyline(c, [(q[0], q[1]) for q in seg], col, alpha * depth_a(min(q[2] for q in seg)), w)
            seg = []
        else:
            seg.append(p)
    if len(seg) > 1:
        polyline(c, [(q[0], q[1]) for q in seg], col, alpha * depth_a(min(q[2] for q in seg)), w)

def box3(c, cam3, ctr, size, col, alpha=1.0, w=1.0, fill=None, fill_alpha=0.0):
    x, y, z = ctr; sx, sy, sz = (s / 2 for s in size)
    v = [(x + i * sx, y + j * sy, z + k * sz) for i in (-1, 1) for j in (-1, 1) for k in (-1, 1)]
    if fill is not None and fill_alpha > 0:
        # fill front-ish faces as flat polygons (painter order by depth)
        faces = [(0, 1, 3, 2), (4, 5, 7, 6), (0, 1, 5, 4), (2, 3, 7, 6), (0, 2, 6, 4), (1, 3, 7, 5)]
        pv = [cam3.project(p) for p in v]
        if all(pv):
            fl = []
            for fc in faces:
                d = sum(1 / pv[i][2] for i in fc)
                fl.append((d, fc))
            fl.sort(reverse=True)
            for d, fc in fl:
                path = skia.Path(); path.moveTo(pv[fc[0]][0], pv[fc[0]][1])
                for i in fc[1:]:
                    path.lineTo(pv[i][0], pv[i][1])
                path.close()
                c.drawPath(path, paint(fill, fill_alpha))
    for a_, b_ in [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)]:
        line3(c, cam3, v[a_], v[b_], col, alpha, w)

def grid3(c, cam3, y=-60, half=320, step=40, col=GREEN, alpha=0.3, cx=0, cz=0):
    for k in range(-half, half + 1, step):
        line3(c, cam3, (cx + k, y, cz - half), (cx + k, y, cz + half), col, alpha, 0.8)
        line3(c, cam3, (cx - half, y, cz + k), (cx + half, y, cz + k), col, alpha, 0.8)

def circle3(c, cam3, ctr, r, col, alpha=1.0, w=1.0, plane='xz', n=48):
    x, y, z = ctr
    if plane == 'xz':
        pts = [(x + r * math.cos(a), y, z + r * math.sin(a)) for a in np.linspace(0, math.tau, n)]
    else:
        pts = [(x + r * math.cos(a), y + r * math.sin(a), z) for a in np.linspace(0, math.tau, n)]
    poly3(c, cam3, pts, col, alpha, w)

def text3(c, cam3, p, s, tf, size, col, alpha=1.0, align='center'):
    q = cam3.project(p)
    if q:
        draw_text(c, s, q[0], q[1], tf, size * q[2], col, alpha * depth_a(q[2]), align=align)
    return q

def mono3(c, cam3, p, s, col, alpha=1.0, align='left'):
    q = cam3.project(p)
    if q:
        mono(c, s, q[0], q[1], col, alpha * depth_a(q[2]), size=7 * (2 if q[2] > 1.6 else 1), align=align)
    return q
