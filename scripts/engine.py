"""Core renderer: content drawn at LED-grid resolution with skia, then 'filmed' by a
virtual camera looking at an LED dot-matrix panel. Post: white-hot tonemap, bloom,
chromatic aberration, depth-of-field falloff, vignette, grain, flash/glitch.
Motion blur = sub-frame accumulation (content and camera)."""
import math, os
import numpy as np, cv2, skia

cv2.setNumThreads(1)

W, H = int(os.environ.get('LED_W', 1920)), int(os.environ.get('LED_H', 1080))
FPS = 30
SW, SH = int(os.environ.get('LED_SW', 640)), int(os.environ.get('LED_SH', 360))
PITCH0 = W / SW            # px per cell at zoom 1  (=3)

HERE = os.path.dirname(os.path.abspath(__file__))
def _font(env, files, family):
    """font lookup: env var path -> scripts/fonts/<file> -> system family -> default"""
    cands = [os.environ.get(env, '')] + [os.path.join(HERE, 'fonts', f) for f in files]
    for p in cands:
        if p and os.path.exists(p):
            tf = skia.Typeface.MakeFromFile(p)
            if tf is not None:
                return tf
    tf = skia.Typeface.MakeFromName(family, skia.FontStyle.Normal())
    return tf if tf is not None else skia.Typeface.MakeDefault()

# Chinese display font (default: 猴尊宋体 / any CJK serif), English italic (Instrument Serif Italic), mono
TF_CN = _font('LED_FONT_CN', ['cn.ttf', 'cn.otf', 'houzun.ttf'], 'Noto Serif CJK SC')
TF_EN = _font('LED_FONT_EN', ['InstrumentSerif-Italic.ttf', 'en.ttf'], 'Instrument Serif')
TF_MONO = _font('LED_FONT_MONO', ['mono.ttf', 'DejaVuSansMono-Bold.ttf'], 'DejaVu Sans Mono')

# ---------------------------------------------------------------- utilities
def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x

def lerp(a, b, t):
    return a + (b - a) * t

def smooth(t):
    t = clamp(t); return t * t * (3 - 2 * t)

def ease_out(t, p=3):
    t = clamp(t); return 1 - (1 - t) ** p

def ease_in(t, p=3):
    t = clamp(t); return t ** p

def ease_io(t, p=3):
    t = clamp(t)
    return 0.5 * (2 * t) ** p if t < 0.5 else 1 - 0.5 * (2 - 2 * t) ** p

def expo_out(t):
    t = clamp(t); return 1 - 2 ** (-10 * t) if t < 1 else 1.0

def hash1(*a):
    """deterministic pseudo-random in [0,1)"""
    s = 0
    for v in a:
        s = (s * 1000003) ^ int(v * 1000 + 7919)
    s = (s ^ (s >> 13)) * 0x5bd1e995 & 0xffffffff
    s ^= s >> 15
    return (s & 0xffffff) / 0x1000000

def vnoise(x, seed=0):
    """smooth 1D value noise in [-1,1]"""
    i = math.floor(x); f = x - i
    a = hash1(i, seed) * 2 - 1; b = hash1(i + 1, seed) * 2 - 1
    return lerp(a, b, f * f * (3 - 2 * f))

def hexcol(h, a=1.0):
    h = h.lstrip('#')
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a)

def mix(c1, c2, t):
    return tuple(lerp(a, b, t) for a, b in zip(c1, c2))

# palette (reference-matched)
GREEN = hexcol('#38ffa0')
CYAN = hexcol('#38c8ff')
BLUE = hexcol('#4a63ff')
WHITE = hexcol('#ffffff')
MAGENTA = hexcol('#d23cff')
PINK = hexcol('#ff3fa8')
ORANGE = hexcol('#ff7a38')
AMBER = hexcol('#ffb238')
TEXT_WHITE = hexcol('#e8ecf0')
GAIN_SCALE = 0.84   # v2: global light gain trim

