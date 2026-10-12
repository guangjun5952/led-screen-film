"""Shared drawing helpers for the pipeline-episode shots."""
import os, math
import numpy as np, cv2
from kit import *

ASSET = os.path.join(HERE, 'assets')
_IMG = {}

def load_img(path, level=1.0, sat=1.0, lift=0.0, cool=0.0, key=None):
    """load an image file -> skia.Image (graded)."""
    k = key or (path, level, sat, lift, cool)
    if k in _IMG:
        return _IMG[k]
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im.ndim == 2:
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGRA)
    if im.shape[2] == 3:
        im = cv2.cvtColor(im, cv2.COLOR_BGR2BGRA)
    f = im.astype(np.float32) / 255.0
    rgb = f[..., :3][..., ::-1]
    l = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    rgb = l[..., None] + (rgb - l[..., None]) * sat
    if cool:
        rgb = rgb * (1 - cool) + l[..., None] * np.array([0.75, 0.9, 1.15], np.float32) * cool
    rgb = np.clip(rgb * level + lift, 0, 1)
    out = np.dstack([rgb, f[..., 3:4]])
    out = (out * 255).astype(np.uint8)
    out = np.ascontiguousarray(out)
    img = skia.Image.fromarray(out, colorType=skia.ColorType.kRGBA_8888_ColorType)
    _IMG[k] = img
    return img

def from_array(rgb_u8, key):
    if key in _IMG:
        return _IMG[key]
    a = np.dstack([rgb_u8, np.full(rgb_u8.shape[:2] + (1,), 255, np.uint8)])
    img = skia.Image.fromarray(np.ascontiguousarray(a), colorType=skia.ColorType.kRGBA_8888_ColorType)
    _IMG[key] = img
    return img

SAMP = skia.SamplingOptions(skia.FilterMode.kLinear, skia.MipmapMode.kLinear)

def draw_img(c, img, x, y, w, h, alpha=1.0, src=None):
    p = skia.Paint(AntiAlias=True); p.setAlphaf(clamp(alpha))
    if src is not None:
        c.drawImageRect(img, skia.Rect.MakeXYWH(*src), skia.Rect.MakeXYWH(x, y, w, h), SAMP, p)
    else:
        c.drawImageRect(img, skia.Rect.MakeXYWH(x, y, w, h), SAMP, p)

def draw_img_quad(c, img, quad, alpha=1.0):
    """draw image mapped to a 4-point quad (tl, tr, br, bl) via perspective matrix"""
    w, h = img.width(), img.height()
    m = skia.Matrix()
    ok = m.setPolyToPoly([skia.Point(0, 0), skia.Point(w, 0), skia.Point(w, h), skia.Point(0, h)],
                         [skia.Point(*q) for q in quad])
    c.save(); c.concat(m)
    p = skia.Paint(AntiAlias=True); p.setAlphaf(clamp(alpha))
    c.drawImage(img, 0, 0, SAMP, p)
    c.restore()

# ---------------------------------------------------------------- 花字
def plate_text(c, s, x, y, size, col=TEXT_WHITE, alpha=1.0, align='left', tf=None, pad=None, plate_a=0.92, border=None):
    tf = tf or TF_CN
    w = text_w(s, tf, size)
    x0 = x - (w if align == 'right' else w / 2 if align == 'center' else 0)
    pd = pad if pad is not None else size * 0.28
    rect(c, x0 - pd, y - size * 0.92 - pd * 0.6, w + 2 * pd, size * 1.16 + pd * 1.2, (0, 0, 0, 1), plate_a * alpha)
    if border:
        rect(c, x0 - pd, y - size * 0.92 - pd * 0.6, w + 2 * pd, size * 1.16 + pd * 1.2, border, alpha, stroke=1.0)
    draw_text(c, s, x0, y, tf, size, col, alpha)
    return x0 - pd, y - size * 0.92 - pd * 0.6, w + 2 * pd, size * 1.16 + pd * 1.2

def typed_plate(c, s, x, y, size, t, t0, cps=14, col=TEXT_WHITE, accent=AMBER, align='left', plate=True,
                track=False, cursor=True, alpha=1.0, char_times=None, plate_a=0.9, blink_after=True, tf=None):
    tf = tf or TF_CN
    w = text_w(s, tf, size)
    x0 = x - (w if align == 'right' else w / 2 if align == 'center' else 0)
    n = len(s)
    times = char_times or [t0 + i / cps for i in range(n)]
    if t < times[0]:
        return
    if plate:
        lay, tot = glyph_layout(s, tf, size)
        k = sum(1 for tt in times if t >= tt)
        ww = lay[k - 1][1] + lay[k - 1][2] if k else 0
        if k < n:
            ww += lay[k][2]
        pd = size * 0.26
        rect(c, x0 - pd, y - size * 0.92 - pd * 0.6, ww + 2 * pd, size * 1.16 + pd * 1.2, (0, 0, 0, 1), plate_a * alpha)
    typed(c, s, x0, y, size, t, 0, 1, col=col, accent=accent, tf=tf, track=track, cursor=cursor, alpha=alpha,
          char_times=times, blink_after=blink_after)

