#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gelir hesaplayıcı: bir VARSAYIM aracıdır; tahmin ya da garanti DEĞİLDİR.
Eşikler: YouTube Yardım, Tubefilter, PPC Land (Ağustos-Ekim 2026); TikTok Creator Rewards şartları (2026).
Kullanım:  python revenue_calc.py GUNLUK_YT_IZLENME [GUNLUK_TT_IZLENME]
Örnek:     python revenue_calc.py 5000 3000
"""
import sys

YT_FAN_FUNDING_90D = 3_000_000    # 500 abone + 3 genel video + 3M Shorts izlenme / 90 gün (ülkeye bağlı)
YT_ADS_NOW_90D = 10_000_000       # 1.000 abone + 10M Shorts izlenme / 90 gün (1 Şub 2027 öncesi başvuru)
YT_ADS_2027_90D = 20_000_000      # 1 Şub 2027 sonrası YENİ başvurular
RPM = {"düşük": 0.01, "orta": 0.04, "yüksek": 0.07}   # dolar / 1000 izlenme (kaynaklarda $0.01-0.07)
TT_VIEWS_30D = 100_000            # TikTok Creator Rewards: 10.000 takipçi + 100.000 izlenme / 30 gün
TT_COUNTRIES = "ABD, Birleşik Krallık, Almanya, Japonya, G.Kore, Fransa, Meksika, Brezilya (Kasım 2026 kaynağı)"


def yt(daily):
    v90 = daily * 90
    print(f"\nYOUTUBE SHORTS | günlük {daily:,.0f} izlenme -> 90 günde {v90:,.0f}")
    for name, thr in [("Hayran fonu eşiği (3M)", YT_FAN_FUNDING_90D),
                      ("Reklam payı eşiği, şimdi (10M)", YT_ADS_NOW_90D),
                      ("Yeni başvuru, 1 Şub 2027 sonrası (20M)", YT_ADS_2027_90D)]:
        print(f"  {name:42s}: {'GEÇER' if v90 >= thr else 'geçmez'} (gereken günlük ~ {thr/90:,.0f})")
    if v90 >= YT_ADS_NOW_90D:
        for k, r in RPM.items():
            print(f"  tahmini 90 gün geliri, RPM {k} (${r}): ${v90/1000*r:,.0f} (~ ${v90/1000*r/3:,.0f}/ay)")
    else:
        print("  reklam geliri: 0 (eşik geçilmediği için)")


def tt(daily):
    v30 = daily * 30
    print(f"\nTIKTOK | günlük {daily:,.0f} izlenme -> 30 günde {v30:,.0f}")
    print(f"  Creator Rewards izlenme eşiği (100K/30 gün): {'GEÇER' if v30 >= TT_VIEWS_30D else 'geçmez'} "
          f"(gereken günlük ~ {TT_VIEWS_30D/30:,.0f})")
    print(f"  Ek şartlar: 10.000 takipçi, 18+, video >= 60 sn. Ülke listesi: {TT_COUNTRIES}")
    print("  Not: örnek videolarımız 15 sn; 60 sn altı videolar bu programdan kazandırmaz.")


def affiliate(sales, price=79.99, commission=0.05):
    print(f"\nORTAKLIK (varsayım): {sales} satış x ${price} x %{commission*100:.0f} = ${sales*price*commission:,.2f} "
          "(oran ve program şartları DOĞRULANMADI)")


if __name__ == "__main__":
    a = [float(x) for x in sys.argv[1:]]
    if not a:
        print(__doc__)
        sys.exit(0)
    yt(a[0])
    if len(a) > 1:
        tt(a[1])
    affiliate(10)