# ---------------------------------------------------------------- camera
class Cam:
    __slots__ = ('cx', 'cy', 'zoom', 'roll', 'px', 'py')

    def __init__(self, cx=SW / 2, cy=SH / 2, zoom=1.0, roll=0.0, px=0.0, py=0.0):
        self.cx, self.cy, self.zoom, self.roll, self.px, self.py = cx, cy, zoom, roll, px, py

    def lerp(self, o, t):
        return Cam(*(lerp(getattr(self, k), getattr(o, k), t) for k in Cam.__slots__))

    def tup(self):
        return tuple(getattr(self, k) for k in Cam.__slots__)


_U, _V = np.meshgrid(np.arange(W, dtype=np.float32) - W / 2 + 0.5,
                     np.arange(H, dtype=np.float32) - H / 2 + 0.5)

def cam_maps(cam):
    x, y = _U, _V
    if cam.px or cam.py:
        w = 1.0 + cam.px * x + cam.py * y
        x = x / w; y = y / w
    c, s = math.cos(-cam.roll), math.sin(-cam.roll)
    k = 1.0 / (PITCH0 * cam.zoom)
    sx = (c * k) * x - (s * k) * y + cam.cx
    sy = (s * k) * x + (c * k) * y + cam.cy
    return sx, sy

def cam_corner_disp(c1, c2):
    """max px displacement of output-corner screen points between two cams (measured in output px)"""
    pts = [(-W / 2, -H / 2), (W / 2, -H / 2), (-W / 2, H / 2), (W / 2, H / 2), (0, 0)]
    def proj(cam, x, y):
        w = 1 + cam.px * x + cam.py * y; x /= w; y /= w
        c, s = math.cos(-cam.roll), math.sin(-cam.roll); k = 1 / (PITCH0 * cam.zoom)
        return (c * x - s * y) * k + cam.cx, (s * x + c * y) * k + cam.cy
    m = 0
    for x, y in pts:
        a = proj(c1, x, y); b = proj(c2, x, y)
        m = max(m, math.hypot(a[0] - b[0], a[1] - b[1]) * PITCH0 * c1.zoom)
    return m

# LED dot mask (one cell)
MASKN = 64
def _make_mask():
    g = (np.arange(MASKN, dtype=np.float32) + 0.5) / MASKN - 0.5
    X, Y = np.meshgrid(g, g)
    p = 2.6
    r = (np.abs(X) ** p + np.abs(Y) ** p) ** (1 / p)
    core = 1 - np.clip((r - 0.26) / (0.44 - 0.26), 0, 1)
    core = core * core * (3 - 2 * core)
    halo = np.exp(-(X * X + Y * Y) / (2 * 0.22 ** 2)) * 0.25
    m = core + halo
    return (m / m.mean()).astype(np.float32)
MASK = _make_mask()
MASK_MEAN = 1.0
# wrap-friendly: pad mask so linear interpolation at the edge wraps
MASK_PAD = np.pad(MASK, 1, mode='wrap')