def gag(c, s, x, y, size, t, t0, angle=-3.0, alpha=1.0, col=PINK, txt=(0.03, 0.03, 0.04, 1)):
    """pink block that pops in with overshoot + jitter"""
    if t < t0:
        return
    a = t - t0
    sc = 1.0 + 0.35 * math.exp(-a * 9) * math.cos(a * 30) if a < 0.6 else 1.0
    sc *= ease_out(a / 0.08, 2) * 0.4 + 0.6 if a < 0.08 else 1.0
    jx = vnoise(t * 20, 3) * 0.8; jy = vnoise(t * 20, 9) * 0.8
    w = text_w(s, TF_CN, size)
    c.save(); c.translate(x + jx, y + jy); c.rotate(angle); c.scale(sc, sc)
    pd = size * 0.32
    rect(c, -w / 2 - pd, -size * 0.62 - pd * 0.5, w + 2 * pd, size * 1.24 + pd, col, alpha)
    draw_text(c, s, -w / 2, size * 0.36, TF_CN, size, txt, alpha)
    c.restore()

def pro(c, s, x, y, col=CYAN, alpha=1.0, size=7, lead=None, align='left'):
    """pixel annotation; lead=(x2,y2) draws a leader line"""
    from pixfont import pix_width
    sc = max(1, int(round(size / 7.0)))
    w = pix_width(s, sc)
    x0 = x - (w if align == 'right' else w / 2 if align == 'center' else 0)
    rect(c, x0 - 3 * sc, y - 7 * sc - 3 * sc, w + 6 * sc, 7 * sc + 6 * sc, (0, 0, 0, 1), 0.85 * alpha)
    rect(c, x0 - 3 * sc, y - 7 * sc - 3 * sc, w + 6 * sc, 7 * sc + 6 * sc, col, 0.9 * alpha, stroke=1.0)
    mono(c, s, x0, y, col, alpha, size=size)
    if lead:
        ax = x0 + w + 3 * sc if lead[0] > x0 + w else x0 - 3 * sc
        line(c, ax, y - 3.5 * sc, lead[0], lead[1], col, 0.8 * alpha, 0.8)
        circle(c, lead[0], lead[1], 1.6, col, alpha)

def chat_box(c, s, x, y, w, size, t, t0, cps=12, col=TEXT_WHITE, border=GREEN, alpha=1.0, sent_at=None, align='left'):
    """input box with typing; after sent_at the box flashes and text stays"""
    h = size * 1.9
    if align == 'center':
        x -= w / 2
    k = ease_out((t - t0 + 0.25) / 0.25)
    if k <= 0:
        return
    rect(c, x, y, w * k, h, (0, 0, 0, 1), 0.9 * alpha)
    rect(c, x, y, w * k, h, border, alpha * 0.9, stroke=1.2)
    if k < 1:
        return
    flash = 0.0
    if sent_at is not None and t >= sent_at:
        flash = math.exp(-(t - sent_at) * 8)
        rect(c, x, y, w, h, border, 0.35 * flash * alpha)
    typed(c, s, x + size * 0.6, y + h * 0.5 + size * 0.36, size, t, t0, cps, col=col, accent=border, track=False,
          cursor=sent_at is None or t < sent_at, alpha=alpha)
    # send arrow
    ax = x + w - size * 1.1; ay = y + h / 2
    circle(c, ax, ay, size * 0.55, border, alpha * (0.4 + 0.6 * flash))
    line(c, ax - size * 0.25, ay, ax + size * 0.25, ay, (0, 0, 0, 1), alpha, 1.4)
    line(c, ax + size * 0.05, ay - size * 0.2, ax + size * 0.25, ay, (0, 0, 0, 1), alpha, 1.4)
    line(c, ax + size * 0.05, ay + size * 0.2, ax + size * 0.25, ay, (0, 0, 0, 1), alpha, 1.4)

def bracket(c, x, y, w, h, col, alpha=1.0, l=6, wd=1.2):
    for (px, py, dx, dy) in ((x, y, 1, 1), (x + w, y, -1, 1), (x, y + h, 1, -1), (x + w, y + h, -1, -1)):
        line(c, px, py, px + dx * l, py, col, alpha, wd)
        line(c, px, py, px, py + dy * l, col, alpha, wd)

def scan_grid(c, t, col=GREEN, alpha=0.08, step=20):
    for x in range(0, SW + 1, step):
        line(c, x, 0, x, SH, col, alpha, 0.6)
    for y in range(0, SH + 1, step):
        line(c, 0, y, SW, y, col, alpha, 0.6)
