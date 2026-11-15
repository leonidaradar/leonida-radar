#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
90 günlük senaryo modeli. BU BİR TAHMİN DEĞİL, açık varsayımlı bir hesaptır.
Olasılıklar ölçülmüş veri değil, yazarın öznel yargısıdır (kaynak: aşağıdaki varsayımlar).
Her varsayımı kendi verinizle değiştirin; sayılar otomatik güncellenir.
Kullanım: python model_90gun.py
"""

# (ad, günlük ortalama YouTube Shorts izlenmesi aralığı, temsilci günlük izlenme, öznel olasılık)
SENARYOLAR = [
    ("A Sönük",       "< 1.000",          500,     0.40),
    ("B Düşük",       "1.000 - 10.000",   4_000,   0.35),
    ("C Orta",        "10.000 - 33.000",  20_000,  0.15),
    ("D Yüksek",      "33.000 - 111.000", 60_000,  0.07),
    ("E Eşik üstü",   ">= 111.000",       150_000, 0.03),
]
GUN = 90
RPM_DUSUK, RPM_ORTA, RPM_YUKSEK = 0.01, 0.04, 0.07   # dolar / 1000 izlenme (kaynaklarda 0,01-0,07)
REKLAM_ESIGI_90G = 10_000_000                          # 1.000 abone + 90 günde 10M Shorts izlenmesi
# Ortaklık varsayımları (HEPSİ varsayım; program şartları doğrulanmadı)
TIKLAMA = 0.0005       # izlenenlerin bağlantıya tıklama oranı (%0,05)
DONUSUM = 0.02         # tıklayanların satın alma oranı (%2)
KOMISYON = 4.0         # satış başına dolar (79,99 dolarda ~%5)


def hesapla(tiklama=TIKLAMA, donusum=DONUSUM, komisyon=KOMISYON):
    toplam_p = round(sum(s[3] for s in SENARYOLAR), 6)
    assert toplam_p == 1.0, f"olasılıklar 1 etmeli: {toplam_p}"
    satirlar, bek_reklam, bek_ort = [], 0.0, 0.0
    p_odeme = p_100 = 0.0
    for ad, aralik, gunluk, p in SENARYOLAR:
        v = gunluk * GUN
        reklam_orta = v / 1000 * RPM_ORTA if v >= REKLAM_ESIGI_90G else 0.0
        reklam_dusuk = v / 1000 * RPM_DUSUK if v >= REKLAM_ESIGI_90G else 0.0
        reklam_yuksek = v / 1000 * RPM_YUKSEK if v >= REKLAM_ESIGI_90G else 0.0
        tik = v * tiklama
        satis = tik * donusum
        ort = satis * komisyon
        bek_reklam += p * reklam_orta
        bek_ort += p * ort
        if v >= REKLAM_ESIGI_90G:
            p_odeme += p
        if reklam_orta + ort >= 100:
            p_100 += p
        satirlar.append((ad, aralik, p, v, reklam_dusuk, reklam_orta, reklam_yuksek, tik, satis, ort))
    return satirlar, bek_reklam, bek_ort, p_odeme, p_100


def yazdir():
    satirlar, br, bo, p_odeme, p_100 = hesapla()
    print("SENARYO | günlük izlenme | olasılık | 90 gün izlenme | reklam (düşük/orta/yüksek) | ortaklık satışı | ortaklık $")
    for ad, aralik, p, v, rd, ro, ry, tik, satis, ort in satirlar:
        print(f"{ad:12s} {aralik:18s} %{p*100:>4.0f}  {v:>12,.0f}   ${rd:,.0f}/${ro:,.0f}/${ry:,.0f}   {satis:6.1f} satış   ${ort:,.0f}")
    print(f"\nBeklenen reklam geliri (RPM orta)   : ${br:,.1f}")
    print(f"Beklenen ortaklık geliri (varsayım) : ${bo:,.1f}")
    print(f"BEKLENEN TOPLAM (90 gün)            : ${br+bo:,.1f}")
    print(f"P(reklam payı eşiğini geçmek)       : %{p_odeme*100:.0f}")
    print(f"P(90 günde toplam >= $100)          : %{p_100*100:.0f}  (reklam + ortaklık, varsayımlara bağlı)")


def duyarlilik():
    print("\nDUYARLILIK: ortaklık tıklama oranı değişirse beklenen toplam (90 gün)")
    for t in (0.0001, 0.0005, 0.002):
        _, br, bo, _, _ = hesapla(tiklama=t)
        print(f"  tıklama %{t*100:.2f}: ${br+bo:,.1f}")


if __name__ == "__main__":
    yazdir()
    duyarlilik()
