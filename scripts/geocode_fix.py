#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ズレ座標の補正（厳選・手動検証済み）。
GSI/Nominatimで両方検証し目視確認した町centroidだけを使う。誤検知(大字/字で正しい店)は触らない。
町centroid＝近傍精度なので geo='town'（UIで「おおよその位置」と注記表示）。"""
import json, re, os, math

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
GEO = os.path.join(ROOT, "data", "stores.geo.json")

# 目視確認した正しい町centroid（lat,lng）。キー＝address_1から「大分市」を除いた町名。
# 北下郡 は下郡地区なので下郡centroidへ。
VERIFIED = {
    "北下郡": (33.22327, 131.62607),   # 下郡地区（GSI「大分市下郡」/Nominatim 下郡信号場と一致）
    "椎迫":   (33.22608, 131.59527),   # Nominatim 椎迫入口
    "津留":   (33.23959, 131.62608),   # Nominatim 南津留
    "春日浦": (33.24619, 131.59640),   # Nominatim 春日浦
}

_Z2H = str.maketrans("０１２３４５６７８９－ー―‐−　", "0123456789----- ")
def z2h(s): return (s or "").translate(_Z2H)
def hav(a, b):
    R=6371000; t=math.pi/180
    dla=(b[0]-a[0])*t; dlo=(b[1]-a[1])*t
    h=math.sin(dla/2)**2+math.cos(a[0]*t)*math.cos(b[0]*t)*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))

def town_of(a1, a2):
    t = z2h(a1).replace("大分県", "").replace("大分市", "").strip()
    if t: return re.sub(r"[0-9\-丁目番地号組の字].*$", "", t)
    m = re.match(r"[一-龯ぁ-んァ-ヶ々]+", z2h(a2))  # address_1が「大分市」だけ→address_2先頭
    return m.group(0) if m else ""

def main():
    d = json.load(open(GEO, encoding="utf-8"))
    fixed = 0
    for x in d:
        if x["lat"] is None: continue
        t = town_of(x["address_1"], x["address_2"])
        if t in VERIFIED:
            c = VERIFIED[t]
            if hav((x["lat"], x["lng"]), c) > 600:   # 明確にズレている時だけ（4エリアは全店が誤座標に固まっている）
                print(f"  FIX {x['store_name'][:24]:<24}｜{x['address_1']}{x['address_2'][:8]} : ({x['lat']:.4f},{x['lng']:.4f})→({c[0]:.4f},{c[1]:.4f}) {hav((x['lat'],x['lng']),c)/1000:.1f}km")
                x["lat"], x["lng"], x["geo"] = c[0], c[1], "town"
                fixed += 1
    json.dump(d, open(GEO, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\n補正 {fixed} 件 → data/stores.geo.json を更新")

if __name__ == "__main__": main()