def led_view(content, cam):
    """content: float32 (SH,SW,3). returns float32 (H,W,3) image of the LED panel seen by cam."""
    sx, sy = cam_maps(cam)
    fx = np.floor(sx); fy = np.floor(sy)
    col = cv2.remap(content, fx, fy, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    mx = (sx - fx) * MASKN + 0.5
    my = (sy - fy) * MASKN + 0.5
    m = cv2.remap(MASK_PAD, mx, my, cv2.INTER_LINEAR)
    pitch = PITCH0 * cam.zoom
    contrast = clamp((pitch - 2.2) / 3.0)
    if contrast < 1:
        m = 1.0 + (m - 1.0) * contrast
    return col * m[..., None]

# ---------------------------------------------------------------- skia helpers
def new_surface(w=SW, h=SH):
    info = skia.ImageInfo.Make(w, h, skia.ColorType.kRGBA_8888_ColorType, skia.AlphaType.kPremul_AlphaType)
    return skia.Surface.MakeRaster(info)

def surf_to_float(surf):
    a = surf.makeImageSnapshot().toarray()  # RGBA uint8
    return a[..., :3].astype(np.float32) * (1 / 255.0)

def paint(col, alpha=1.0, stroke=None, aa=True, blend=None):
    r, g, b, a = col
    p = skia.Paint(AntiAlias=aa)
    p.setColor4f(skia.Color4f(r, g, b, clamp(a * alpha)))
    if stroke is not None:
        p.setStyle(skia.Paint.kStroke_Style); p.setStrokeWidth(stroke)
    if blend is not None:
        p.setBlendMode(blend)
    return p

_font_cache = {}
def font(tf, size):
    key = (id(tf), round(size * 4))
    f = _font_cache.get(key)
    if f is None:
        f = skia.Font(tf, size)
        f.setEdging(skia.Font.Edging.kAntiAlias)
        f.setSubpixel(True)
        _font_cache[key] = f
    return f

def text_w(s, tf, size):
    return font(tf, size).measureText(s)

def draw_text(c, s, x, y, tf, size, col, alpha=1.0, align='left', aa=True):
    f = font(tf, size)
    if align != 'left':
        w = f.measureText(s)
        x -= w if align == 'right' else w / 2
    p = paint(col, alpha, aa=aa)
    c.drawString(s, x, y, f, p)

def glyph_layout(s, tf, size):
    """returns list of (char, x, width) with advance, using per-char measurement."""
    f = font(tf, size)
    out = []; x = 0.0
    for ch in s:
        w = f.measureText(ch)
        out.append((ch, x, w)); x += w
    return out, x

def hatch_rect(c, x, y, w, h, col, alpha=1.0, period=3.0, width=1.1, phase=0.0):
    c.save()
    c.clipRect(skia.Rect.MakeXYWH(x, y, w, h))
    p = paint(col, alpha, stroke=width)
    start = -h + ((phase % period) - period)
    k = start
    while k < w + h:
        c.drawLine(x + k, y + h, x + k + h, y, p)
        k += period
    c.restore()

def mono(c, s, x, y, col, alpha=1.0, size=7.0, align='left'):
    """pixel-font text; y = baseline. size ~7 per scale step."""
    from pixfont import pix_text
    sc = max(1, int(round(size / 7.0)))
    pix_text(c, s, x, y - 7 * sc, col, alpha, sc, align)

def line(c, x1, y1, x2, y2, col, alpha=1.0, w=1.0):
    c.drawLine(x1, y1, x2, y2, paint(col, alpha, stroke=w))

def polyline(c, pts, col, alpha=1.0, w=1.0):
    if len(pts) < 2: return
    path = skia.Path(); path.moveTo(*pts[0])
    for p in pts[1:]: path.lineTo(*p)
    c.drawPath(path, paint(col, alpha, stroke=w))

def rect(c, x, y, w, h, col, alpha=1.0, stroke=None):
    c.drawRect(skia.Rect.MakeXYWH(x, y, w, h), paint(col, alpha, stroke=stroke))

def circle(c, x, y, r, col, alpha=1.0, stroke=None):
    c.drawCircle(x, y, r, paint(col, alpha, stroke=stroke))

# ---------------------------------------------------------------- post
_rr = None
def _radial():
    global _rr
    if _rr is None:
        x = (_U / (W / 2)); y = (_V / (H / 2))
        _rr = np.sqrt(x * x * 0.85 + y * y).astype(np.float32)
    return _rr

_grain = None
def _grain_tex():
    global _grain
    if _grain is None:
        rng = np.random.default_rng(7)
        g = rng.normal(0, 1, (H // 2 + 64, W // 2 + 64)).astype(np.float32)
        g = cv2.GaussianBlur(g, (0, 0), 0.6)
        _grain = g
    return _grain

_moire = None
def moire_tex():
    global _moire
    if _moire is None:
        rr = np.sqrt((_U * 1.0) ** 2 + (_V * 1.15) ** 2)
        a = 0.5 + 0.5 * np.cos(rr ** 1.02 * 0.62)
        rr2 = np.sqrt((_U - 520) ** 2 + (_V + 60) ** 2)
        b = 0.5 + 0.5 * np.cos(rr2 * 0.58)
        _moire = (a * b).astype(np.float32)
    return _moire


def post(img, t_frame, P):
    """img: float32 HxWx3 linear-ish. P: dict of post params."""
    # bloom
    small = cv2.resize(img, (W // 4, H // 4), interpolation=cv2.INTER_AREA)
    b1 = cv2.GaussianBlur(small, (0, 0), 2.2)
    tiny = cv2.resize(small, (W // 16, H // 16), interpolation=cv2.INTER_AREA)
    b2 = cv2.GaussianBlur(tiny, (0, 0), 2.5)
    b1 = cv2.resize(b1, (W, H), interpolation=cv2.INTER_LINEAR)
    b2 = cv2.resize(b2, (W, H), interpolation=cv2.INTER_LINEAR)
    bloom = P.get('bloom', 1.0)
    x = img + b1 * (0.32 * bloom) + b2 * (0.38 * bloom)   # v2: tamer glow

    # depth of field falloff toward edges
    dof = P.get('dof', 0.35)
    if dof > 0:
        half = cv2.resize(x, (W // 3, H // 3), interpolation=cv2.INTER_AREA)
        half = cv2.GaussianBlur(half, (0, 0), 1.6 + 2.5 * dof)
        bl = cv2.resize(half, (W, H), interpolation=cv2.INTER_LINEAR)
        m = np.clip((_radial() - P.get('dof_r0', 0.45)) / 0.55, 0, 1) * min(1.0, dof * 1.6)
        m = m[..., None]
        x = x + (bl - x) * m

    # exposure + white-hot crosstalk
    x *= P.get('exposure', 1.0)
    mx = x.max(axis=2, keepdims=True)
    x += np.maximum(mx - 1.0, 0) * 0.35   # v2: gentler white-hot
    y = 1.0 - np.exp(-x * 1.25)

    # chromatic aberration
    ca = P.get('ca', 0.0025)
    if ca > 0:
        for ch, s in ((0, 1 + ca), (2, 1 - ca)):
            M = np.float32([[s, 0, (1 - s) * W / 2], [0, s, (1 - s) * H / 2]])
            y[..., ch] = cv2.warpAffine(np.ascontiguousarray(y[..., ch]), M, (W, H), flags=cv2.INTER_LINEAR,
                                        borderMode=cv2.BORDER_REFLECT)

    # flash (camera-filmed white/pink screen with moiré)
    fl = P.get('flash', 0.0)
    if fl > 0:
        fc = np.array(P.get('flash_col', (1.0, 0.92, 0.95)), np.float32)
        mo = moire_tex()
        fimg = fc[None, None, :] * (0.82 + 0.18 * mo[..., None])
        edge = np.clip(_radial() - 0.2, 0, 1)[..., None]
        fimg = fimg * (1 - edge * np.array([0.0, 0.6, 0.15], np.float32))  # magenta edges
        y = y * (1 - fl) + fimg * fl

    # rolling refresh band (filmed screen)
    band = P.get('band', 0.06)
    if band > 0:
        ph = (t_frame * 0.37) % 1.0
        yy = (np.arange(H, dtype=np.float32) / H - ph) % 1.0
        prof = 1 - band * np.exp(-((yy - 0.5) ** 2) / (2 * 0.08 ** 2))
        y *= prof[:, None, None]

    # vignette
    vg = 1 - 0.38 * np.clip(_radial() - 0.35, 0, 1) ** 1.5
    y *= vg[..., None]

    # glitch: horizontal slice displacement
    gl = P.get('glitch', 0.0)
    if gl > 0:
        rng = np.random.default_rng(int(t_frame * 1000) % 100000)
        n = int(3 + 8 * gl)
        for _ in range(n):
            y0 = int(rng.integers(0, H - 10)); h = int(rng.integers(4, int(30 + 120 * gl)))
            dx = int(rng.normal(0, 60 * gl))
            y[y0:y0 + h] = np.roll(y[y0:y0 + h], dx, axis=1)
            if rng.random() < 0.5:
                y[y0:y0 + h, :, int(rng.integers(0, 3))] *= 0.3

    # grain
    g = _grain_tex()
    ox = int(hash1(t_frame, 3) * 60); oy = int(hash1(t_frame, 5) * 60)
    gn = g[oy:oy + H // 2, ox:ox + W // 2]
    gn = cv2.resize(gn, (W, H), interpolation=cv2.INTER_LINEAR)
    y += gn[..., None] * P.get('grain', 0.018)

    # lift blacks a touch
    y = y * (1 - 0.006) + 0.004
    return np.clip(y * 255.0 + 0.5, 0, 255).astype(np.uint8)
