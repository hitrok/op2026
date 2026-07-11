#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_site.py — 大分市プレミアム付き商品券2026 加盟店マップ の静的SEO/AIOページ生成器

data/stores.geo.json を「唯一の真実の源」として、以下を決定論的に再生成する:
  - index.html の生成ブロック（JSON-LD / 概要・FAQ・データ・フッターの可視テキスト）
  - list/index.html              … 加盟店一覧ハブ（全件の入口）
  - c/<slug>/[<n>/]index.html    … カテゴリ別（買う/食べる/暮らす/遊ぶ/泊まる、大きいものは連番分割）
  - g/<slug>/index.html          … 上位ジャンル別（居酒屋・コンビニ等）
  - area/<slug>/index.html       … 上位エリア別（要町・中央町等）
  - sitemap.xml / robots.txt / llms.txt / llms-full.txt

方針:
  * クロール可能な実HTMLテキストとして店名・業種・住所・対応(デジタル/紙)・規模を出力（JSではなくView Sourceに出す）。
  * 電話番号(tel_no)は出力しない（個人事業主の携帯番号が多くPII配慮）。
  * geo が 'full'/'number' 以外（おおよその位置）の店は精密座標のJSON-LDを出さない。
  * 全ページに「非公式」恒久表示＋公式サイトへのリンク。『公式』を騙らない。
  * 件数・日付は本スクリプトで一括算出し、prose/JSON-LD/llms 全てを常に同期。
