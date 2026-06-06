#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
おおいたペイ加盟店マップ — 住所ジオコーディング（ベースライン生成）

入力: data/store_list.raw.json  (oita-pay の store_list.json をそのまま保存したもの)
出力: data/stores.geo.json      (各店舗に lat/lng/geo[精度] を付与した配列)
      scripts/geocode_cache.json (住所→座標キャッシュ。再実行で再ジオコーディングを回避)

ジオコーダ: 国土地理院 住所検索API（無料・キー不要・CORS可）
  https://msearch.gsi.go.jp/address-search/AddressSearch?q=<住所>

このロジック（住所正規化→フルアドレス→番地のみ→丁目のみのフォールバック）は
ブラウザ側の「更新」機能(app.js geocodeAddress)と意図的に揃えている。
"""
import json, re, os, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "data", "store_list.raw.json")
OUT = os.path.join(ROOT, "data", "stores.geo.json")
CACHE = os.path.join(HERE, "geocode_cache.json")
GSI = "https://msearch.gsi.go.jp/address-search/AddressSearch?q="

# 全角英数字・記号 -> 半角
_Z2H = str.maketrans(
    "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ－ー―‐−　",
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz----- ",
)

def z2h(s: str) -> str:
    return (s or "").translate(_Z2H)

def lead_number(s: str) -> str:
    """正規化済み文字列から、先頭の住所番地部分（数字・ハイフン・丁目番地号）だけを抜く。
    建物名・階・テナント名を落としてヒット率を上げる。"""
    s = s.strip()
    m = re.match(r"^[0-9\-\s丁目番地号の]+", s)
    return (m.group(0).strip() if m else "").strip()

def candidates(a1: str, a2: str):
    """ジオコーディング候補クエリ（精度高い順）を返す。"""
    a1 = z2h(a1).strip()
    a2 = z2h(a2).strip()
    cands = []
    if a1 and a2:
        cands.append(("full", f"{a1}{a2}"))
        ln = lead_number(a2)
        if ln and ln != a2:
            cands.append(("number", f"{a1}{ln}"))
    if a1:
        cands.append(("chome", a1))   # 丁目センター（近似）
    # 重複除去（順序維持）
    seen, out = set(), []
    for acc, q in cands:
        if q and q not in seen:
            seen.add(q); out.append((acc, q))
    return out

_lock = threading.Lock()
cache = {}
if os.path.exists(CACHE):
    try:
        cache = json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        cache = {}

def gsi_lookup(q: str):
    with _lock:
        if q in cache:
            return cache[q]
    url = GSI + urllib.parse.quote(q)
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "oitapay-map/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                arr = json.loads(r.read().decode("utf-8"))
            res = None
            if isinstance(arr, list) and arr:
                c = arr[0]["geometry"]["coordinates"]  # [lng, lat]
                res = [round(c[1], 6), round(c[0], 6)]   # -> [lat, lng]
            with _lock:
                cache[q] = res
            return res
        except Exception:
            time.sleep(0.6 * (attempt + 1))
    with _lock:
        cache[q] = None
    return None

def geocode_store(s: dict):
    for acc, q in candidates(s.get("address_1", ""), s.get("address_2", "")):
        latlng = gsi_lookup(q)
        if latlng:
            return latlng[0], latlng[1], acc
    return None, None, "none"

def main():
    data = json.load(open(RAW, encoding="utf-8"))["data"]
    total = len(data)
    done = {"n": 0}

    def work(s):
        lat, lng, acc = geocode_store(s)
        s["lat"], s["lng"], s["geo"] = lat, lng, acc
        with _lock:
            done["n"] += 1
            n = done["n"]
        if n % 50 == 0 or n == total:
            json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"  {n}/{total} geocoded", flush=True)
        return s

    print(f"geocoding {total} stores via GSI ...", flush=True)
    with ThreadPoolExecutor(max_workers=6) as ex:
        out = list(ex.map(work, data))

    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)

    ok = sum(1 for s in out if s["geo"] in ("full", "number"))
    approx = sum(1 for s in out if s["geo"] == "chome")
    fail = sum(1 for s in out if s["geo"] == "none")
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"done. exact/number={ok}  chome(approx)={approx}  fail={fail}", flush=True)
    print(f"wrote {OUT}", flush=True)

if __name__ == "__main__":
    main()
