"""Synthesised SFX library (numpy + pedalboard). Use via kit.sfx_track(events, dur, path)."""
import math, subprocess, json
import numpy as np
from pedalboard import (Pedalboard, Reverb, LadderFilter, Compressor, Limiter, HighpassFilter, LowpassFilter,
                        Delay, Gain, PeakFilter, HighShelfFilter, Chorus, Distortion)
TOTAL = 30.0

SR = 48000
N = int((TOTAL + 1.5) * SR)
rng = np.random.default_rng(11)
BPM = 120; BEAT = 60 / BPM; BAR = BEAT * 4


def tarr(d):
    return np.arange(int(d * SR)) / SR

def env_ad(n, a=0.002, d=0.2, curve=1.0):
    t = np.arange(n) / SR
    e = np.minimum(1, t / max(a, 1e-4)) * np.exp(-np.maximum(0, t - a) / max(d, 1e-4) * curve)
    return e

def add(buf, x, t, gain=1.0, pan=0.0):
    i = int(t * SR)
    if i < 0:
        x = x[-i:]; i = 0
    j = min(len(buf), i + len(x))
    if j <= i:
        return
    l = math.cos((pan + 1) * math.pi / 4); r = math.sin((pan + 1) * math.pi / 4)
    if x.ndim == 1:
        buf[i:j, 0] += x[:j - i] * gain * l * 1.414
        buf[i:j, 1] += x[:j - i] * gain * r * 1.414
    else:
        buf[i:j] += x[:j - i] * gain

def fx(x, board):
    y = board(x.astype(np.float32).T if x.ndim == 2 else x.astype(np.float32)[None, :], SR)
    return y.T if x.ndim == 2 else y[0]

def noise(n):
    return rng.normal(0, 1, n).astype(np.float32)

def sine_sweep(f0, f1, d, curve='exp'):
    t = tarr(d)
    if curve == 'exp':
        f = f0 * (f1 / f0) ** (t / d)
    else:
        f = f0 + (f1 - f0) * (t / d)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph).astype(np.float32)

def saw(f, d, detune=0.0):
    t = tarr(d)
    return (2 * ((t * f * (1 + detune)) % 1.0) - 1).astype(np.float32)

def sq(f, d, duty=0.5):
    t = tarr(d)
    return np.where((t * f) % 1.0 < duty, 1.0, -1.0).astype(np.float32)

def bandnoise(d, lo, hi):
    return fx(noise(int(d * SR)), Pedalboard([HighpassFilter(lo), LowpassFilter(hi)]))

def mtof(m):
    return 440.0 * 2 ** ((m - 69) / 12)

# ================================================================== SFX
def s_key(v=1.0):
    n = int(0.03 * SR)
    x = noise(n) * env_ad(n, 0.0005, 0.004)
    x = fx(x, Pedalboard([HighpassFilter(1800), LowpassFilter(9000)]))
    tone = np.sin(2 * np.pi * rng.uniform(2200, 3600) * tarr(0.03)) * env_ad(n, 0.0005, 0.006)
    thock = np.sin(2 * np.pi * rng.uniform(140, 190) * tarr(0.03)) * env_ad(n, 0.001, 0.012)
    return (x * 0.5 + tone * 0.18 + thock * 0.35) * v

def s_blip(f=1800, d=0.07):
    return np.sin(2 * np.pi * f * tarr(d)) * env_ad(int(d * SR), 0.002, d / 3)

def s_hit(v=1.0):
    d = 0.9
    sub = sine_sweep(110, 42, d) * env_ad(int(d * SR), 0.002, 0.22)
    tr = noise(int(0.08 * SR)) * env_ad(int(0.08 * SR), 0.0005, 0.02)
    tr = fx(tr, Pedalboard([HighpassFilter(800)]))
    x = sub * 0.9
    x[:len(tr)] += tr * 0.5
    x = fx(x, Pedalboard([Reverb(room_size=0.6, wet_level=0.18, dry_level=0.9, width=1.0)]))
    return x * v

def s_impact():
    d = 2.2
    sub = sine_sweep(90, 28, d) * env_ad(int(d * SR), 0.003, 0.55)
    nb = noise(int(d * SR)) * env_ad(int(d * SR), 0.001, 0.25)
    nb = fx(nb, Pedalboard([LowpassFilter(2500)]))
    x = sub * 1.0 + nb * 0.35
    x = fx(x, Pedalboard([Distortion(drive_db=6), Reverb(room_size=0.85, wet_level=0.3, dry_level=0.8)]))
    return x

