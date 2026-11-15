#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Leonida Radar ses kimliği sentezleyici. Tamamen kodla üretilir: örnek (sample), hazır müzik ya da
başkasının kaydı YOKTUR. Gereken: numpy, scipy, ffmpeg.
Kullanım:  python make_sound.py A     (rahat: ~96 BPM)   ->  assets/music.mp3 + assets/ping.wav
           python make_sound.py B     (daha enerjik: ~112 BPM)
Önizleme:  python make_sound.py A --out preview_A
"""
import sys, subprocess
from pathlib import Path
import numpy as np
from scipy.signal import butter, lfilter, fftconvolve

SR = 44100
ROOT = Path(__file__).resolve().parent

VARIANTS = {
    # bpm, arp adımı (bir vuruşta kaç nota), kick her vuruşta mı, clap var mı, parlaklık
    "A": dict(bpm=96, arp_per_beat=2, kick_every_beat=False, clap=False, pad_cut=1300, arp_gain=0.36, seed=7),
    "B": dict(bpm=112, arp_per_beat=4, kick_every_beat=True, clap=True, pad_cut=1900, arp_gain=0.32, seed=11),
}
CHORDS = [(57, [0, 3, 7]), (53, [0, 4, 7]), (60, [0, 4, 7]), (55, [0, 4, 7])]   # Am - F - C - G (her biri 2 ölçü)


def mtof(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def lp(x, fc, order=2):
    b, a = butter(order, fc / (SR / 2), "low"); return lfilter(b, a, x)


def hp(x, fc, order=2):
    b, a = butter(order, fc / (SR / 2), "high"); return lfilter(b, a, x)


def saw(f, t, maxh=14):
    out = np.zeros_like(t)
    for k in range(1, maxh + 1):
        if f * k > 9000: break
        out += np.sin(2 * np.pi * f * k * t) / k
    return out * (2 / np.pi)


def place(buf, sig, start):
    i = int(start * SR); n = min(len(sig), len(buf) - i)
    if n > 0: buf[i:i + n] += sig[:n]


def render(variant):
    p = VARIANTS[variant]; rng = np.random.default_rng(p["seed"])
    beat = 60.0 / p["bpm"]; bar = 4 * beat; bars = 8; loop = bars * bar
    N = int((loop + 2.5) * SR)                    # kuyruk, döngüye geri katlanacak
    t_all = np.arange(N) / SR
    pad = np.zeros(N); arp_l = np.zeros(N); arp_r = np.zeros(N); bass = np.zeros(N)
    kick = np.zeros(N); hat = np.zeros(N); clap = np.zeros(N)

    for ci, (root, ints) in enumerate(CHORDS):
        start, dur = ci * 2 * bar, 2 * bar
        seg_t = np.arange(int((dur + 0.8) * SR)) / SR
        seg = np.zeros_like(seg_t)
        for iv in ints + [12]:
            for det in (-7, 0, 7):                # üç hafif detune: sıcak, geniş pad
                f = mtof(root + iv) * 2 ** (det / 1200)
                seg += saw(f, seg_t) * 0.12
        env = np.minimum(1, seg_t / 0.5) * np.clip((dur + 0.8 - seg_t) / 0.8, 0, 1)
        place(pad, lp(seg * env, p["pad_cut"]), start)

        # arpej: akor notaları, hafif vuruşlu (pluck)
        notes = [root + ints[0] + 12, root + ints[1] + 12, root + ints[2] + 12, root + ints[1] + 24,
                 root + ints[2] + 12, root + ints[1] + 12, root + ints[2] + 24, root + ints[1] + 12]
        step = beat / p["arp_per_beat"]; n_steps = int(dur / step)
        for s in range(n_steps):
            m = notes[s % len(notes)]; f = mtof(m)
            tt = np.arange(int(0.55 * SR)) / SR
            tone = (np.sin(2 * np.pi * f * tt) + 0.55 * np.sin(2 * np.pi * 2 * f * tt) + 0.30 * np.sin(2 * np.pi * 3 * f * tt) + 0.14 * np.sin(2 * np.pi * 5 * f * tt)) * np.exp(-tt * 7.5)
            tone *= np.minimum(1, tt / 0.004)
            pan = 0.35 + 0.3 * ((s % 4) / 3)       # 0.35..0.65 arası hafif gezinen
            place(arp_l, tone * (1 - pan), start + s * step); place(arp_r, tone * pan, start + s * step)

        # bas
        for k, off in enumerate([0, 2.5]):
            tt = np.arange(int(1.0 * SR)) / SR
            f = mtof(root - 12)
            b = np.sin(2 * np.pi * f * tt) * np.exp(-tt * (2.2 if k == 0 else 4.0)) * np.minimum(1, tt / 0.01)
            for rep in range(2):                    # 2 ölçüde tekrar
                place(bass, b, start + rep * bar + off * beat)

    # davul (2. ölçüden itibaren kick, 3. ölçüden itibaren hat/clap: sahne yavaş yavaş açılır)
    tk = np.arange(int(0.45 * SR)) / SR
    k_tone = np.sin(2 * np.pi * np.cumsum(48 + 70 * np.exp(-tk * 35)) / SR) * np.exp(-tk * 9)
    kick_times = []
    for b in range(1, bars):
        beats = [0, 1, 2, 3] if p["kick_every_beat"] else [0, 2]
        for bt in beats: kick_times.append(b * bar + bt * beat)
    for ktm in kick_times: place(kick, k_tone, ktm)
    th = np.arange(int(0.05 * SR)) / SR
    h_tone = hp(rng.standard_normal(len(th)), 7000) * np.exp(-th * 90)
    for b in range(2, bars):
        for e in range(8): 
            if e % 2 == 1: place(hat, h_tone, b * bar + e * beat / 2)
    if p["clap"]:
        tc = np.arange(int(0.16 * SR)) / SR
        c_tone = lp(hp(rng.standard_normal(len(tc)), 1200), 5000) * np.exp(-tc * 28)
        for b in range(2, bars):
            for bt in (1, 3): place(clap, c_tone, b * bar + bt * beat)

    # sidechain: kick anında pad ve arp kısa süre kısılır (nefes alan, rahat his)
    duck = np.ones(N)
    for ktm in kick_times:
        i = int(ktm * SR); L = int(0.22 * SR)
        if i + L < N: duck[i:i + L] = np.minimum(duck[i:i + L], 0.55 + 0.45 * np.linspace(0, 1, L) ** 1.5)

    mid = pad * duck * 0.9
    left = mid + arp_l * p["arp_gain"] * 3 * duck + bass * 0.38 + kick * 0.55 + hat * 0.22 + clap * 0.16
    right = mid + arp_r * p["arp_gain"] * 3 * duck + bass * 0.38 + kick * 0.55 + hat * 0.22 + clap * 0.16

    # yankı: kısa ve hafif oda hissi
    ir_n = int(1.5 * SR); ir_t = np.arange(ir_n) / SR
    wet = []
    for ch, seed in ((left, 1), (right, 2)):
        r2 = np.random.default_rng(seed)
        ir = lp(r2.standard_normal(ir_n), 4500) * np.exp(-ir_t * 3.2); ir /= np.abs(ir).sum() / 8
        wet.append(fftconvolve(pad + (arp_l if seed == 1 else arp_r) * 3, ir)[:N])
    left = left + wet[0] * 0.20; right = right + wet[1] * 0.20

    # kuyruğu başa katla: kusursuz döngü
    L0 = int(loop * SR)
    def fold(x):
        y = x[:L0].copy(); tail = x[L0:L0 + (N - L0)]; y[:len(tail)] += tail[:L0]; return y
    stereo = np.stack([fold(left), fold(right)], axis=1)
    stereo = np.tanh(stereo * 0.9)
    stereo *= 0.89 / np.abs(stereo).max()
    return stereo


def ping():
    """Ses imzası: iki notalı çan 'tu-ding' (E5 -> A5) + iki yankı. ~1,3 sn."""
    n = int(1.4 * SR); out = np.zeros((n, 2))
    def bell(f, length=0.9):
        tt = np.arange(int(length * SR)) / SR
        idx = 2.2 * np.exp(-tt * 6)
        s = np.sin(2 * np.pi * f * tt + idx * np.sin(2 * np.pi * 2 * f * tt)) * np.exp(-tt * 4.2)
        return s * np.minimum(1, tt / 0.003)
    sig = np.zeros(n)
    place(sig, bell(659.25), 0.0); place(sig, bell(880.0), 0.14)
    echo = sig.copy()
    for d, g in ((0.30, 0.45), (0.60, 0.22)):
        i = int(d * SR); echo[i:] += sig[:n - i] * g
    out[:, 0] = echo * 0.9; out[:, 1] = np.roll(echo, int(0.012 * SR)) * 0.9
    out *= 0.85 / np.abs(out).max()
    return out


def write_wav(path, stereo):
    import wave
    data = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(data.tobytes())


def main():
    variant = (sys.argv[1] if len(sys.argv) > 1 else "A").upper()
    if variant not in VARIANTS: print("Seçenek: A ya da B"); sys.exit(1)
    outdir = ROOT / "assets"; outdir.mkdir(exist_ok=True)
    stereo = render(variant)
    write_wav(outdir / "music.wav", stereo)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(outdir / "music.wav"), "-c:a", "libmp3lame", "-b:a", "192k", str(outdir / "music.mp3")], check=True)
    (outdir / "music.wav").unlink()
    write_wav(outdir / "ping.wav", ping())
    print(f"Hazır: assets/music.mp3 ({len(stereo)/SR:.1f} sn döngü, {VARIANTS[variant]['bpm']} BPM) ve assets/ping.wav")


if __name__ == "__main__":
    main()
