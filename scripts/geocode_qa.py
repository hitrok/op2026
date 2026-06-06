#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ジオコーディング品質チェック：住所と一致していない（＝ズレている疑い）店舗を洗い出す。
GSIの返すタイトルに「町名（address_1から大分市を除いた部分）」が含まれているかで判定。"""
import json, re, os, urllib.parse, urllib.request, threading
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
GEO = os.path.join(ROOT, "data", "stores.geo.json")
GSI = "https://msearch.gsi.go.jp/address-search/AddressSearch?q="
TCACHE = os.path.join(HERE, "title_cache.json")

_Z2H = str.maketrans("０１２３４５６７８９－ー―‐−　", "0123456789----- ")
def z2h(s): return (s or "").translate(_Z2H)

lock = threading.Lock()
tcache = json.load(open(TCACHE, encoding="utf-8")) if os.path.exists(TCACHE) else {}

def gsi(q):
    with lock:
        if q in tcache: return tcache[q]
    url = GSI + urllib.parse.quote(q)
    res = None
    try:
        a = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "qa"}), timeout=12))
        if a: res = {"title": a[0]["properties"]["title"], "lat": round(a[0]["geometry"]["coordinates"][1], 6), "lng": round(a[0]["geometry"]["coordinates"][0], 6)}
    except Exception: res = None
    with lock: tcache[q] = res
    return res

def town(a1): return z2h(a1).replace("大分県", "").replace("大分市", "").strip()

def main():
    d = json.load(open(GEO, encoding="utf-8"))
    def work(x):
        q = z2h(x["address_1"]) + z2h(x["address_2"])
        r = gsi(q)
        x["_title"] = r["title"] if r else "(なし)"
        t = town(x["address_1"])
        # 判定：町名がタイトルに含まれていない → ズレ疑い
        x["_bad"] = not (t and t in (r["title"] if r else ""))
        return x
    with ThreadPoolExecutor(max_workers=6) as ex:
        d = list(ex.map(work, d))
    json.dump(tcache, open(TCACHE, "w", encoding="utf-8"), ensure_ascii=False)

    bad = [x for x in d if x["_bad"]]
    print(f"ズレ疑い: {len(bad)} / {len(d)} 店\n")
    from collections import Counter
    by_town = Counter(x["address_1"] for x in bad)
    print("=== 町名別（疑い件数）top25 ===")
    for k, v in by_town.most_common(25):
        print(f"  {v:3d}  {k}")
    print("\n=== 例（住所→GSIタイトル）20件 ===")
    for x in bad[:20]:
        print(f"  {x['store_name']}｜{x['address_1']}{x['address_2']} → 「{x['_title']}」 ({x['lat']},{x['lng']})")
    json.dump([{"id": x["store_id"], "name": x["store_name"], "a1": x["address_1"], "a2": x["address_2"], "lat": x["lat"], "lng": x["lng"], "title": x["_title"]} for x in bad],
              open(os.path.join(HERE, "qa_suspects.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ scripts/qa_suspects.json に {len(bad)}件 保存")

if __name__ == "__main__":
    main()