def s_riser(d=2.0):
    t = tarr(d)
    n = noise(len(t))
    out = np.zeros(len(t), np.float32)
    # stepped filter sweep via chunks
    seg = 2048
    for i in range(0, len(t), seg):
        k = i / len(t)
        f = 300 * (40 ** k)
        out[i:i + seg] = fx(n[i:i + seg], Pedalboard([HighpassFilter(f * 0.5), LowpassFilter(min(18000, f * 2))]))
    tone = sine_sweep(110, 880, d) * 0.25 + saw(55, d) * 0.0
    e = (t / d) ** 2
    return (out * 0.6 + tone) * e

def s_whoosh(d=0.8, up=True):
    t = tarr(d)
    n = noise(len(t))
    out = np.zeros(len(t), np.float32)
    seg = 1024
    for i in range(0, len(t), seg):
        k = i / len(t)
        k = k if up else 1 - k
        f = 400 * (12 ** k)
        out[i:i + seg] = fx(n[i:i + seg], Pedalboard([HighpassFilter(f * 0.6), LowpassFilter(f * 1.8)]))
    e = np.sin(np.pi * np.clip(t / d, 0, 1)) ** 1.5
    return fx(out * e, Pedalboard([Reverb(room_size=0.5, wet_level=0.2)]))

def s_swell(d=1.2):
    t = tarr(d)
    x = bandnoise(d, 2000, 14000) * (t / d) ** 3
    x += (saw(mtof(62), d) + saw(mtof(69), d, 0.004)) * 0.05 * (t / d) ** 2
    return fx(x, Pedalboard([Reverb(room_size=0.9, wet_level=0.4)]))

def s_byte(i=0):
    d = 0.09
    x = sq(1, d) * 0
    f0 = [700, 900, 1150][i % 3]
    x = np.sin(2 * np.pi * np.cumsum(np.linspace(f0, f0 * 2, int(d * SR))) / SR) * env_ad(int(d * SR), 0.001, 0.03)
    return fx(x.astype(np.float32), Pedalboard([Delay(0.09, 0.3, 0.25)]))

def s_bit(b=0):
    d = 0.025
    return np.sin(2 * np.pi * (3200 if b else 2400) * tarr(d)) * env_ad(int(d * SR), 0.0005, 0.006)

def s_data(d=2.0, v=0.6):
    out = np.zeros(int(d * SR), np.float32)
    t = 0.0
    while t < d - 0.05:
        dd = rng.uniform(0.012, 0.04)
        f = rng.choice([880, 1320, 1760, 2640, 3520]) * rng.choice([1, 1, 0.5, 2])
        x = sq(f, dd, rng.uniform(0.2, 0.5)) * env_ad(int(dd * SR), 0.0005, dd / 2) * 0.25
        i = int(t * SR); out[i:i + len(x)] += x[:len(out) - i]
        t += dd + rng.uniform(0.0, 0.05)
    return fx(out * v, Pedalboard([HighpassFilter(500), LowpassFilter(7000), Delay(0.125, 0.2, 0.2)]))

def s_scramble(d=1.0):
    out = np.zeros(int(d * SR), np.float32)
    t = 0.0
    while t < d - 0.03:
        dd = rng.uniform(0.01, 0.05)
        n = int(dd * SR)
        kind = rng.random()
        if kind < 0.5:
            x = noise(n) * 0.3
        else:
            x = sq(rng.uniform(150, 2500), dd) * 0.25
        x *= env_ad(n, 0.0005, dd)
        i = int(t * SR); out[i:i + n] += x[:len(out) - i]
        t += dd * rng.uniform(0.5, 1.5)
    env = np.exp(-np.arange(len(out)) / SR / (d * 0.6))
    return fx(out * env, Pedalboard([HighpassFilter(200), Distortion(drive_db=10), LowpassFilter(9000)])) * 0.5

def s_cut(i=0):
    d = 0.06
    x = noise(int(d * SR)) * env_ad(int(d * SR), 0.0005, 0.01)
    x = fx(x, Pedalboard([HighpassFilter(3000)]))
    b = s_blip(1500 + 200 * i, 0.04)
    x = x * 0.5
    x[:len(b)] += b * 0.3
    return x

def s_zip(i=0, rev=False):
    d = 0.22
    f0, f1 = (600 + i * 120, 4000) if not rev else (4000, 500 + i * 100)
    x = sine_sweep(f0, f1, d) * env_ad(int(d * SR), 0.003, 0.08) * 0.35
    x += s_whoosh(d, not rev) * 0.4
    return x

