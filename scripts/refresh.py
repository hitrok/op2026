#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
おおいたペイ加盟店マップ — 増分リフレッシュ（QA済み座標を保全）

入力: data/store_list.raw.json  (公式 store_list.json を保存したもの)
      data/stores.geo.json      (現行データ＝QA済み座標を含む)
出力: data/stores.geo.json      (公式の最新属性に更新。既存店は座標を再利用、新規/移転のみジオコーディング)

geocode.py を全件再ジオコーディングすると、geocode_fix.py / geocode_qa.py で手当てした
座標が失われうる。本スクリプトはブラウザ側 app.js の update() と同じ増分マージで、
  - 既存 store_id かつ住所が同じ → 既存の lat/lng/geo を保持（公式の他属性のみ更新）
  - 新規 or 住所変更 → 国土地理院でジオコーディング
  - 公式から消えた店 → 出力から除外
出力は store_id で安定ソートし、git diff をクリーンに保つ。
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import geocode as g  # z2h/candidates/gsi_lookup/geocode_store/cache/CACHE を再利用

RAW = os.path.join(ROOT, "data", "store_list.raw.json")
OUT = os.path.join(ROOT, "data", "stores.geo.json")


def main():
    fresh = json.load(open(RAW, encoding="utf-8"))
    fresh = fresh["data"] if isinstance(fresh, dict) else fresh
    cur = []
    if os.path.exists(OUT):
        cur = json.load(open(OUT, encoding="utf-8"))
    curm = {s["store_id"]: s for s in cur}

    out, todo = [], []
    for f in fresh:
        c = curm.get(f["store_id"])
        if (c and c.get("lat") is not None
                and c.get("address_1") == f.get("address_1")
                and c.get("address_2") == f.get("address_2")):
            rec = dict(f)
            rec["lat"], rec["lng"], rec["geo"] = c["lat"], c["lng"], c.get("geo", "full")
            out.append(rec)
        else:
            rec = dict(f)
            rec["lat"] = rec["lng"] = None
            rec["geo"] = "pending"
            out.append(rec)
            todo.append(rec)

    added = sum(1 for r in todo if r["store_id"] not in curm)
    changed = len(todo) - added
    removed = sum(1 for sid in curm if sid not in {f["store_id"] for f in fresh})
    print(f"fresh={len(fresh)} reuse={len(out)-len(todo)} new/moved={len(todo)} "
          f"(added={added} changed={changed}) removed={removed}", flush=True)

    for i, s in enumerate(todo, 1):
        lat, lng, acc = g.geocode_store(s)
        s["lat"], s["lng"], s["geo"] = lat, lng, acc
        if i % 20 == 0 or i == len(todo):
            json.dump(g.cache, open(g.CACHE, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"  geocoded {i}/{len(todo)}", flush=True)

    json.dump(g.cache, open(g.CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    out.sort(key=lambda s: s["store_id"])
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)

    none = sum(1 for s in out if s.get("geo") in ("none", "pending") or s.get("lat") is None)
    print(f"wrote {OUT}: {len(out)} stores ({none} without coordinates)", flush=True)


if __name__ == "__main__":
    main()