実行: python3 scripts/build_site.py
"""
import json, os, re, html, datetime, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data", "stores.geo.json")
BASE = "https://op2026.plan8.jp"
OFFICIAL = "https://2026.oita-pay.jp"
OFFICIAL_JSON = "https://2026.oita-pay.jp/docs/store_list/store_list.json"
CITY_OFFICIAL = "https://www.city.oita.oita.jp/o154/shigotosangyo/shokogyo/syouhinken3.html"
MAKER = "https://plan8.jp"
PER_PAGE = 250
FIRST_PUB = "2026-06-06"   # 初回公開日（WebPage.datePublished 用・定数管理）

# ----- 表記ゆれ（呼称の言い換え）---------------------------------------------
# 公式内で「付」「付き」が併存する: 大分市役所サイトは「付」（送り仮名なし）、
# 大分商工会議所・公式特設サイト(2026.oita-pay.jp)は「付き」（送り仮名あり）。
# どちらか一方を“唯一の正式表記”として断定しない。本文での両表記併記は KW_BOTH を使う。
KW_KI    = "大分市プレミアム付き商品券"   # 付き：商工会議所・公式特設サイト表記
KW_NOKI  = "大分市プレミアム付商品券"     # 付 ：大分市役所サイト表記
KW_SHORT = "大分市プレミアム商品券"       # 「付/付き」省略・一般検索の最頻形
KW_BOTH  = "大分市プレミアム付き商品券（プレミアム付商品券）"  # 1箇所で両表記を括弧併記する安全形
# GSC上位クエリ（2026-07時点）に合わせた表記ゆれ・意図語
# 主軸: 「大分市プレミアム商品券 使える店一覧」系 ＋ 加盟店 ＋ 中小店舗
ALIASES  = [
    KW_SHORT, KW_SHORT + "2026",
    f"{KW_SHORT} 使える店一覧", f"{KW_SHORT} 使える店", f"{KW_SHORT} 使える 店一覧",
    f"{KW_SHORT} 使える店一覧 2026", f"{KW_SHORT} 使える 店 2026",
    f"{KW_SHORT} 加盟店", f"{KW_SHORT} 中小店舗", f"{KW_SHORT} 中小 店舗一覧",
    f"{KW_SHORT} 中小店舗検索", "大分プレミアム商品券 加盟店", "大分プレミアム商品券",
    KW_KI, KW_KI + "2026", KW_NOKI, KW_NOKI + "2026",
    "プレミアム商品券", "プレミアム付商品券", "プレミアム付き商品券",
    "大分市 商品券", "大分市 商品券 2026", "おおいた市プレミアム商品券",
]

# ----- 制度の検証済み事実（公式「概要」PDF・大分市サイト＝2026年3月時点）----------
# 出典: 2026.oita-pay.jp/docs/information/概要.pdf, city.oita.oita.jp/o154/...
# 非公式サイト掲載のため「2026年3月時点」「最新は公式で確認」を必ず併記する。
FACTS_ASOF = "2026年3月時点"
PROGRAM_FACTS = [
    ("プレミアム率", "30%（販売額1万円につき1万3,000円分を購入）"),
    ("利用期間", "2026年6月1日（月）〜8月31日（月）"),
    ("購入・チャージ期間", "2026年6月1日（月）〜6月15日（月）"),
    ("購入上限", "1人4冊まで（最大4万円→5万2,000円分・紙か電子のいずれか一方）"),
    ("1冊の内訳", "全店舗共通券6,000円分＋中小・小規模店専用券7,000円分＝1万3,000円分"),
    ("購入方法", "事前申込制の抽選方式（先着ではありません）"),
    ("購入対象", "大分県内在住者（大分市在住者を優先）"),
    ("発行総数", "34万9,000冊（紙10万4,700冊／電子24万4,300冊）"),
]

esc = html.escape

# ---------------------------------------------------------------- load & stats
stores = json.load(open(DATA, encoding="utf-8"))
stores.sort(key=lambda s: s.get("store_id", ""))
TOTAL = len(stores)
BUILD_DATE = datetime.date.fromtimestamp(os.path.getmtime(DATA)).isoformat()

CAT_ORDER = ["食べる", "買う", "暮らす", "遊ぶ", "泊まる"]
CAT_SLUG = {"食べる": "taberu", "買う": "kau", "暮らす": "kurasu", "遊ぶ": "asobu", "泊まる": "tomaru"}
CAT_EMOJI = {"食べる": "🍴", "買う": "🛍️", "暮らす": "🏠", "遊ぶ": "🎡", "泊まる": "🛏️"}

# 上位ジャンル（store_category_minor_name）→ ローマ字slug。ここに無い業種はジャンルページを作らない。
GENRE_SLUG = {
    "衣類・靴・雑貨・アクセサリー": "fashion", "居酒屋・小料理": "izakaya", "コンビニ": "konbini",
    "エステ・サロン・マッサージ": "salon", "和食・すし・割烹": "washoku", "カフェ・喫茶店": "cafe",
    "理容室・美容室": "beauty", "焼肉・肉料理・鉄板焼き": "yakiniku", "スーパー": "super",
    "ドラッグストア": "drugstore", "食堂・レストラン": "restaurant",
    "時計・宝石・メガネ・コンタクト": "watch-jewelry", "和菓子・洋菓子": "sweets",
    "ラーメン": "ramen", "ガソリンスタンド": "gas", "家電": "kaden",
    # 追加（しきい値20以上の業種でロングテールを拡張）
    "惣菜・弁当屋": "bento", "軽食・ファストフード": "fastfood",
    "自動車販売・整備・修理・タイヤ": "car", "スナック・ラウンジ・Bar": "bar",
    "医療・介護・福祉": "care", "美容・化粧品店": "cosme",
    "イタリアン・フレンチ": "italian-french", "うどん、そば": "udon-soba",
    "中華料理": "chuka", "タクシー・レンタカー": "taxi",
    "自転車・バイク販売・修理": "bike", "造園・住宅関連": "housing",
    "パン・ベーカリー": "bakery",
}
# 上位エリア（address_1 の町名）→ ローマ字slug。ここに無い町はエリアページを作らない。
# ※ "大分市市" "大分市森" 等の住所パース由来のノイズ町名は意図的に含めない。
AREA_SLUG = {
    "大分市要町": "kanamemachi", "大分市中央町": "chuomachi", "大分市府内町": "funaimachi",
    "大分市公園通り西": "koendori-nishi", "大分市都町": "miyakomachi", "大分市玉沢": "tamazawa",
    "大分市森町": "morimachi", "大分市萩原": "hagiwara", "大分市田中町": "tanakamachi",
    "大分市中戸次": "nakahetsugi", "大分市下郡": "shimogori", "大分市金池町": "kanaikemachi",
    "大分市大手町": "otemachi", "大分市皆春": "minaharu", "大分市畑中": "hatanaka",
    # 追加（しきい値20以上の実在町名でロングテールを拡張）
    "大分市賀来南": "kakuminami", "大分市上宗方": "kamimunakata", "大分市光吉": "mitsuyoshi",
    "大分市高城西町": "takajo-nishimachi", "大分市政所": "mandokoro",
}


def area_of(s):
    a = (s.get("address_1") or "").strip()
    # 末尾の丁目・番地だけを落として町名に正規化する。
    # 算用/全角数字以降、または「<漢数字>丁目」以降を除去。
    # 町名に含まれる漢数字（三佐・三芳・二又町 等）を誤って削らないよう、漢数字は「丁目」が続く時だけ削る。
    return re.sub(r"(?:[0-9０-９]|[一二三四五六七八九十]+丁目).*$", "", a).strip() or a


def addr(s):
    return ((s.get("address_1") or "") + (s.get("address_2") or "")).strip()


def is_precise(s):
    return s.get("geo") in ("full", "number") and s.get("lat") is not None


def cnt(pred):
    return sum(1 for s in stores if pred(s))


STATS = {
    "total": TOTAL,
    "digital": cnt(lambda s: s.get("digital_coupon")),
    "paper": cnt(lambda s: s.get("paper_coupon")),
    "small": cnt(lambda s: s.get("is_small_store")),
    "large": cnt(lambda s: not s.get("is_small_store")),
}
CAT_COUNT = {c: cnt(lambda s, c=c: s.get("store_category_major_name") == c) for c in CAT_ORDER}

from collections import Counter
genre_counter = Counter(s.get("store_category_minor_name", "") for s in stores)
area_counter = Counter(area_of(s) for s in stores)
# 生成対象（slug定義があり、件数が一定以上）
GENRES = [(g, GENRE_SLUG[g], genre_counter[g]) for g in GENRE_SLUG if genre_counter[g] >= 20]
GENRES.sort(key=lambda x: -x[2])
AREAS = [(a, AREA_SLUG[a], area_counter[a]) for a in AREA_SLUG if area_counter[a] >= 20]
AREAS.sort(key=lambda x: -x[2])

# 各ジャンル(minor)の親カテゴリ(major)。関連リンク（同カテゴリの他業種）に使う。
genre_parent = {}
for _g, _s, _c in GENRES:
    _maj = Counter(s.get("store_category_major_name") for s in stores
                   if s.get("store_category_minor_name") == _g)
    genre_parent[_g] = _maj.most_common(1)[0][0] if _maj else None

# エリア×業種の掛け合わせ（超ロングテール）。薄ページ乱造を避け一定数以上のみ生成。
COMBO_MIN = 6
_area_minor = Counter((area_of(s), s.get("store_category_minor_name")) for s in stores)
COMBOS = []  # (area_name, area_slug, genre_name, genre_slug, count)
for _aname, _aslug, _ in AREAS:
    for _gname, _gslug, _ in GENRES:
        _c = _area_minor.get((_aname, _gname), 0)
        if _c >= COMBO_MIN:
            COMBOS.append((_aname, _aslug, _gname, _gslug, _c))
COMBOS.sort(key=lambda x: -x[4])


def fmt(n):
    return f"{n:,}"


# ---------------------------------------------------------------- shared CSS (inlined for fast LCP / no extra request)
PAGE_CSS = """
:root{--bg:#f6f5f3;--card:#fff;--text:#141413;--text2:#3a3936;--text3:#6b6862;--sep:#e4e1db;--line2:#d0ccc4;--accent:#2f6f9f;--red:#e85a5a;--green:#2f7a4e;--ink:#141413}
@media(prefers-color-scheme:dark){:root{--bg:#141413;--card:#1c1b1a;--text:#f2efe8;--text2:#c9c4b8;--text3:#8f8a80;--sep:#2c2a28;--line2:#3a3734;--accent:#7aa3cc}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:"Noto Sans JP",-apple-system,BlinkMacSystemFont,"Hiragino Sans","Yu Gothic",system-ui,sans-serif;line-height:1.6;font-size:15px;-webkit-text-size-adjust:100%;line-break:strict;word-break:normal;overflow-wrap:break-word}
.wrap{max-width:880px;margin:0 auto;padding:16px 16px 64px}
a{color:var(--accent);text-decoration:none;font-weight:600}a:hover{text-decoration:underline;text-underline-offset:2px}
.bc{font-size:12.5px;color:var(--text3);margin:6px 0 14px;display:flex;flex-wrap:wrap;gap:4px;font-weight:600}
.bc a{color:var(--text3)}.bc span[aria-current]{color:var(--text2)}
h1{font-size:22px;font-weight:800;letter-spacing:-.02em;line-height:1.35;margin:.2em 0 .3em}
h2{font-size:16px;font-weight:800;margin:1.6em 0 .5em;letter-spacing:-.01em}
.lead{font-size:14px;color:var(--text2);margin:.4em 0 1em;line-height:1.75}
.upd{display:inline-block;font-size:12px;font-weight:600;color:var(--text3);border:1px solid var(--line2);border-radius:999px;padding:2px 10px;margin-bottom:10px;background:#f3f1ed}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 4px}
.stat{background:var(--card);border:1px solid var(--sep);border-radius:10px;padding:8px 12px;font-size:13px}
.stat b{font-size:16px;font-weight:800;display:block}
.links{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 4px}
.pill{display:inline-block;background:#f3f1ed;border:1px solid var(--line2);border-radius:999px;padding:5px 12px;font-size:12.5px;font-weight:700;color:var(--text2)}
.pill:hover{background:#ebe8e2;border-color:#bdb8ae;color:var(--text);text-decoration:none}
ul.stores{list-style:none;padding:0;margin:10px 0}
ul.stores li{background:var(--card);border:1px solid var(--sep);border-radius:10px;padding:11px 14px;margin-bottom:8px}
ul.stores .n{font-size:14.5px;font-weight:700;letter-spacing:-.01em;color:var(--text)}
ul.stores .g{font-size:12.5px;color:var(--accent);margin-left:0;font-weight:700}
ul.stores .a{display:block;font-size:12.5px;color:var(--text3);margin-top:2px}
.badges{margin-top:5px;display:flex;flex-wrap:wrap;gap:5px}
.bdg{font-size:11px;font-weight:700;border-radius:5px;padding:1px 7px;border:1px solid var(--line2);color:var(--text2);background:#f3f1ed}
.bdg.d{background:#e8f0fa;border-color:#7aa3cc;color:#1a4d7a}
.bdg.p{background:#e8f6ee;border-color:#7cbc94;color:#1f6b40}
@media(prefers-color-scheme:dark){.bdg.p{color:#7cbc94}.upd{background:var(--card)}.pill{background:var(--card)}}
.pager{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0;align-items:center}
.pager a,.pager span{border:1px solid var(--line2);border-radius:8px;padding:6px 12px;font-size:13px;font-weight:700;background:var(--card)}
.pager span[aria-current]{background:var(--ink);color:#fff;border-color:var(--ink)}
details{background:var(--card);border:1px solid var(--sep);border-radius:10px;padding:0 14px;margin-bottom:8px}
details summary{font-weight:700;cursor:pointer;padding:12px 0;font-size:14px}
details p{margin:0 0 12px;color:var(--text2);font-size:13.5px}
.foot{margin-top:34px;padding-top:16px;border-top:1px solid var(--sep);font-size:12.5px;color:var(--text3);line-height:1.75}
.foot b{color:var(--red)}
.foot a{color:var(--text2)}
.back{display:inline-block;margin:18px 0 0;font-weight:700}
table.sum{border-collapse:collapse;margin:10px 0 6px;font-size:13.5px;width:100%;max-width:520px}
table.sum th,table.sum td{border:1px solid var(--sep);padding:6px 12px;text-align:left}
table.sum th{background:#f3f1ed;color:var(--text2);font-weight:700;white-space:nowrap;width:48%}
.note{font-size:12.5px;color:var(--text3);margin:4px 0 0}
ol.howto{padding-left:22px;margin:8px 0}
ol.howto li{margin:7px 0;font-size:14px}
.ans{background:var(--card);border:1px solid var(--sep);border-radius:8px;padding:12px 14px;margin:0 0 14px;font-size:13.5px;font-weight:600;color:var(--text2);line-height:1.7}
.ans b,.ans strong{color:var(--text);font-weight:800}
"""

FOOTER = (
    '<footer class="foot">'
    f'<p>本サイトは<b>非公式</b>です。株式会社plan8が制作した、<b>{KW_SHORT}</b>（{KW_KI}／{KW_NOKI}）2026の使える店・加盟店を探す検索ツールです。'
    f'最新・正確な情報（利用期間・購入方法・利用条件など）は必ず公式サイト <a href="{OFFICIAL}/" rel="noopener">{KW_KI}2026（公式）</a> でご確認ください。</p>'
    f'<p>加盟店データ出典：公式 <a href="{OFFICIAL_JSON}" rel="noopener nofollow">store_list.json</a>（最終更新 {BUILD_DATE}）／'
    '位置情報：国土地理院・OpenStreetMap・CARTO／'
    f'制作：<a href="{MAKER}" rel="noopener">株式会社plan8</a>（非公式）</p>'
    "</footer>"
)


def breadcrumb_json(items):
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n,
             **({"item": BASE + u} if u else {})}
            for i, (n, u) in enumerate(items)
        ],
    }


def itemlist_json(items, name):
    return {
        "@type": "ItemList", "name": name, "numberOfItems": len(items),
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": s["store_name"],
             "url": f"{BASE}/s/{s['store_id']}/"}
            for i, s in enumerate(items)
        ],
    }


def jsonld(*objs):
    graph = [o for o in objs if o]
    doc = {"@context": "https://schema.org", "@graph": graph}
    return '<script type="application/ld+json">' + json.dumps(doc, ensure_ascii=False) + "</script>"


def webpage_json(url, name, breadcrumb=None, speakable=False, collection=False, about=None):
    """ページ単位の鮮度シグナル(dateModified)とブレッドクラムを持つ WebPage / CollectionPage。"""
    o = {
        "@type": "CollectionPage" if collection else "WebPage",
        "url": url, "name": name, "inLanguage": "ja",
        "isPartOf": {"@type": "WebSite", "url": BASE + "/"},
        "datePublished": FIRST_PUB, "dateModified": BUILD_DATE,
    }
    if about:
        o["about"] = about
    if breadcrumb:
        o["breadcrumb"] = breadcrumb
    if speakable:
        o["speakable"] = {"@type": "SpeakableSpecification",
                          "cssSelector": ["h1", ".lead", "details summary"]}
    return o


def store_li(s):
    badges = []
    if s.get("digital_coupon"):
        badges.append('<span class="bdg d">デジタル対応</span>')
    if s.get("paper_coupon"):
        badges.append('<span class="bdg p">紙対応</span>')
    badges.append('<span class="bdg">' + ("中小・小規模店" if s.get("is_small_store") else "大規模店") + "</span>")
    if s.get("business_hours"):
        badges.append('<span class="bdg">' + esc(s["business_hours"]) + "</span>")
    minor = s.get("store_category_minor_name") or s.get("store_category_major_name") or ""
    return (
        '<li class="s">'
        f'<a class="n" href="/s/{esc(s["store_id"])}/">{esc(s["store_name"])}</a> '
        f'<span class="g">{esc(minor)}</span>'
        f'<span class="a">{esc(addr(s))}</span>'
        f'<div class="badges">{"".join(badges)}</div>'
        "</li>"
    )


def page(path, title, desc, h1, lead_html, body_html, breadcrumb, itemlist=None, extra_head="",
         extra_ld=(), speakable=False, collection=False, about=None):
    """1ページを書き出す。path は ROOT 相対（例 'c/kau/index.html'）。"""
    url = BASE + "/" + os.path.dirname(path).replace("index.html", "")
    url = url.rstrip("/") + "/"
    if path == "index.html":
        url = BASE + "/"
    wp = webpage_json(url, title, breadcrumb, speakable=speakable, collection=collection, about=about)
    ld = jsonld(breadcrumb, wp, itemlist, *extra_ld)
    out = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{url}">
<meta name="robots" content="index,follow,max-image-preview:large">
<meta name="author" content="株式会社plan8">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:site_name" content="{KW_SHORT} 使える店一覧（非公式）">
<meta property="og:locale" content="ja_JP">
<meta property="og:image" content="{BASE}/ogp.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#f6f5f3">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700;900&display=swap">
{extra_head}
{ld}
<style>{PAGE_CSS}</style>
</head>
<body>
<div class="wrap">
<nav class="bc">{breadcrumb_html(breadcrumb)}</nav>
<h1>{esc(h1)}</h1>
<div class="upd">データ最終更新 {BUILD_DATE}・全{fmt(TOTAL)}店掲載</div>
{lead_html}
{body_html}
<a class="back" href="/list/">← 加盟店一覧（全{fmt(TOTAL)}店）へ</a> ・ <a href="/">地図で探す</a>
{FOOTER}
</div>
</body>
</html>
"""
    full = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    open(full, "w", encoding="utf-8").write(out)
    return url


def breadcrumb_html(bc):
    parts = []
    items = bc["itemListElement"]
    for i, it in enumerate(items):
        last = i == len(items) - 1
        name = esc(it["name"])
        if last or "item" not in it:
            parts.append(f'<span aria-current="page">{name}</span>')
        else:
            u = it["item"].replace(BASE, "")
            parts.append(f'<a href="{u or "/"}">{name}</a>')
    return ' <span>›</span> '.join(parts)


# ---------------------------------------------------------------- list rendering with pagination
def stats_table(items):
    """AIO/featured snippet 向けの機械可読な内訳サマリー表。"""
    d = sum(1 for s in items if s.get("digital_coupon"))
    p = sum(1 for s in items if s.get("paper_coupon"))
    sm = sum(1 for s in items if s.get("is_small_store"))
    return (
        '<table class="sum"><tbody>'
        f'<tr><th>掲載している使える店</th><td>{fmt(len(items))}店</td></tr>'
        f'<tr><th>デジタル対応</th><td>{fmt(d)}店</td></tr>'
        f'<tr><th>紙対応</th><td>{fmt(p)}店</td></tr>'
        f'<tr><th>中小・小規模店</th><td>{fmt(sm)}店</td></tr>'
        '</tbody></table>'
    )


def related_block(heading, pairs):
    """(label, href) のピル群で関連ページへの内部リンクを作る（KW入りアンカーで主題を補強）。"""
    links = "".join(f'<a class="pill" href="{h}">{esc(l)}</a>' for l, h in pairs if h)
    return f'<h2>{esc(heading)}</h2><div class="links">{links}</div>' if links else ""


def render_store_pages(items, slug_dir, title_base, h1_base, desc_base, crumb_parent, kind_label,
                       lead_extra="", related_html="", about=None):
    """items を PER_PAGE ごとに分割して slug_dir/[n/]index.html を生成。生成URL一覧を返す。
    title_base/h1_base/desc_base は呼び出し側で意図語（店舗/使える店/お店）と表記ゆれを含めて渡す。"""
    items = sorted(items, key=lambda s: s.get("store_id", ""))
    npages = max(1, (len(items) + PER_PAGE - 1) // PER_PAGE)
    urls = []
    tbl = stats_table(items)
    for p in range(1, npages + 1):
        chunk = items[(p - 1) * PER_PAGE: p * PER_PAGE]
        sub = "" if p == 1 else f"{p}/"
        path = f"{slug_dir}/{sub}index.html"
        suffix = "" if p == 1 else f"（{p}/{npages}）"
        title = f"{title_base}{suffix}（非公式）"
        h1 = f"{h1_base}{suffix}"
        # ページ2以降は meta description を一意にする（重複説明の回避）
        desc = desc_base if p == 1 else f"{desc_base}（{p}/{npages}ページ）"
        lead = (
            f'<p class="lead">{desc_base}{lead_extra}'
            f'このページでは{esc(kind_label)}で大分市プレミアム付き商品券（プレミアム付商品券）2026が使えるお店を一覧で確認できます'
            f'（{fmt(len(items))}店中 {(p-1)*PER_PAGE+1}〜{min(p*PER_PAGE,len(items))}店）。'
            f'店名をタップすると地図で場所を確認できます。電話番号は各店・公式サイトでご確認ください。</p>'
        )
        lst = '<ul class="stores">' + "".join(store_li(s) for s in chunk) + "</ul>"
        pager = ""
        if npages > 1:
            links = []
            for q in range(1, npages + 1):
                qu = f"{BASE}/{slug_dir}/" + ("" if q == 1 else f"{q}/")
                if q == p:
                    links.append(f'<span aria-current="page">{q}</span>')
                else:
                    links.append(f'<a href="{qu}">{q}</a>')
            pager = '<div class="pager"><span style="border:none;padding-left:0">ページ:</span>' + "".join(links) + "</div>"
        crumb = breadcrumb_json(crumb_parent + [(h1_base + suffix, None)])
        extra = ""
        if npages > 1:
            if p > 1:
                extra += f'<link rel="prev" href="{BASE}/{slug_dir}/' + ("" if p == 2 else f"{p-1}/") + '">'
            if p < npages:
                extra += f'<link rel="next" href="{BASE}/{slug_dir}/{p+1}/">'
        body = (tbl if p == 1 else "") + pager + lst + pager + (related_html if p == 1 else "")
        url = page(path, title, desc[:158], h1, lead, body, crumb,
                   itemlist=itemlist_json(chunk, h1), extra_head=extra,
                   collection=True, about=about or (KW_KI + "2026 加盟店"))
        urls.append((url, "weekly" if p == 1 else "monthly"))
    return urls


SITEMAP_URLS = []


def add_url(url, freq="weekly", prio="0.6"):
    SITEMAP_URLS.append((url, freq, prio))


# ---------------------------------------------------------------- build: category / genre / area pages
HOME_CRUMB = [("ホーム", "/"), ("加盟店一覧", "/list/")]


def build_categories():
    for c in CAT_ORDER:
        items = [s for s in stores if s.get("store_category_major_name") == c]
        if not items:
            continue
        slug = CAT_SLUG[c]
        n = fmt(len(items))
        title_base = f"大分市プレミアム商品券2026 {c}で使える店 {n}店一覧"
        h1_base = f"大分市プレミアム付き商品券2026「{c}」で使える加盟店 店舗一覧（{n}店）"
        desc = (f"{KW_BOTH}2026が使える「{c}」の加盟店 店舗{n}店の一覧（非公式）。"
                f"店名・業種・住所・デジタル/紙対応がわかります。使える店・使えるお店を地図でも探せます。制作plan8。")
        # 関連：配下の主要業種＋ほかのカテゴリ
        genre_pairs = [(o.split("・")[0].split(" [")[0] + f"（{fmt(cc)}）", f"/g/{gslug}/")
                       for o, gslug, cc in GENRES if genre_parent.get(o) == c][:6]
        cat_pairs = [(f"{cc}（{fmt(CAT_COUNT[cc])}）", f"/c/{CAT_SLUG[cc]}/")
                     for cc in CAT_ORDER if cc != c and CAT_COUNT[cc]]
        related = (related_block(f"「{c}」の使える店を業種から探す", genre_pairs)
                   + related_block("ほかのカテゴリで使える店", cat_pairs))
        urls = render_store_pages(items, f"c/{slug}", title_base, h1_base, desc,
                                  HOME_CRUMB, f"「{c}」", related_html=related)
        for u, fr in urls:
            add_url(u, fr, "0.7" if u.endswith(f"/c/{slug}/") else "0.5")


def build_genres():
    for name, slug, count in GENRES:
        items = [s for s in stores if s.get("store_category_minor_name") == name]
        short = name.split("・")[0].split(" [")[0]
        n = fmt(count)
        title_base = f"大分市プレミアム商品券2026 {short}で使える店 {n}店一覧"
        h1_base = f"大分市プレミアム付き商品券2026が使える{short}の店舗一覧（{n}店）"
        desc = (f"{KW_BOTH}2026が使える{short}（{esc(name)}）の使える店 {n}店の一覧（非公式）。"
                f"店名・住所・デジタル/紙対応がわかります。制作plan8。")
        # 関連：親カテゴリ＋同カテゴリの他業種
        parent = genre_parent.get(name)
        pairs = []
        if parent in CAT_SLUG:
            pairs.append((f"{parent}カテゴリの使える店（{fmt(CAT_COUNT[parent])}）", f"/c/{CAT_SLUG[parent]}/"))
        sib = [(o.split("・")[0].split(" [")[0] + f"（{fmt(cc)}）", f"/g/{gslug}/")
               for o, gslug, cc in GENRES if gslug != slug and genre_parent.get(o) == parent][:6]
        related = related_block("関連する使える店（業種）", pairs + sib)
        urls = render_store_pages(items, f"g/{slug}", title_base, h1_base, desc,
                                  HOME_CRUMB, short, related_html=related)
        for u, fr in urls:
            add_url(u, fr, "0.6" if u.endswith(f"/g/{slug}/") else "0.5")


def build_areas():
    for name, slug, count in AREAS:
        items = [s for s in stores if area_of(s) == name]
        short = name.replace("大分市", "")
        n = fmt(count)
        title_base = f"大分市プレミアム商品券2026 {short}で使えるお店 {n}店一覧"
        h1_base = f"{short}で大分市プレミアム付き商品券2026が使えるお店 加盟店一覧（{n}店）"
        desc = (f"{short}周辺で{KW_BOTH}2026が使えるお店 {n}店の一覧（非公式）。"
                f"店名・業種・デジタル/紙対応がわかります。近くの使える店を地図で探せます。制作plan8。")
        # 関連：ほかのエリア
        area_pairs = [(a.replace("大分市", "") + f"（{fmt(cc)}）", f"/area/{aslug}/")
                      for a, aslug, cc in AREAS if aslug != slug][:8]
        related = related_block("ほかのエリアで使えるお店", area_pairs)
        urls = render_store_pages(items, f"area/{slug}", title_base, h1_base, desc,
                                  HOME_CRUMB, short, related_html=related)
        for u, fr in urls:
            add_url(u, fr, "0.5")


# ---------------------------------------------------------------- build: list hub
def build_list_hub():
    cat_links = "".join(
        f'<a class="pill" href="/c/{CAT_SLUG[c]}/">{c} {fmt(CAT_COUNT[c])}</a>'
        for c in CAT_ORDER if CAT_COUNT[c]
    )
    genre_links = "".join(
        f'<a class="pill" href="/g/{slug}/">{esc(name.split("・")[0].split(" [")[0])} {fmt(count)}</a>'
        for name, slug, count in GENRES
    )
    area_links = "".join(
        f'<a class="pill" href="/area/{slug}/">{esc(name.replace("大分市",""))} {fmt(count)}</a>'
        for name, slug, count in AREAS
    )
    small_n, large_n = STATS["small"], STATS["large"]
    lead = (
        f'<p class="lead"><strong>{KW_SHORT} 使える店一覧</strong>として、加盟店全<b>{fmt(TOTAL)}店</b>を掲載しています'
        f'（最終更新 {BUILD_DATE}・非公式）。'
        f'買う{fmt(CAT_COUNT["買う"])}・食べる{fmt(CAT_COUNT["食べる"])}・暮らす{fmt(CAT_COUNT["暮らす"])}・'
        f'遊ぶ{fmt(CAT_COUNT["遊ぶ"])}・泊まる{fmt(CAT_COUNT["泊まる"])}。'
        f'中小・小規模店舗 <b>{fmt(small_n)}店</b>／大規模 {fmt(large_n)}店。'
        f'デジタル対応{fmt(STATS["digital"])}店／紙対応{fmt(STATS["paper"])}店。'
        f'地図で探す場合は <a href="/">使える店マップ</a> へ。'
        f'（「{KW_SHORT}」「{KW_NOKI}」「{KW_KI}」は同一事業）</p>'
    )
    body = (
        stats_table(stores)
        + f'<h2 id="small">{KW_SHORT} 中小店舗一覧（中小・小規模 {fmt(small_n)}店）</h2>'
        + f'<p>中小・小規模店専用券の対象になる区分の使える店は<strong>{fmt(small_n)}店</strong>です。'
        f'地図の店舗区分「中小・小規模店舗」で中小店舗検索ができます。'
        f'大規模店舗は{fmt(large_n)}店（全店舗共通券で使いやすい区分）です。</p>'
        + f'<p class="links"><a class="pill" href="/?size=small"><b>地図で中小店舗を検索 →</b></a> '
        f'<a class="pill" href="/">使える店マップ</a></p>'
        + f'<p class="links" style="margin:10px 0 2px"><a class="pill" href="/guide/"><b>{KW_SHORT}とは・使える店の探し方 →</b></a></p>'
        + f'<h2>{KW_SHORT} 使える店一覧（カテゴリ）</h2>'
        f'<div class="links">{cat_links}</div>'
        f'<h2>{KW_SHORT} 使える店を業種から</h2>'
        f'<div class="links">{genre_links}</div>'
        f'<h2>{KW_SHORT} 使える店をエリアから</h2>'
        f'<div class="links">{area_links}</div>'
        f'<h2>よくある質問（使える店一覧・中小店舗）</h2>'
        + faq_html()
        + '<p style="margin-top:18px"><a class="pill" href="/llms-full.txt">全店データ（テキスト版）</a> '
          '<a class="pill" href="/">地図で探す</a></p>'
    )
    dataset = dataset_json()
    crumb = breadcrumb_json([("ホーム", "/"), ("使える店一覧", None)])
    title = f"{KW_SHORT} 使える店一覧 全{fmt(TOTAL)}店 地図でも探せる加盟店・中小店舗（非公式）"
    desc = (f"{KW_SHORT} 使える店一覧（全{fmt(TOTAL)}店）。地図でさくっと検索も可。"
            f"中小店舗{fmt(small_n)}店、買う{fmt(CAT_COUNT['買う'])}・食べる{fmt(CAT_COUNT['食べる'])}。"
            f"カテゴリ・業種・エリア別。非公式・制作plan8。")
    ld = jsonld(
        crumb,
        webpage_json(BASE + "/list/", title, crumb, speakable=True, collection=True,
                     about=f"{KW_SHORT} 使える店一覧"),
        dataset, faqpage_json(), howto_json(),
    )
    full = os.path.join(ROOT, "list", "index.html")
    os.makedirs(os.path.dirname(full), exist_ok=True)
    html_out = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{BASE}/list/">
<meta name="robots" content="index,follow,max-image-preview:large">
<meta name="author" content="株式会社plan8">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{BASE}/list/">
<meta property="og:site_name" content="{KW_SHORT} 使える店一覧（非公式）">
<meta property="og:locale" content="ja_JP">
<meta property="og:image" content="{BASE}/ogp.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700;900&display=swap">
{ld}
<style>{PAGE_CSS}</style>
</head>
<body>
<div class="wrap">
<nav class="bc">{breadcrumb_html(crumb)}</nav>
<div class="ans" id="answer"><strong>{KW_SHORT} 使える店一覧</strong>：全<b>{fmt(TOTAL)}店</b>（中小・小規模 {fmt(small_n)}店）。最終更新 {BUILD_DATE}。カテゴリ・エリア・業種から一覧でき、地図でもさくっと検索できます（非公式）。</div>
<h1>{KW_SHORT} 使える店一覧（加盟店 全{fmt(TOTAL)}店・地図対応）</h1>
<div class="upd">データ最終更新 {BUILD_DATE}・非公式</div>
{lead}
{body}
{FOOTER}
</div>
</body>
</html>
"""
    open(full, "w", encoding="utf-8").write(html_out)
    add_url(BASE + "/list/", "weekly", "0.9")


# ---------------------------------------------------------------- build: guide (制度まとめハブ)
def build_guide():
    facts_rows = "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in PROGRAM_FACTS)
    facts_table = f'<table class="sum"><tbody>{facts_rows}</tbody></table>'
    steps = "".join(f"<li><b>{esc(n)}</b>：{esc(t)}</li>" for n, t in HOWTO_STEPS)
    hub_pairs = [(f"加盟店一覧（全{fmt(TOTAL)}店）", "/list/")] + [
        (f"{c}で使える店（{fmt(CAT_COUNT[c])}）", f"/c/{CAT_SLUG[c]}/") for c in CAT_ORDER if CAT_COUNT[c]
    ]
    lead = (
        f'<div class="ans" id="answer"><strong>{KW_SHORT}</strong>は大分市内の加盟店で使えるプレミアム付き商品券です。'
        f'プレミアム率30%・利用期間2026/6/1〜8/31・1人4冊まで（{FACTS_ASOF}の公式概要）。'
        f'使える店は本サイトで全{fmt(TOTAL)}店を地図・一覧から探せます（非公式）。</div>'
        f'<p class="lead"><strong>{KW_SHORT}</strong>（{KW_BOTH}）2026について、制度の概要と「使える店」の探し方をまとめた'
        f'<b>非公式</b>ガイドです（株式会社plan8制作）。最新・正確な内容は公式 '
        f'<a href="{OFFICIAL}/" rel="noopener">2026.oita-pay.jp</a> と'
        f'<a href="{CITY_OFFICIAL}" rel="noopener">大分市の案内</a>でご確認ください。</p>'
    )
    body = (
        f"<h2>{KW_SHORT}が使えるお店はどこ？</h2>"
        f'<p>{KW_SHORT}（{KW_NOKI}／{KW_KI}）2026が使えるお店は、本サイトの'
        f'<a href="/">使える店マップ</a>と<a href="/list/">加盟店一覧（全{fmt(TOTAL)}店）</a>から、'
        f"業種・エリア・現在地で探せます。大型店から中小・小規模店まで、"
        f"コンビニ・スーパー・ドラッグストア・ガソリンスタンドなどの買い物、"
        f"居酒屋・カフェ・焼肉などの飲食、暮らしのサービスまで幅広い業種が対象です。</p>"
        f"<h2>{KW_SHORT}とは（制度の概要）</h2>"
        f"<p>{KW_SHORT}2026は、大分市内のお店で使えるプレミアム付きの商品券です。"
        f"おもな内容は次のとおりです（{FACTS_ASOF}の公式概要より）。</p>"
        + facts_table
        + f'<p class="note">上記は{FACTS_ASOF}の公式概要にもとづく参考情報です。申込・抽選・2次募集など最新の日程や条件は'
          f'公式サイト（<a href="{OFFICIAL}/" rel="noopener">2026.oita-pay.jp</a>）と'
          f'<a href="{CITY_OFFICIAL}" rel="noopener">大分市の案内</a>でご確認ください。</p>'
        f"<h2>「{KW_SHORT}」「{KW_NOKI}」「{KW_KI}」の表記</h2>"
        f"<p>大分市（行政）の案内では「{KW_NOKI}」、事業主体の大分商工会議所と公式特設サイトでは"
        f"「{KW_KI}」と表記され、「付」と「付き」の両表記が公式に併存しています。"
        f"一般検索では「{KW_SHORT}」と省略されることが多く、いずれも同じ事業を指します。</p>"
        f"<h2>{KW_SHORT}の使える店の探し方</h2>"
        f'<ol class="howto">{steps}</ol>'
        + related_block(f"{KW_SHORT}の使える店をカテゴリから探す", hub_pairs)
        + f"<h2>よくある質問（{KW_SHORT}）</h2>" + faq_html()
    )
    crumb = breadcrumb_json([("ホーム", "/"), ("ガイド", None)])
    title = f"{KW_SHORT}2026とは 使える店の探し方・制度まとめ（非公式）"
    h1 = f"{KW_SHORT}（{KW_KI}／{KW_NOKI}）2026とは 使える店の探し方"
    desc = (f"{KW_SHORT}2026とは。プレミアム率30%・利用期間2026年6月1日〜8月31日・1人4冊まで・抽選方式などの概要と、"
            f"使える店・加盟店の探し方をまとめた非公式ガイド。最新は公式で確認。制作plan8。")
    url = page("guide/index.html", title, desc[:158], h1, lead, body, crumb,
               extra_ld=[howto_json(), faqpage_json()], speakable=True, about=KW_SHORT + "2026")
    add_url(url, "weekly", "0.8")


# ---------------------------------------------------------------- build: individual store pages (/s/<id>/)
def store_json(s):
    o = {
        "@type": ["LocalBusiness", "Store"],
        "name": s["store_name"],
        "url": f"{BASE}/s/{s['store_id']}/",
        "address": {"@type": "PostalAddress", "addressRegion": "大分県",
                    "addressLocality": "大分市", "streetAddress": addr(s)},
        "areaServed": {"@type": "City", "name": "大分市"},
        "makesOffer": {"@type": "Offer", "name": "大分市プレミアム付き商品券2026 利用可",
                       "description": "この店舗で大分市プレミアム付き商品券（プレミアム付商品券）2026が利用できます。"},
    }
    if s.get("store_name_kana"):
        o["alternateName"] = s["store_name_kana"]
    if is_precise(s):
        o["geo"] = {"@type": "GeoCoordinates", "latitude": s["lat"], "longitude": s["lng"]}
    return o


def build_stores():
    n = 0
    for s in stores:
        sid = s["store_id"]
        name = s["store_name"]
        minor = s.get("store_category_minor_name") or s.get("store_category_major_name") or ""
        major = s.get("store_category_major_name") or ""
        area = area_of(s)
        a = addr(s)
        digital, paper = s.get("digital_coupon"), s.get("paper_coupon")
        pay = "・".join([t for t, ok in (("デジタル", digital), ("紙", paper)) if ok]) or "—"
        size = "中小・小規模店" if s.get("is_small_store") else "大規模店"
        dmark, pmark = ("○" if digital else "×"), ("○" if paper else "×")
        ans = (f"はい。{name}（{area}・{minor}）は、{KW_BOTH}2026の加盟店です"
               f"（{pay}に対応）。最新・正確な情報は公式サイトでご確認ください。")
        rows = [("店名", name)]
        if s.get("store_name_kana"):
            rows.append(("よみ", s["store_name_kana"]))
        rows += [("業種", minor), ("住所", a)]
        if s.get("business_hours"):
            rows.append(("営業時間", s["business_hours"]))
        if s.get("closed_day"):
            rows.append(("定休日", s["closed_day"]))
        rows += [("商品券の対応", f"デジタル{dmark}／紙{pmark}"), ("店舗区分", size)]
        detail = ('<table class="sum"><tbody>'
                  + "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in rows)
                  + "</tbody></table>")
        cat_slug = CAT_SLUG.get(major)
        gslug = GENRE_SLUG.get(s.get("store_category_minor_name"))
        aslug = AREA_SLUG.get(area)
        short_g = minor.split("・")[0].split(" [")[0]
        pairs = []
        if cat_slug:
            pairs.append((f"{major}で使える店", f"/c/{cat_slug}/"))
        if gslug:
            pairs.append((f"{short_g}で使える店", f"/g/{gslug}/"))
        if aslug:
            pairs.append((f"{area.replace('大分市','')}で使えるお店", f"/area/{aslug}/"))
        pairs.append((f"加盟店一覧（全{fmt(TOTAL)}店）", "/list/"))
        related = related_block("関連ページ", pairs)
        sib = [o for o in stores
               if o.get("store_category_minor_name") == s.get("store_category_minor_name")
               and o["store_id"] != sid][:6]
        sib_html = ('<h2>同じ業種で使えるお店</h2><ul class="stores">'
                    + "".join(store_li(o) for o in sib) + "</ul>") if sib else ""
        lead = (f'<p class="lead">{esc(name)}（{esc(area)}・{esc(minor)}）で'
                f'大分市プレミアム付き商品券（プレミアム付商品券）2026が使えるかをまとめた<b>非公式</b>のページです。</p>')
        body = (
            f"<h2>{esc(name)}で大分市プレミアム付き商品券2026は使える？</h2>"
            f"<p>{esc(ans)}</p>"
            + detail
            + f'<p class="links"><a class="pill" href="/#store={esc(sid)}">地図でこの店を見る</a> '
              f'<a class="pill" href="/list/">加盟店一覧へ</a></p>'
            + related + sib_html
        )
        crumb_items = [("ホーム", "/"), ("加盟店一覧", "/list/")]
        if cat_slug:
            crumb_items.append((f"{major}で使える店", f"/c/{cat_slug}/"))
        crumb_items.append((name, None))
        crumb = breadcrumb_json(crumb_items)
        title = f"{name}で大分市プレミアム付き商品券2026は使える？ {minor}（非公式）"
        h1 = f"{name}で大分市プレミアム付き商品券2026は使える？"
        desc = (f"{name}（{area}・{minor}）は{KW_BOTH}2026の加盟店。デジタル{dmark}／紙{pmark}。住所{a}。"
                f"非公式まとめ。最新は公式サイトで確認。制作plan8。")
        store_faq = {"@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": f"{name}で大分市プレミアム付き商品券2026は使えますか？",
             "acceptedAnswer": {"@type": "Answer", "text": ans}}]}
        url = page(f"s/{sid}/index.html", title, desc[:158], h1, lead, body, crumb,
                   extra_ld=[store_json(s), store_faq], about=KW_KI + "2026")
        add_url(url, "monthly", "0.4")
        n += 1
    return n


# ---------------------------------------------------------------- build: area × genre combos
def build_combos():
    for aname, aslug, gname, gslug, count in COMBOS:
        items = [s for s in stores if area_of(s) == aname and s.get("store_category_minor_name") == gname]
        short_a = aname.replace("大分市", "")
        short_g = gname.split("・")[0].split(" [")[0]
        n = fmt(count)
        slug_dir = f"area/{aslug}/g/{gslug}"
        title_base = f"大分市プレミアム商品券2026 {short_a}の{short_g}で使える店 {n}店一覧"
        h1_base = f"{short_a}で大分市プレミアム付き商品券2026が使える{short_g}一覧（{n}店）"
        desc = (f"{short_a}周辺で{KW_BOTH}2026が使える{short_g}の使える店 {n}店の一覧（非公式）。"
                f"店名・住所・デジタル/紙対応がわかります。制作plan8。")
        crumb_parent = [("ホーム", "/"), ("加盟店一覧", "/list/"), (f"{short_a}で使えるお店", f"/area/{aslug}/")]
        related = related_block("関連", [(f"{short_g}で使える店", f"/g/{gslug}/"),
                                        (f"{short_a}で使えるお店", f"/area/{aslug}/")])
        urls = render_store_pages(items, slug_dir, title_base, h1_base, desc,
                                  crumb_parent, f"{short_a}の{short_g}", related_html=related)
        for u, fr in urls:
            add_url(u, fr, "0.4")


# ---------------------------------------------------------------- FAQ + structured data shared
def faqs():
    s = STATS
    return [
        # AIO・GSC共通: 「地図で店舗一覧をさくっと」＋「使える店一覧」を先頭で直答
        (f"{KW_SHORT} 使える店一覧はどこで見られる？",
         f"{KW_SHORT}2026の使える店一覧は、本サイト（非公式）で地図とリストからすぐ探せます。掲載は全{fmt(TOTAL)}店（最終更新 {BUILD_DATE}）。"
         f"買う{fmt(CAT_COUNT['買う'])}・食べる{fmt(CAT_COUNT['食べる'])}・暮らす{fmt(CAT_COUNT['暮らす'])}・遊ぶ{fmt(CAT_COUNT['遊ぶ'])}・泊まる{fmt(CAT_COUNT['泊まる'])}。"
         f"公式の店舗一覧は2026.oita-pay.jp、本サイトは地図でさくっと使える店を見つける用途向けです。"),
        (f"{KW_SHORT}が使える店を地図で探すには？",
         f"本サイトの加盟店マップを開くと、使える店が地図上に表示されます。"
         f"現在地を許可すると近い順、リスト表示に切り替えれば店舗一覧をスクロールできます。"
         f"カテゴリ・エリア・業種・中小店舗でもしぼれます（非公式・全{fmt(TOTAL)}店）。"),
        (f"{KW_SHORT}の加盟店一覧は？",
         f"加盟店一覧（使える店一覧）は /list/ に全{fmt(TOTAL)}店。"
         f"トップの地図ではピン表示＋リスト表示で同じデータをさくっと検索できます。"
         f"デジタル対応{fmt(s['digital'])}店・紙対応{fmt(s['paper'])}店。"),
        (f"公式の一覧とこのサイトの違いは？",
         f"公式（2026.oita-pay.jp）は加盟店の正式な一覧です。"
         f"本サイトは非公式で、同じ加盟店データを地図・現在地から近い順・中小店舗絞り込み・業種/エリアで、"
         f"使える店をさくっと探すことに特化しています。制度や購入条件は必ず公式で確認してください。"),
        (f"{KW_SHORT}の中小店舗一覧は？",
         f"中小・小規模店舗の使える店は{fmt(s['small'])}店です（全{fmt(TOTAL)}店中）。"
         f"中小・小規模店専用券7,000円分はこれらの店向け。"
         f"地図の店舗区分「中小・小規模店舗」、または /?size=small で中小店舗検索ができます。"),
        (f"{KW_SHORT} 中小店舗検索のやり方は？",
         f"地図の「さがす・絞り込み」→店舗区分「中小・小規模店舗」で{fmt(s['small'])}店に絞れます。"
         f"カテゴリやエリアと組み合わせた中小店舗検索も可能です。"),
        (f"近くで{KW_SHORT}が使えるお店を探すには？",
         f"地図で現在地を許可すると、近い順に使えるお店を表示します。"
         f"リスト表示に切り替えれば店舗一覧としてスクロール確認もできます。全{fmt(TOTAL)}店。"),
        (f"「{KW_SHORT}」「{KW_NOKI}」「{KW_KI}」は同じ？",
         f"同じ事業です。検索では「{KW_SHORT}」、行政は「{KW_NOKI}」、特設サイトは「{KW_KI}」。"
         f"使える店・条件は同一です。"),
        (f"{KW_SHORT}のプレミアム率・利用期間は？",
         f"プレミアム率30%（1万円→1万3,000円分）、利用期間2026年6月1日〜8月31日、1人4冊まで（{FACTS_ASOF}の公式概要）。"
         f"1冊＝全店舗共通6,000円分＋中小・小規模店専用7,000円分。最新は公式で確認を。"),
        (f"{KW_SHORT}で使える飲食店・コンビニは？",
         f"食べる{fmt(CAT_COUNT['食べる'])}店、コンビニ{fmt(genre_counter.get('コンビニ',0))}・"
         f"スーパー{fmt(genre_counter.get('スーパー',0))}・ドラッグストア{fmt(genre_counter.get('ドラッグストア',0))}を地図と一覧で掲載。"),
        ("このサイトは公式ですか？",
         f"いいえ。plan8制作の非公式ツールです。"
         f"強みは、使える店一覧を地図でさくっと探し、現在地・中小店舗・業種で絞り込める点です。"
         f"制度・購入は必ず公式（2026.oita-pay.jp）で確認してください。"),
        ("データはいつ時点？",
         f"公式 store_list.json をもとに最終更新{BUILD_DATE}・全{fmt(TOTAL)}店。最新は公式で確認を。"),
    ]


def faq_html():
    return "".join(f"<details><summary>{esc(q)}</summary><p>{esc(a)}</p></details>" for q, a in faqs())


def faqpage_json():
    return {
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in faqs()
        ],
    }


# 「地図で店舗一覧をさくっと探す」手順（AIOが引用しやすい操作系 HowTo）
HOWTO_STEPS = [
    ("地図を開く", f"本サイト（{BASE}/）を開くと、{KW_SHORT}の使える店が地図上に表示されます。"),
    ("さがす・絞り込みを使う", "店名・カテゴリ・エリア・業種・中小/大規模・デジタル対応で店舗一覧をしぼれます。"),
    ("現在地で近い順にする", "現在地を許可すると、近くの使える店から順に並び替えられます。"),
    ("リスト表示に切り替える", "地図とリストを切り替え、店舗一覧をスクロールして確認できます。"),
    ("店をタップして詳細を見る", "店名・住所・業種・デジタル/紙対応・店舗区分を確認し、必要ならルート案内へ進めます。"),
]


def howto_json():
    return {
        "@type": "HowTo",
        "name": f"{KW_SHORT}の使える店を地図でさくっと探す",
        "description": (
            f"{KW_SHORT}の使える店一覧・加盟店を、地図とリストですぐ探す手順（非公式マップ）。"
            f"全{fmt(TOTAL)}店・中小店舗絞り込み・現在地から近い順に対応。"
        ),
        "totalTime": "PT1M",
        "tool": {"@type": "HowToTool", "name": f"{KW_SHORT} 使える店マップ（非公式）"},
        "step": [
            {
                "@type": "HowToStep",
                "position": i + 1,
                "name": n,
                "text": t,
                "url": BASE + "/",
            }
            for i, (n, t) in enumerate(HOWTO_STEPS)
        ],
    }


def webapp_json():
    """AIO向け: 『地図で店舗一覧をすぐ探せるツール』としての自己説明。"""
    return {
        "@type": "WebApplication",
        "name": f"{KW_SHORT} 使える店マップ（非公式）",
        "alternateName": [
            f"{KW_SHORT} 使える店一覧",
            f"{KW_SHORT} 加盟店マップ",
            "商品券マップ2026",
        ],
        "url": BASE + "/",
        "applicationCategory": "TravelApplication",
        "operatingSystem": "Any",
        "browserRequirements": "Requires JavaScript. Map view works best on modern browsers.",
        "inLanguage": "ja",
        "isAccessibleForFree": True,
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "JPY"},
        "creator": {"@type": "Organization", "name": "株式会社plan8", "url": MAKER},
        "dateModified": BUILD_DATE,
        "description": (
            f"{KW_SHORT}（{KW_KI}／{KW_NOKI}）2026が使える加盟店を、"
            f"地図と店舗一覧ですぐ探せる非公式の検索ツール。"
            f"全{fmt(TOTAL)}店を掲載し、現在地から近い順・カテゴリ・エリア・業種・"
            f"中小店舗（{fmt(STATS['small'])}店）での絞り込みに対応。"
            f"公式の一覧表示に加え、地図でさくっと使える店を見つける用途向け。"
        ),
        "featureList": [
            "使える店を地図で表示",
            "店舗一覧（リスト）表示",
            "現在地から近い順",
            "カテゴリ・エリア・業種で絞り込み",
            "中小・小規模店舗の絞り込み検索",
            "デジタル/紙対応の確認",
            "店名キーワード検索",
        ],
        "about": {
            "@type": "Thing",
            "name": f"{KW_SHORT}2026 使える店・加盟店",
        },
    }


def category_itemlist_json():
    """トップ直下のカテゴリ件数を ItemList でAIOに渡す。"""
    items = []
    pos = 1
    for c in CAT_ORDER:
        n = CAT_COUNT.get(c) or 0
        if not n:
            continue
        items.append({
            "@type": "ListItem",
            "position": pos,
            "name": f"{KW_SHORT} {c}で使える店 {fmt(n)}店",
            "url": f"{BASE}/c/{CAT_SLUG[c]}/",
            "description": f"{c}カテゴリの使える店（加盟店）{fmt(n)}店の一覧",
        })
        pos += 1
    items.append({
        "@type": "ListItem",
        "position": pos,
        "name": f"{KW_SHORT} 中小店舗 {fmt(STATS['small'])}店",
        "url": f"{BASE}/?size=small",
        "description": f"中小・小規模店舗の使える店 {fmt(STATS['small'])}店を地図で検索",
    })
    return {
        "@type": "ItemList",
        "name": f"{KW_SHORT} 使える店一覧の入口",
        "itemListOrder": "https://schema.org/ItemListOrderAscending",
        "numberOfItems": len(items),
        "itemListElement": items,
    }


def dataset_json():
    return {
        "@type": "Dataset",
        "name": f"{KW_SHORT}2026 加盟店データ（非公式まとめ）",
        "description": (
            f"{KW_SHORT}（{KW_KI}／{KW_NOKI}）2026が使える加盟店{fmt(TOTAL)}店の名称・業種・住所・"
            f"カテゴリ・デジタル/紙対応・位置情報のまとめ。株式会社plan8が公式店舗一覧をもとに作成した非公式データセット。"
        ),
        "url": BASE + "/list/",
        "creator": {"@type": "Organization", "name": "株式会社plan8", "url": MAKER},
        "isBasedOn": OFFICIAL_JSON,
        "dateModified": BUILD_DATE,
        "spatialCoverage": {"@type": "Place", "name": "大分県大分市"},
        "alternateName": ALIASES,
        "keywords": [
            KW_SHORT, KW_SHORT + "2026", KW_KI, KW_NOKI, "プレミアム商品券", "プレミアム付商品券",
            "加盟店", "店舗一覧", "使える店", "使える店一覧", "使えるお店", "地図", "加盟店マップ",
            "中小店舗", "大分市 商品券", "大分市",
            f"{KW_SHORT} 使える店", f"{KW_SHORT} 使える店一覧", f"{KW_SHORT} 加盟店", f"{KW_SHORT} 地図",
        ],
        "variableMeasured": [
            {"@type": "PropertyValue", "name": "加盟店総数", "value": TOTAL},
            {"@type": "PropertyValue", "name": "中小・小規模店舗数", "value": STATS["small"]},
            {"@type": "PropertyValue", "name": "デジタル対応店数", "value": STATS["digital"]},
            {"@type": "PropertyValue", "name": "紙対応店数", "value": STATS["paper"]},
        ],
    }


def website_json():
    return {
        "@type": "WebSite",
        "name": f"{KW_SHORT} 使える店一覧を地図で探す（非公式）",
        "alternateName": ALIASES + [
            f"{KW_SHORT} 加盟店", "商品券マップ2026",
            f"{KW_SHORT} 使える店マップ", f"{KW_KI}2026 加盟店マップ",
        ],
        "url": BASE + "/",
        "inLanguage": "ja",
        "description": (
            f"{KW_SHORT}の使える店・加盟店を地図と店舗一覧でさくっと探せる非公式サイト。"
            f"全{fmt(TOTAL)}店・現在地から近い順・中小店舗絞り込み対応。"
        ),
        "publisher": {"@type": "Organization", "name": "株式会社plan8", "url": MAKER},
        "potentialAction": {
            "@type": "SearchAction",
            "target": {"@type": "EntryPoint", "urlTemplate": BASE + "/?q={search_term_string}"},
            "query-input": "required name=search_term_string",
        },
    }


def organization_json():
    return {
        "@type": "Organization",
        "name": "株式会社plan8",
        "url": MAKER,
        "sameAs": [MAKER],
    }


# ---------------------------------------------------------------- index.html injection
def inject_index():
    path = os.path.join(ROOT, "index.html")
    src = open(path, encoding="utf-8").read()

    # ----- GEN:head: GSC「使える店一覧」＋ AIO「地図でさくっと」を両立 -----
    title = f"{KW_SHORT} 使える店一覧 2026 地図で探す 全{fmt(TOTAL)}店（非公式）"
    desc = (
        f"{KW_SHORT} 使える店一覧を地図とリストでさくっと検索（全{fmt(TOTAL)}店・2026）。"
        f"現在地から近い順・中小店舗{fmt(STATS['small'])}店・カテゴリ/エリア対応。"
        f"加盟店マップの非公式まとめ。制作plan8"
    )
    og_title = f"{KW_SHORT} 使える店一覧を地図で探す（全{fmt(TOTAL)}店）"
    og_desc = (
        f"使える店・加盟店を地図でさくっと。中小店舗絞り込み・リスト表示対応。"
        f"非公式・plan8"
    )
    head = f"""<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{BASE}/">
<meta name="robots" content="index,follow,max-image-preview:large">
<meta name="author" content="株式会社plan8">
<meta property="og:title" content="{esc(og_title)}">
<meta property="og:description" content="{esc(og_desc)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{BASE}/">
<meta property="og:locale" content="ja_JP">
<meta property="og:site_name" content="{KW_SHORT} 使える店一覧">
<meta property="og:image" content="{BASE}/ogp.png">
<meta property="og:image:width" content="2400">
<meta property="og:image:height" content="1260">
<meta property="og:image:type" content="image/png">
<meta property="og:image:alt" content="{KW_SHORT} 使える店一覧 2026 — 制作 plan8">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(og_title)}">
<meta name="twitter:description" content="{esc(og_desc)}">
<meta name="twitter:image" content="{BASE}/ogp.png">"""

    wp = webpage_json(BASE + "/", title, speakable=True, about=f"{KW_SHORT} 使える店一覧")
    wp["speakable"] = {
        "@type": "SpeakableSpecification",
        "cssSelector": ["#answer", "#aio-map", "h1", "h2", "details summary"],
    }
    wp["description"] = desc
    head_ld = jsonld(
        website_json(), organization_json(), wp, webapp_json(),
        dataset_json(), category_itemlist_json(), faqpage_json(), howto_json(),
    )

    cat_links = "".join(
        f'<a href="/c/{CAT_SLUG[c]}/">{c}（{fmt(CAT_COUNT[c])}）</a>' for c in CAT_ORDER if CAT_COUNT[c])
    genre_links = "".join(
        f'<a href="/g/{slug}/">{esc(name.split("・")[0].split(" [")[0])}</a>' for name, slug, count in GENRES[:12])
    area_links = "".join(
        f'<a href="/area/{slug}/">{esc(name.replace("大分市",""))}</a>' for name, slug, count in AREAS[:12])

    g_konbini = genre_counter.get("コンビニ", 0)
    g_super = genre_counter.get("スーパー", 0)
    g_iza = genre_counter.get("居酒屋・小料理", 0)
    small_n = STATS["small"]
    large_n = STATS["large"]

    seo = f"""<section class="seo-content" id="about">
  <div class="ans" id="answer"><strong>{KW_SHORT} 使える店一覧</strong>は、本サイトの<strong>地図とリスト</strong>でさくっと探せます。掲載は<strong>全{fmt(TOTAL)}店</strong>（最終更新 {BUILD_DATE}・非公式）。買う{fmt(CAT_COUNT['買う'])}・食べる{fmt(CAT_COUNT['食べる'])}・暮らす{fmt(CAT_COUNT['暮らす'])}・遊ぶ{fmt(CAT_COUNT['遊ぶ'])}・泊まる{fmt(CAT_COUNT['泊まる'])}。中小・小規模 {fmt(small_n)}店。現在地から近い順・カテゴリ/エリア/業種でも検索可。最新は公式で確認を。</div>
  <h1>{KW_SHORT} 使える店一覧を地図で探す 2026（非公式）</h1>
  <p id="aio-map">このサイトは、<strong>{KW_SHORT}の使える店（加盟店）を地図でさくっと探す</strong>ための非公式マップです。
  店舗一覧を見ながら地図上の位置を確認でき、現在地からの距離順やリスト表示にも切り替えられます（株式会社plan8・更新 {BUILD_DATE}）。
  公式サイトの一覧表示に対し、本サイトは<strong>地図×店舗一覧のすばやい検索</strong>に特化しています。</p>
  <p>「{KW_SHORT} 使える店一覧」「使える店」「加盟店」で探している方向けに、全<strong>{fmt(TOTAL)}店</strong>を掲載。
  コンビニ{fmt(g_konbini)}・スーパー{fmt(g_super)}・居酒屋{fmt(g_iza)}など。デジタル対応{fmt(STATS['digital'])}店／紙対応{fmt(STATS['paper'])}店。
  行政の「{KW_NOKI}」・特設サイトの「{KW_KI}」と同じ事業です。</p>
  <p class="seo-links">
    <a href="/"><b>地図で使える店を探す →</b></a>
    <a href="/list/"><b>使える店一覧（全{fmt(TOTAL)}店）</b></a>
    <a href="/?size=small"><b>中小店舗を地図で検索（{fmt(small_n)}店）</b></a>
    <a href="/guide/">制度の要点</a>
    <a href="{OFFICIAL}/" rel="noopener">公式サイト</a>
  </p>

  <h2>地図で店舗一覧をさくっと探す（このサイトの使い方）</h2>
  <ol class="howto">
    <li><b>地図を開く</b> — 使える店がピンで表示されます</li>
    <li><b>さがす・絞り込み</b> — 店名・カテゴリ・エリア・業種・中小店舗・デジタル対応</li>
    <li><b>現在地</b> — 近い順に並べ替え</li>
    <li><b>リスト表示</b> — 店舗一覧をスクロールして確認</li>
    <li><b>店をタップ</b> — 住所・対応・ルート案内</li>
  </ol>

  <h2>{KW_SHORT} 使える店一覧（カテゴリ別）</h2>
  <nav class="seo-links">{cat_links}</nav>
  <h2>{KW_SHORT} 使える店を業種から探す</h2>
  <nav class="seo-links">{genre_links}</nav>
  <h2>{KW_SHORT} 使える店をエリアから探す</h2>
  <nav class="seo-links">{area_links}</nav>

  <h2>{KW_SHORT} 中小店舗一覧・中小店舗検索</h2>
  <p>1冊のうち<strong>中小・小規模店専用券 7,000円分</strong>は、中小・小規模の加盟店でのみ使えます。
  中小・小規模は<strong>{fmt(small_n)}店</strong>。地図の店舗区分「中小・小規模店舗」、または
  <a href="/?size=small">中小店舗の地図検索</a>でさくっとしぼれます。大規模は{fmt(large_n)}店。</p>
  <p class="seo-links">
    <a href="/?size=small"><b>地図で中小店舗検索 →</b></a>
    <a href="/list/#small"><b>中小店舗の説明・件数</b></a>
  </p>

  <h2>公式一覧との違い</h2>
  <p><a href="{OFFICIAL}/" rel="noopener">公式特設サイト</a>は加盟店の正式な一覧と制度案内の場です。
  本サイトは非公式で、<strong>地図上で使える店をすぐ見つける・近い店から並べる・中小店舗だけ探す</strong>用途に寄せています。
  利用期間・購入方法・最新の加盟可否は必ず公式でご確認ください。</p>

  <h2>{KW_SHORT}の制度の要点（参考）</h2>
  <p>プレミアム率<strong>30%</strong>、利用期間<strong>2026年6月1日〜8月31日</strong>、1人4冊まで（{FACTS_ASOF}の公式概要）。
  購入は事前申込の抽選。最新日程は
  <a href="{OFFICIAL}/" rel="noopener">公式</a>・<a href="{CITY_OFFICIAL}" rel="noopener">大分市案内</a>が正です。</p>
  <p class="seo-links"><a href="/guide/">{KW_SHORT}とは・使える店の探し方ガイド →</a></p>

  <h2>よくある質問（使える店一覧・地図検索・中小店舗）</h2>
  {faq_html()}

  <h2>データの出典</h2>
  <p>加盟店データは公式の店舗一覧（<a href="{OFFICIAL_JSON}" rel="noopener nofollow">store_list.json</a>）をもとにしています（最終更新 {BUILD_DATE}・全{fmt(TOTAL)}店）。
  位置は国土地理院の住所検索。{fmt(sum(1 for s in stores if not is_precise(s)))}店はおおよその位置です。
  地図は OpenStreetMap・CARTO。電話番号は非掲載。本サイトは非公式です。</p>
  {FOOTER}
</section>"""

    src = _replace_region(src, "GEN:head", head)
    src = _replace_region(src, "GEN:jsonld", head_ld)
    src = _replace_region(src, "GEN:seo", seo)
    open(path, "w", encoding="utf-8").write(src)


def _replace_region(src, tag, content):
    start, end = f"<!-- {tag} -->", f"<!-- /{tag} -->"
    pat = re.compile(re.escape(start) + ".*?" + re.escape(end), re.S)
    block = f"{start}\n{content}\n{end}"
    if pat.search(src):
        return pat.sub(lambda _: block, src)
    raise SystemExit(f"marker {tag} not found in index.html — add {start} ... {end}")


# ---------------------------------------------------------------- robots / sitemap / llms
def write_robots():
    ai = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot",
          "Claude-User", "PerplexityBot", "Perplexity-User", "Google-Extended",
          "Applebot-Extended", "Amazonbot", "Meta-ExternalAgent", "DuckAssistBot",
          "MistralAI-User", "CCBot", "Bytespider"]
    lines = [
        "# robots.txt — https://op2026.plan8.jp/",
        "# 公開の非公式加盟店ディレクトリ。検索エンジン・AI検索/取得botともに全許可。",
        "",
        "User-agent: *",
        "Allow: /",
        "",
        "# AI検索・生成エンジンでの被引用を歓迎（明示的に許可）",
    ]
    for ua in ai:
        lines += [f"User-agent: {ua}", "Allow: /", ""]
    lines += [f"Sitemap: {BASE}/sitemap.xml", ""]
    open(os.path.join(ROOT, "robots.txt"), "w", encoding="utf-8").write("\n".join(lines))


def write_sitemap():
    urls = [(BASE + "/", "daily", "1.0")] + SITEMAP_URLS
    seen, rows = set(), []
    for u, f, p in urls:
        if u in seen:
            continue
        seen.add(u)
        rows.append(f"  <url><loc>{u}</loc><lastmod>{BUILD_DATE}</lastmod>"
                    f"<changefreq>{f}</changefreq><priority>{p}</priority></url>")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           + "\n".join(rows) + "\n</urlset>\n")
    open(os.path.join(ROOT, "sitemap.xml"), "w", encoding="utf-8").write(xml)
    return len(seen)


def write_llms():
    g = "".join(f"\n- 業種: {n.split('・')[0]}（{fmt(c)}店） → {BASE}/g/{s}/" for n, s, c in GENRES)
    a = "".join(f"\n- エリア: {n.replace('大分市','')}（{fmt(c)}店） → {BASE}/area/{s}/" for n, s, c in AREAS)
    txt = f"""# {KW_SHORT}2026 使える店マップ（非公式・株式会社plan8制作）

> {KW_SHORT}（{KW_BOTH}）2026が使える加盟店{fmt(TOTAL)}店を地図・カテゴリ・エリア・業種で探せる非公式まとめ。データ最終更新 {BUILD_DATE}。最新・正確な情報は公式({OFFICIAL})で確認。
> 表記ゆれ（同一事業）: {KW_SHORT} / {KW_KI} / {KW_NOKI} / プレミアム商品券 / 大分市 商品券。

## 概要（件数）
- 総加盟店数（本サイト掲載・使える店）: {fmt(TOTAL)}店
- カテゴリ別: 買う {fmt(CAT_COUNT['買う'])} / 食べる {fmt(CAT_COUNT['食べる'])} / 暮らす {fmt(CAT_COUNT['暮らす'])} / 遊ぶ {fmt(CAT_COUNT['遊ぶ'])} / 泊まる {fmt(CAT_COUNT['泊まる'])}
- 対応: デジタル対応 {fmt(STATS['digital'])}店 / 紙対応 {fmt(STATS['paper'])}店
- 規模: 中小・小規模店 {fmt(STATS['small'])}店 / 大規模店 {fmt(STATS['large'])}店

## 制度の概要（{FACTS_ASOF}の公式概要より・最新は公式で確認）
- プレミアム率: 30%（1万円→1万3,000円分）
- 利用期間: 2026年6月1日〜8月31日
- 購入上限: 1人4冊まで（最大4万円→5万2,000円分）
- 購入方法: 事前申込制の抽選方式（先着ではない）

## 主要ページ
- [制度まとめ・使える店の探し方]({BASE}/guide/)
- [加盟店一覧（全{fmt(TOTAL)}店）]({BASE}/list/)
- [カテゴリ: 買う]({BASE}/c/kau/) / [食べる]({BASE}/c/taberu/) / [暮らす]({BASE}/c/kurasu/){g}{a}
- [地図で探す（現在地から近い順）]({BASE}/)
- [全店データ(テキスト)]({BASE}/llms-full.txt)

## データ出典
- 公式サイト: {OFFICIAL}
- 公式データ: {OFFICIAL_JSON}
- 座標: 国土地理院ジオコーディング（おおよその位置を含む）
- 制作: 株式会社plan8 {MAKER} （非公式）
"""
    open(os.path.join(ROOT, "llms.txt"), "w", encoding="utf-8").write(txt)

    lines = [f"# 大分市プレミアム付き商品券（プレミアム付商品券）2026 加盟店一覧（全{fmt(TOTAL)}店・非公式 / plan8）",
             f"# データ最終更新 {BUILD_DATE} ・ 出典 {OFFICIAL_JSON} ・ 電話番号は非掲載",
             "# 形式: 店名｜よみ｜業種｜住所｜対応｜規模｜個別ページURL",
             ""]
    for c in CAT_ORDER:
        items = sorted((s for s in stores if s.get("store_category_major_name") == c),
                       key=lambda s: s.get("store_id", ""))
        if not items:
            continue
        lines.append(f"\n## {c}（{fmt(len(items))}店）")
        for s in items:
            pay = "/".join([t for t, ok in (("デジタル", s.get("digital_coupon")), ("紙", s.get("paper_coupon"))) if ok]) or "—"
            sz = "中小・小規模店" if s.get("is_small_store") else "大規模店"
            kana = s.get("store_name_kana", "")
            lines.append(f"- {s['store_name']}｜{kana}｜{s.get('store_category_minor_name','')}｜{addr(s)}｜{pay}｜{sz}｜{BASE}/s/{s['store_id']}/")
    open(os.path.join(ROOT, "llms-full.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


# ---------------------------------------------------------------- PII guard
def assert_no_phone():
    """生成物に電話番号らしき文字列が混入していないか検査（将来の回帰防止）。"""
    import glob
    pat = re.compile(r"0[789]0\d{7,8}|0\d{1,3}-\d{2,4}-\d{3,4}|tel:\s*0\d")
    targets = ["index.html", "robots.txt", "sitemap.xml", "llms.txt", "llms-full.txt"]
    for d in ("list", "c", "g", "area", "guide", "s"):
        targets += [os.path.relpath(p, ROOT) for p in
                    glob.glob(os.path.join(ROOT, d, "**", "*.html"), recursive=True)]
    hits = []
    for rel in targets:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        for ln in open(p, encoding="utf-8"):
            if pat.search(ln):
                hits.append((rel, ln.strip()[:90]))
    if hits:
        for rel, ln in hits[:10]:
            print(f"  PII? {rel} :: {ln}")
        raise SystemExit(f"build aborted: {len(hits)} 件の電話番号らしき出力を検出（tel は非掲載のはず）")


# ---------------------------------------------------------------- main
def main():
    build_categories()
    build_genres()
    build_areas()
    build_combos()
    build_stores()
    build_list_hub()
    build_guide()
    inject_index()
    write_robots()
    n = write_sitemap()
    write_llms()
    assert_no_phone()
    print(f"built: {TOTAL} stores | categories {len([c for c in CAT_ORDER if CAT_COUNT[c]])} "
          f"| genres {len(GENRES)} | areas {len(AREAS)} | combos {len(COMBOS)} | store pages {TOTAL} "
          f"| sitemap urls {n} | updated {BUILD_DATE} | PII-check OK")


if __name__ == "__main__":
    main()