def s_ping(rev=False):
    d = 1.2
    x = (np.sin(2 * np.pi * 1180 * tarr(d)) * 0.6 + np.sin(2 * np.pi * 2360 * tarr(d)) * 0.15) * env_ad(int(d * SR), 0.002, 0.2)
    x = fx(x.astype(np.float32), Pedalboard([Delay(0.18, 0.35, 0.3), Reverb(room_size=0.7, wet_level=0.3)]))
    return x[::-1].copy() if rev else x

def s_zap(rev=False):
    d = 0.5
    x = sine_sweep(3800, 160, d) * env_ad(int(d * SR), 0.001, 0.12)
    x += sine_sweep(5200, 300, d) * env_ad(int(d * SR), 0.001, 0.08) * 0.4
    x = fx(x.astype(np.float32), Pedalboard([Chorus(), Reverb(room_size=0.6, wet_level=0.25)])) * 0.5
    return x[::-1].copy() if rev else x

def s_count(d=0.6):
    out = np.zeros(int(d * SR) + 4800, np.float32)
    t = 0.0; k = 0
    while t < d:
        x = s_blip(2000 + k * 40, 0.02) * 0.35
        i = int(t * SR); out[i:i + len(x)] += x
        t += 0.018 + 0.05 * (t / d) ** 2; k += 1
    return out

def s_hop(i=0):
    return fx((s_blip(mtof(74 + [0, 3, 5, 7, 10, 12, 15, 17, 19, 22, 24, 27, 29, 31][i % 14]), 0.06) * 0.5).astype(np.float32),
              Pedalboard([Delay(0.125, 0.25, 0.25)]))

def s_beep(f=1000):
    d = 0.14
    x = np.sin(2 * np.pi * f * tarr(d)) * np.minimum(1, tarr(d) / 0.004) * np.minimum(1, (d - tarr(d)) / 0.01)
    return x.astype(np.float32) * 0.45

def s_hum(d=1.5):
    t = tarr(d)
    x = sum(np.sin(2 * np.pi * 50 * h * t) / h for h in (1, 2, 3, 5)) * 0.25
    x = x + bandnoise(d, 300, 3000) * 0.25
    e = np.minimum(1, t / 0.2) * np.minimum(1, (d - t) / 0.3)
    return (x * e).astype(np.float32)

def s_lock():
    d = 0.4
    x = noise(int(0.02 * SR)) * env_ad(int(0.02 * SR), 0.0003, 0.004)
    y = np.zeros(int(d * SR), np.float32)
    y[:len(x)] += fx(x, Pedalboard([HighpassFilter(2000)])) * 0.7
    y += sine_sweep(160, 70, d) * env_ad(int(d * SR), 0.001, 0.06) * 0.6
    return y

def s_dec(i=0):
    return s_blip(mtof(84 + (i * 5) % 12), 0.05) * 0.22

def s_slice(i=0):
    d = 0.12
    x = noise(int(d * SR)) * env_ad(int(d * SR), 0.001, 0.03)
    return fx(x, Pedalboard([HighpassFilter(4000 + 300 * i)])) * 0.35

def s_id(i=0):
    return s_blip(mtof(72 + [0, 4, 7, 11, 12, 16, 19][i % 7]), 0.08) * 0.35

def s_arc(n=5):
    d = 0.9
    x = s_whoosh(d, True) * 0.5
    for k in range(n):
        b = s_blip(mtof(79 + (k * 7) % 24), 0.18) * 0.12
        i = int(k * 0.06 * SR); x[i:i + len(b)] += b[:len(x) - i]
    return fx(x, Pedalboard([Reverb(room_size=0.8, wet_level=0.35)]))

def s_tick(v=1.0):
    d = 0.03
    x = noise(int(d * SR)) * env_ad(int(d * SR), 0.0003, 0.003)
    return fx(x, Pedalboard([HighpassFilter(5000)])) * 0.35 * v

def s_suck(d=1.0):
    x = s_impact()[: int(1.6 * SR)][::-1].copy()
    x = x[-int(d * SR):]
    return fx(x, Pedalboard([LowpassFilter(3000)])) * 0.6

def s_bars(d=0.4):
    out = np.zeros(int((d + 0.3) * SR), np.float32)
    for k in range(5):
        b = s_blip(mtof(67 + [0, 3, 7, 10, 12][k]), 0.06) * 0.25
        i = int(k * d / 5 * SR); out[i:i + len(b)] += b
    return out

def s_pick():
    d = 0.6
    x = (np.sin(2 * np.pi * mtof(86) * tarr(d)) + 0.5 * np.sin(2 * np.pi * mtof(93) * tarr(d))) * env_ad(int(d * SR), 0.002, 0.15)
    return fx(x.astype(np.float32) * 0.3, Pedalboard([Reverb(room_size=0.7, wet_level=0.3)]))

