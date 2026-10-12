"""Other media for the same 'build a screen, then film it' method.
Each function takes a float32 HxWx3 (or HxW) white-on-black *content mask* at output resolution
(e.g. draw your frame with skia at 1920x1080, white text on black) plus time t, and returns an
HxWx3 float image in 0..1. Swap these in where the LED path (led_view + post) would go."""
import math
import numpy as np, cv2
from engine import W, H, _radial

def _bloom(img, amt=1.0):
    small = cv2.resize(img, (W // 4, H // 4), interpolation=cv2.INTER_AREA)
    b1 = cv2.resize(cv2.GaussianBlur(small, (0, 0), 2.2), (W, H))
    tiny = cv2.resize(small, (W // 16, H // 16), interpolation=cv2.INTER_AREA)
    b2 = cv2.resize(cv2.GaussianBlur(tiny, (0, 0), 2.5), (W, H))
    x = img + (b1 * 0.32 + b2 * 0.38) * amt
    x = x + np.maximum(x.max(axis=2, keepdims=True) - 1.0, 0) * 0.35 * amt
    return 1.0 - np.exp(-x * 1.25)

_C = {}
def crt(mask, t, tint=(0.55, 1.0, 0.75)):
    """CRT tube: barrel curvature, RGB aperture grille, scanlines, phosphor bloom, rolling bar, flicker."""
    if 'maps' not in _C:
        yy, xx = np.indices((H, W), np.float32)
        u = (xx - W / 2) / (W / 2); v = (yy - H / 2) / (H / 2)
        k = 1 + 0.10 * (u * u + v * v)
        _C['maps'] = ((u * k * 0.94) * W / 2 + W / 2, (v * k * 0.94) * H / 2 + H / 2)
        tri = np.zeros((H, W, 3), np.float32)
        for ch in range(3):
            tri[:, ch::3, ch] = 1.0
        _C['tri'] = 0.55 + 0.45 * tri
        _C['scan'] = (0.62 + 0.38 * np.sin(yy * math.pi / 3.0) ** 2)[..., None]
        _C['edge'] = np.clip((1.0 - np.maximum(np.abs(u * k * 0.94), np.abs(v * k * 0.94))) * 30, 0, 1)[..., None]
    m = mask if mask.ndim == 3 else np.repeat(mask[..., None], 3, 2)
    col = cv2.GaussianBlur(m * np.array(tint, np.float32) * 1.25, (0, 0), 1.2)
    col = cv2.remap(col, *_C['maps'], cv2.INTER_LINEAR) * _C['scan'] * _C['tri']
    col = _bloom(col * 1.6, 1.2)
    roll = (np.arange(H) / H - (t * 0.6) % 1.0) % 1.0
    col = col * (1 - 0.08 * np.exp(-((roll - 0.5) ** 2) / 0.004))[:, None, None]
    col = col * (0.96 + 0.04 * math.sin(t * 120)) + np.array([0.02, 0.035, 0.03], np.float32)
    return col * _C['edge']

_HT = {}
def halftone(mask, t, per=9.0):
    """newspaper print: AM halftone screen at 45°, paper fibre, misregistered red plate."""
    if 'paper' not in _HT:
        rng = np.random.default_rng(2)
        n = cv2.GaussianBlur(rng.normal(0, 1, (H, W)).astype(np.float32), (0, 0), 1.2)
        fib = cv2.GaussianBlur(rng.normal(0, 1, (H, W)).astype(np.float32), (0, 0), 6)
        _HT['paper'] = np.array([0.91, 0.88, 0.80], np.float32) + (n * 0.02 + fib * 0.03)[..., None]
        yy, xx = np.indices((H, W), np.float32)
        def screen(deg):
            a = math.radians(deg)
            xr = xx * math.cos(a) + yy * math.sin(a); yr = -xx * math.sin(a) + yy * math.cos(a)
            return 0.5 + 0.25 * (np.cos(xr * 2 * math.pi / per) + np.cos(yr * 2 * math.pi / per))
        _HT['s1'] = screen(45); _HT['s2'] = screen(15)
    m = mask.max(axis=2) if mask.ndim == 3 else mask
    m = cv2.GaussianBlur(m, (0, 0), 2.0)
    ink = (m * 1.15 > _HT['s1']).astype(np.float32)
    red = (np.roll(cv2.GaussianBlur(m, (0, 0), 3.0), (3, 5), (0, 1)) * 0.7 > _HT['s2']).astype(np.float32) * 0.55
    img = _HT['paper'] * (1 - red[..., None] * np.array([0.05, 0.75, 0.70], np.float32))
    img = img * (1 - ink[..., None] * 0.92)
    return img * (1 - 0.25 * np.clip(_radial() - 0.4, 0, 1))[..., None]

def scope(stroke_mask, t, graticule=None):
    """oscilloscope: thin green beam strokes (pass an *outline* mask), sweep persistence, glow, graticule."""
    m = stroke_mask.max(axis=2) if stroke_mask.ndim == 3 else stroke_mask
    xx = np.arange(W, dtype=np.float32) / W
    d = ((t * 0.9) % 1.0 - xx) % 1.0
    pers = (0.45 + 0.55 * np.exp(-d * 3.0))[None, :]
    lum = m * pers
    col = lum[..., None] * np.array([0.35, 1.0, 0.55], np.float32) * 1.6
    if graticule is not None:
        col = col + graticule * 0.6
    return _bloom(col, 1.3) + np.array([0.0, 0.02, 0.012], np.float32)