def s_glitch():
    d = 0.18
    base = np.concatenate([noise(int(0.012 * SR)) * 0.4, sq(rng.uniform(200, 900), 0.012) * 0.3])
    reps = int(d / 0.024)
    x = np.tile(base, reps).astype(np.float32)
    x *= np.linspace(1, 0.3, len(x))
    return fx(x, Pedalboard([HighpassFilter(150), Distortion(drive_db=8), LowpassFilter(8000)])) * 0.45

def s_strobe(i=0):
    d = 0.05
    x = noise(int(d * SR)) * env_ad(int(d * SR), 0.0003, 0.008)
    x = fx(x, Pedalboard([HighpassFilter(2500)])) * 0.4
    b = s_blip(mtof(60 + (i * 7) % 36), 0.04) * 0.2
    x[:len(b)] += b[:len(x)]
    return x

def s_power_off():
    d = 1.4
    x = sine_sweep(1400, 40, 0.45) * env_ad(int(0.45 * SR), 0.001, 0.25) * 0.5
    y = np.zeros(int(d * SR), np.float32)
    y[:len(x)] += x
    st = bandnoise(d, 1500, 12000) * env_ad(int(d * SR), 0.001, 0.35) * 0.25
    y += st
    y[:int(0.01 * SR)] += noise(int(0.01 * SR)) * 0.6
    return fx(y, Pedalboard([Reverb(room_size=0.7, wet_level=0.25)]))

def s_room(d=6.0):
    t = tarr(d)
    x = bandnoise(d, 100, 1500) * 0.12 + np.sin(2 * np.pi * 60 * t) * 0.05 + np.sin(2 * np.pi * 15734 * t) * 0.004
    e = np.minimum(1, t / 0.8) * np.minimum(1, (d - t) / 1.0)
    return (x * e).astype(np.float32)

def s_riser_short(d=0.5):
    return s_riser(max(0.2, d)) * 0.9

SFX = {
    'key': (lambda p: s_key(p.get('v', 1)), 0.55),
    'blip': (lambda p: s_blip(p.get('f', 1800)), 0.25),
    'hit': (lambda p: s_hit(p.get('v', 1)), 0.9),
    'impact': (lambda p: s_impact(), 0.25),
    'riser': (lambda p: s_riser(p['d']), 0.35),
    'riser_short': (lambda p: s_riser_short(p['d']), 0.45),
    'whoosh': (lambda p: s_whoosh(p.get('d', 0.8), p.get('up', True)), 0.6),
    'swell': (lambda p: s_swell(p.get('d', 1.2)), 0.45),
    'byte': (lambda p: s_byte(p['i']), 0.45),
    'bit': (lambda p: s_bit(p['b']), 0.18),
    'data': (lambda p: s_data(p['d'], p.get('v', 0.6)), 0.35),
    'scramble': (lambda p: s_scramble(p.get('d', 1.0)), 0.6),
    'cut': (lambda p: s_cut(p['i']), 0.5),
    'zip': (lambda p: s_zip(p['i'], p.get('rev', False)), 0.45),
    'zip_in': (lambda p: s_whoosh(max(0.3, p['d']), False), 0.5),
    'ping': (lambda p: s_ping(), 0.22),
    'ping_rev': (lambda p: s_ping(True), 0.35),
    'zap': (lambda p: s_zap(p.get('rev', False)), 0.55),
    'count': (lambda p: s_count(p['d']), 0.4),
    'hop': (lambda p: s_hop(p['i']), 0.4),
    'beep': (lambda p: s_beep(p.get('f', 1000)), 0.35),
    'hum': (lambda p: s_hum(p['d']), 0.3),
    'lock': (lambda p: s_lock(), 0.6),
    'dec': (lambda p: s_dec(p['i']), 0.5),
    'slice': (lambda p: s_slice(p['i']), 0.55),
    'id': (lambda p: s_id(p['i']), 0.5),
    'arc': (lambda p: s_arc(p['n']), 0.45),
    'tick': (lambda p: s_tick(p.get('v', 1.0)), 0.5),
    'suck': (lambda p: s_suck(p['d']), 0.7),
    'bars': (lambda p: s_bars(p['d']), 0.5),
    'pick': (lambda p: s_pick(), 0.5),
    'glitch': (lambda p: s_glitch(), 0.6),
    'strobe': (lambda p: s_strobe(p['i']), 0.5),
    'power_off': (lambda p: s_power_off(), 0.8),
    'room': (lambda p: s_room(), 0.5),
}

