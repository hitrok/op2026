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
ALIASES  = [
    KW_KI + "2026", KW_SHORT + "2026", KW_NOKI, "プレミアム付商品券",
    "プレミアム付き商品券", "プレミアム商品券", "おおいた市プレミアム商品券",
    "令和8年度 大分市プレミアム付き商品券", "大分市 商品券 2026", "大分市 商品券",
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
:root{--bg:#f2f2f7;--card:#fff;--text:#1c1c1e;--text2:#3a3a3c;--text3:#8e8e93;--sep:#e3e3e8;--accent:#007aff;--red:#ff3b30}
@media(prefers-color-scheme:dark){:root{--bg:#000;--card:#1c1c1e;--text:#f2f2f7;--text2:#c7c7cc;--text3:#8e8e93;--sep:#2c2c2e;--accent:#0a84ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:"Hiragino Kaku Gothic ProN","Hiragino Sans","Noto Sans JP",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;line-height:1.6;-webkit-text-size-adjust:100%}
.wrap{max-width:880px;margin:0 auto;padding:16px 16px 64px}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.bc{font-size:13px;color:var(--text3);margin:6px 0 14px;display:flex;flex-wrap:wrap;gap:4px}
.bc a{color:var(--text3)}.bc span[aria-current]{color:var(--text2)}
h1{font-size:24px;font-weight:800;letter-spacing:-.02em;line-height:1.3;margin:.2em 0 .3em}
h2{font-size:19px;font-weight:700;margin:1.6em 0 .5em;letter-spacing:-.01em}
.lead{font-size:15px;color:var(--text2);margin:.4em 0 1em}
.upd{display:inline-block;font-size:12.5px;color:var(--text3);border:1px solid var(--sep);border-radius:999px;padding:2px 10px;margin-bottom:10px}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 4px}
.stat{background:var(--card);border:1px solid var(--sep);border-radius:12px;padding:8px 12px;font-size:13.5px}
.stat b{font-size:17px;font-weight:800;display:block}
.links{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 4px}
.pill{display:inline-block;background:var(--card);border:1px solid var(--sep);border-radius:999px;padding:6px 13px;font-size:14px;font-weight:600;color:var(--text)}
.pill:hover{border-color:var(--accent);text-decoration:none}
ul.stores{list-style:none;padding:0;margin:10px 0}
ul.stores li{background:var(--card);border:1px solid var(--sep);border-radius:12px;padding:11px 14px;margin-bottom:8px}
ul.stores .n{font-size:16px;font-weight:700;letter-spacing:-.01em}
ul.stores .g{font-size:13px;color:var(--accent);margin-left:0}
ul.stores .a{display:block;font-size:13.5px;color:var(--text3);margin-top:2px}
.badges{margin-top:5px;display:flex;flex-wrap:wrap;gap:5px}
.bdg{font-size:11.5px;font-weight:700;border-radius:6px;padding:1px 7px;border:1px solid var(--sep);color:var(--text2)}
.bdg.d{background:#5856d61a;border-color:#5856d655;color:#5856d6}
.bdg.p{background:#34c7591a;border-color:#34c75955;color:#1a8c3a}
@media(prefers-color-scheme:dark){.bdg.p{color:#34c759}}
.pager{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0;align-items:center}
.pager a,.pager span{border:1px solid var(--sep);border-radius:9px;padding:6px 12px;font-size:14px;font-weight:600}
.pager span[aria-current]{background:var(--accent);color:#fff;border-color:var(--accent)}
details{background:var(--card);border:1px solid var(--sep);border-radius:12px;padding:0 14px;margin-bottom:8px}
details summary{font-weight:700;cursor:pointer;padding:12px 0;font-size:15px}
details p{margin:0 0 12px;color:var(--text2);font-size:14.5px}
.foot{margin-top:34px;padding-top:16px;border-top:1px solid var(--sep);font-size:13px;color:var(--text3)}
.foot b{color:var(--red)}
.foot a{color:var(--text2)}
.back{display:inline-block;margin:18px 0 0;font-weight:600}
table.sum{border-collapse:collapse;margin:10px 0 6px;font-size:14px;width:100%;max-width:520px}
table.sum th,table.sum td{border:1px solid var(--sep);padding:6px 12px;text-align:left}
table.sum th{background:var(--card);color:var(--text2);font-weight:700;white-space:nowrap;width:48%}
.note{font-size:13px;color:var(--text3);margin:4px 0 0}
ol.howto{padding-left:22px;margin:8px 0}
ol.howto li{margin:7px 0;font-size:15px}
"""

FOOTER = (
    '<footer class="foot">'
    '<p>本サイトは<b>非公式</b>です。株式会社plan8が制作した、大分市プレミアム付き商品券2026の加盟店を探すための検索ツールです。'
    f'最新・正確な情報（利用期間・購入方法・利用条件など）は必ず公式サイト <a href="{OFFICIAL}/" rel="noopener">大分市プレミアム付き商品券2026（公式）</a> でご確認ください。</p>'
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
<meta property="og:site_name" content="大分市プレミアム付き商品券2026 加盟店マップ（非公式）">
<meta property="og:locale" content="ja_JP">
<meta property="og:image" content="{BASE}/ogp.png">
<meta name="twitter:card" content="summary_large_image">
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
        f'<a class="pill" href="/c/{CAT_SLUG[c]}/">{CAT_EMOJI[c]} {c} {fmt(CAT_COUNT[c])}</a>'
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
    lead = (
        f'<p class="lead">{KW_BOTH}2026が使える加盟店（使える店）は全<b>{fmt(TOTAL)}店</b>を掲載しています（最終更新 {BUILD_DATE}・非公式まとめ）。'
        f'カテゴリ別では 買う{fmt(CAT_COUNT["買う"])}・食べる{fmt(CAT_COUNT["食べる"])}・暮らす{fmt(CAT_COUNT["暮らす"])}・遊ぶ{fmt(CAT_COUNT["遊ぶ"])}・泊まる{fmt(CAT_COUNT["泊まる"])}。'
        f'デジタル対応{fmt(STATS["digital"])}店／紙対応{fmt(STATS["paper"])}店。'
        f'下のカテゴリ・業種・エリアから、使える店・使えるお店を探せます。地図で近くのお店を探す場合は <a href="/">加盟店マップ</a> をご利用ください。'
        f'（「大分市プレミアム付き商品券」「大分市プレミアム付商品券」「大分市プレミアム商品券」とも表記されます。）</p>'
    )
    body = (
        stats_table(stores)
        + '<p class="links" style="margin:10px 0 2px"><a class="pill" href="/guide/"><b>大分市プレミアム付き商品券2026とは・使える店の探し方を見る →</b></a></p>'
        + '<h2>使える店をカテゴリから探す</h2>'
        f'<div class="links">{cat_links}</div>'
        '<h2>使える店を業種から探す（主要業種）</h2>'
        f'<div class="links">{genre_links}</div>'
        '<h2>使えるお店をエリアから探す（主要地区）</h2>'
        f'<div class="links">{area_links}</div>'
        '<h2>よくある質問</h2>'
        + faq_html()
        + '<p style="margin-top:18px"><a class="pill" href="/llms-full.txt">全店データ（テキスト版）</a> '
          '<a class="pill" href="/">地図で探す</a></p>'
    )
    dataset = dataset_json()
    crumb = breadcrumb_json([("ホーム", "/"), ("加盟店一覧", None)])
    title = f"大分市プレミアム付き商品券2026 加盟店一覧 全{fmt(TOTAL)}店 使える店をカテゴリ エリア 業種別に探す（非公式）"
    desc = (f"{KW_BOTH}2026の加盟店一覧（全{fmt(TOTAL)}店・非公式）。"
            f"買う{fmt(CAT_COUNT['買う'])}・食べる{fmt(CAT_COUNT['食べる'])}など、カテゴリ・業種・エリア別に使える店・使えるお店を一覧で探せます。制作plan8。")
    # list hub では itemlist の代わりに dataset・FAQ・HowTo・CollectionPage を @graph に積む
    ld = jsonld(
        crumb,
        webpage_json(BASE + "/list/", title, crumb, speakable=True, collection=True,
                     about=KW_KI + "2026 加盟店"),
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
<meta property="og:site_name" content="大分市プレミアム付き商品券2026 加盟店マップ（非公式）">
<meta property="og:locale" content="ja_JP">
<meta property="og:image" content="{BASE}/ogp.png">
<meta name="twitter:card" content="summary_large_image">
{ld}
<style>{PAGE_CSS}</style>
</head>
<body>
<div class="wrap">
<nav class="bc">{breadcrumb_html(crumb)}</nav>
<h1>大分市プレミアム付き商品券2026 加盟店一覧（使える店 全{fmt(TOTAL)}店）</h1>
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
        f'<p class="lead">{KW_BOTH}2026について、制度の概要と「使える店」の探し方をまとめた'
        f'<b>非公式</b>のガイドです（株式会社plan8制作）。本ページは参考情報で、'
        f'最新・正確な内容は公式サイト <a href="{OFFICIAL}/" rel="noopener">2026.oita-pay.jp</a> でご確認ください。</p>'
    )
    body = (
        "<h2>大分市プレミアム付商品券が使えるお店はどこ？</h2>"
        f'<p>大分市プレミアム付商品券（プレミアム付き商品券）2026が使えるお店は、本サイトの'
        f'<a href="/">加盟店マップ</a>と<a href="/list/">店舗一覧（全{fmt(TOTAL)}店）</a>から、'
        f"業種・エリア・現在地で探せます。大型店から中小・小規模店まで、"
        f"コンビニ・スーパー・ドラッグストア・ガソリンスタンドなどの買い物、"
        f"居酒屋・カフェ・焼肉などの飲食、暮らしのサービスまで、幅広い業種のお店が対象です。</p>"
        "<h2>大分市プレミアム付き商品券2026とは（制度の概要）</h2>"
        f"<p>大分市プレミアム付き商品券（プレミアム付商品券）2026は、大分市内のお店で使えるプレミアム付きの商品券です。"
        f"おもな内容は次のとおりです（{FACTS_ASOF}の公式概要より）。</p>"
        + facts_table
        + f'<p class="note">上記は{FACTS_ASOF}の公式概要にもとづく参考情報です。申込・抽選・2次募集など最新の日程や条件は'
          f'公式サイト（<a href="{OFFICIAL}/" rel="noopener">2026.oita-pay.jp</a>）と'
          f'<a href="{CITY_OFFICIAL}" rel="noopener">大分市の案内</a>でご確認ください。</p>'
        "<h2>「付」と「付き」表記について</h2>"
        "<p>大分市（行政）の案内では「大分市プレミアム付商品券」、事業主体の大分商工会議所と公式特設サイトでは"
        "「大分市プレミアム付き商品券」と表記され、「付」と「付き」の両表記が公式に併存しています。"
        "「大分市プレミアム商品券」と省略して呼ばれることもありますが、いずれも同じ事業を指します。</p>"
        "<h2>使える店の探し方</h2>"
        f'<ol class="howto">{steps}</ol>'
        + related_block("使える店をカテゴリから探す", hub_pairs)
        + "<h2>よくある質問</h2>" + faq_html()
    )
    crumb = breadcrumb_json([("ホーム", "/"), ("ガイド", None)])
    title = "大分市プレミアム付き商品券2026とは 使える店の探し方 まとめ（非公式）"
    h1 = "大分市プレミアム付き商品券（プレミアム付商品券）2026とは 使える店の探し方"
    desc = (f"{KW_BOTH}2026とは。プレミアム率30%・利用期間2026年6月1日〜8月31日・1人4冊まで・抽選方式などの概要と、"
            f"使える店・使えるお店の探し方をまとめた非公式ガイド。最新は公式サイトで確認。制作plan8。")
    url = page("guide/index.html", title, desc[:158], h1, lead, body, crumb,
               extra_ld=[howto_json(), faqpage_json()], speakable=True, about=KW_KI + "2026")
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
        ("大分市プレミアム付商品券（プレミアム付き商品券）が使える店・お店はどこ？",
         f"{BUILD_DATE}時点で、{KW_BOTH}2026が使える加盟店は全{fmt(TOTAL)}店を掲載しています。"
         f"カテゴリ別では買う{fmt(CAT_COUNT['買う'])}・食べる{fmt(CAT_COUNT['食べる'])}・暮らす{fmt(CAT_COUNT['暮らす'])}・遊ぶ{fmt(CAT_COUNT['遊ぶ'])}・泊まる{fmt(CAT_COUNT['泊まる'])}。"
         f"本サイトでカテゴリ・エリア・業種から使える店を検索でき、地図で近くの使えるお店も探せます。最新・正確な情報は公式サイト（2026.oita-pay.jp）でご確認ください。"),
        ("「プレミアム付商品券」と「プレミアム付き商品券」は同じものですか？",
         "同じ事業を指します。大分市（行政）の案内では「大分市プレミアム付商品券」、"
         "事業主体の大分商工会議所と公式特設サイト（2026.oita-pay.jp）では「大分市プレミアム付き商品券」と表記され、"
         "「付」と「付き」の両表記が公式に併存しています。「大分市プレミアム商品券」と省略して呼ばれることもあります。本サイトはどの呼び方でも使える店を探せます。"),
        ("大分市プレミアム付き商品券2026のプレミアム率は何%ですか？",
         f"プレミアム率は30%です（{FACTS_ASOF}の公式概要より）。販売額1万円につき1万3,000円分の商品券を購入でき、1人4冊まで（最大4万円→5万2,000円分）です。"
         "1冊の内訳は全店舗共通券6,000円分＋中小・小規模店専用券7,000円分。最新の条件は公式サイトでご確認ください。"),
        ("大分市プレミアム付き商品券2026はいつまで使えますか？",
         f"利用期間は2026年6月1日（月）〜8月31日（月）です（{FACTS_ASOF}の公式概要より）。"
         "本サイトは「どの店で使えるか」を探すための非公式マップです。購入・チャージ期間や2次抽選など最新の日程は公式サイトでご確認ください。"),
        ("大分市プレミアム付き商品券2026はどうやって買えますか？",
         f"事前申込制の抽選方式です（先着ではありません・{FACTS_ASOF}の公式概要より）。"
         "インターネットで購入を事前申込し、申込多数の場合は抽選で購入冊数が決まり、結果通知後に販売所で購入またはアプリにチャージします。"
         "購入対象は大分県内在住者（大分市在住者を優先）。申込日程・手順の詳細は公式サイトでご確認ください。"),
        ("近くで大分市プレミアム付商品券が使えるお店を探すには？",
         f"本サイトの地図で現在地を許可すると、近い順に使えるお店を表示できます。エリア別・業種別ページからも絞り込めます。全{fmt(TOTAL)}店を掲載しています。"),
        ("使える飲食店はどれくらいありますか？",
         f"飲食を含む「食べる」カテゴリの加盟店は{fmt(CAT_COUNT['食べる'])}店です。"
         f"主なジャンルは居酒屋{fmt(genre_counter.get('居酒屋・小料理',0))}・和食/すし{fmt(genre_counter.get('和食・すし・割烹',0))}・カフェ{fmt(genre_counter.get('カフェ・喫茶店',0))}・焼肉{fmt(genre_counter.get('焼肉・肉料理・鉄板焼き',0))}などで、ジャンル別ページから探せます。"),
        ("デジタルと紙、どちらで使える店が多いですか？",
         f"大分市プレミアム付き商品券2026は、デジタル対応が{fmt(s['digital'])}店、紙対応が{fmt(s['paper'])}店です。"
         f"多くの店が両方に対応していますが、店舗により異なるため各店の対応バッジでご確認ください。"),
        ("加盟店一覧はどこで見られますか？",
         f"本サイトの加盟店一覧ページ（/list/）で全{fmt(TOTAL)}店を一覧できます。"
         f"カテゴリ・エリア・業種別ページや地図表示も用意しています。なお本サイトは非公式で、公式の店舗一覧は2026.oita-pay.jpにあります。"),
        ("使えるコンビニやスーパーはありますか？",
         f"はい。加盟店にはコンビニ{fmt(genre_counter.get('コンビニ',0))}店、スーパー{fmt(genre_counter.get('スーパー',0))}店、ドラッグストア{fmt(genre_counter.get('ドラッグストア',0))}店が含まれます。"
         f"日常の買い物でも大分市プレミアム付き商品券2026を使えます。各業種ページから確認できます。"),
        ("中小・小規模店だけでしか使えませんか？",
         f"いいえ。大分市プレミアム付き商品券2026は中小・小規模店{fmt(s['small'])}店を含む計{fmt(TOTAL)}店で使えます。"
         f"大規模店舗{fmt(s['large'])}店でも利用できる店があり、本サイトでは店舗区分で絞り込めます。"),
        ("特定エリアで使える店を探せますか？",
         f"はい。エリア別ページで探せます。例として要町{fmt(area_counter.get('大分市要町',0))}店・中央町{fmt(area_counter.get('大分市中央町',0))}店・府内町{fmt(area_counter.get('大分市府内町',0))}店などの加盟店があり、地図の現在地検索で近くのお店も探せます。"),
        ("このサイトは公式ですか？",
         f"いいえ。本サイトは株式会社plan8が制作した非公式の検索ツールです。"
         f"公式の店舗一覧（2026.oita-pay.jp）が一覧表示中心なのに対し、本サイトは地図・現在地からの距離検索・カテゴリ/エリア/業種別の絞り込みを加えて探しやすくしています。利用条件など正確な情報は必ず公式サイトでご確認ください。"),
        ("データはいつ時点のものですか？",
         f"本サイトのデータは公式の店舗一覧（store_list.json）をもとに、最終更新{BUILD_DATE}時点で全{fmt(TOTAL)}店を掲載しています。"
         f"キャンペーン期間中は定期的に更新していますが、最新状況は公式サイトでご確認ください。"),
        ("利用期間や購入方法は？",
         f"利用条件・利用期間・購入方法などの制度面は、公式サイト（2026.oita-pay.jp）および大分市の案内が正となります。"
         f"本サイトは「どの店で使えるか」を探すための非公式マップで、制度詳細は公式情報をご確認ください。"),
        ("電話番号や営業時間はわかりますか？",
         f"本サイトでは店名・住所・業種・デジタル/紙の対応・営業時間（記載がある店）を掲載しています。"
         f"電話番号は個人事業主の携帯番号が多く含まれるため、プライバシー配慮から掲載しておらず、連絡先は公式サイトや各店へ直接ご確認ください。"),
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


# 「使える店の探し方」（制度ではなく自サイトの操作手順なので HowTo 化しても非公式の線引きを保てる）
HOWTO_STEPS = [
    ("エリアか業種でしぼる", "使える店をカテゴリ・エリア・業種から選びます。"),
    ("地図を開く", "加盟店マップを開くと、使えるお店が地図に表示されます。"),
    ("現在地で近い順に並べる", "現在地を許可すると、近くの使えるお店から順に並びます。"),
    ("店名をタップして詳細を見る", "店名・住所・業種・デジタル/紙の対応を確認できます。"),
]


def howto_json():
    return {
        "@type": "HowTo",
        "name": "大分市プレミアム付き商品券2026の使える店を地図で探す",
        "step": [{"@type": "HowToStep", "position": i + 1, "name": n, "text": t}
                 for i, (n, t) in enumerate(HOWTO_STEPS)],
    }


def dataset_json():
    return {
        "@type": "Dataset",
        "name": "大分市プレミアム付き商品券2026 加盟店データ（非公式まとめ）",
        "description": f"大分市プレミアム付き商品券2026が使える加盟店{fmt(TOTAL)}店の名称・業種・住所・カテゴリ・デジタル/紙対応・位置情報のまとめ。株式会社plan8が公式店舗一覧をもとに作成した非公式データセット。",
        "url": BASE + "/list/",
        "creator": {"@type": "Organization", "name": "株式会社plan8", "url": MAKER},
        "isBasedOn": OFFICIAL_JSON,
        "dateModified": BUILD_DATE,
        "spatialCoverage": {"@type": "Place", "name": "大分県大分市"},
        "alternateName": ALIASES,
        "keywords": [
            KW_KI, KW_NOKI, "プレミアム付商品券", KW_SHORT, "プレミアム商品券",
            "加盟店", "店舗一覧", "使える店", "使えるお店", "お店", "大分市 商品券", "大分市",
        ],
        "variableMeasured": [
            {"@type": "PropertyValue", "name": "加盟店総数", "value": TOTAL},
            {"@type": "PropertyValue", "name": "デジタル対応店数", "value": STATS["digital"]},
            {"@type": "PropertyValue", "name": "紙対応店数", "value": STATS["paper"]},
        ],
    }


def website_json():
    return {
        "@type": "WebSite",
        "name": "大分市プレミアム付き商品券2026 加盟店マップ（非公式）",
        "alternateName": ALIASES,
        "url": BASE + "/",
        "inLanguage": "ja",
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

    # ----- GEN:head: title / description / canonical / OGP を生成器の所有下に置く -----
    title = f"{KW_KI}2026 加盟店マップ・店舗一覧 使える店を地図で探す（非公式）"
    desc = (f"{KW_BOTH}2026が使える加盟店{fmt(TOTAL)}店を地図と店舗一覧で検索できる非公式まとめ。"
            f"カテゴリ・エリア・業種別や現在地から近い順に、使える店・使えるお店を探せます。"
            f"デジタル/紙の対応もわかる。制作plan8（最新情報は公式サイトで確認）")
    og_title = f"{KW_KI}2026 加盟店マップ・店舗一覧 使える店を地図で探す（非公式）"
    og_desc = (f"使える加盟店{fmt(TOTAL)}店を一覧・地図で検索。カテゴリ・エリア・業種別、現在地から近い順。"
               f"大分市プレミアム付商品券とも表記。制作plan8")
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
<meta property="og:site_name" content="{KW_KI}2026 加盟店マップ">
<meta property="og:image" content="{BASE}/ogp.png">
<meta property="og:image:width" content="2400">
<meta property="og:image:height" content="1260">
<meta property="og:image:type" content="image/png">
<meta property="og:image:alt" content="{KW_KI}2026 加盟店マップ — 制作 plan8">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(og_title)}">
<meta name="twitter:description" content="{esc(og_desc)}">
<meta name="twitter:image" content="{BASE}/ogp.png">"""

    head_ld = jsonld(
        website_json(), organization_json(),
        webpage_json(BASE + "/", title, speakable=True, about=KW_KI + "2026 加盟店"),
        dataset_json(), faqpage_json(), howto_json(),
    )

    cat_links = "".join(
        f'<a href="/c/{CAT_SLUG[c]}/">{c}（{fmt(CAT_COUNT[c])}）</a>' for c in CAT_ORDER if CAT_COUNT[c])
    genre_links = "".join(
        f'<a href="/g/{slug}/">{esc(name.split("・")[0].split(" [")[0])}</a>' for name, slug, count in GENRES[:12])
    area_links = "".join(
        f'<a href="/area/{slug}/">{esc(name.replace("大分市",""))}</a>' for name, slug, count in AREAS[:12])

    seo = f"""<section class="seo-content" id="about">
  <h2>大分市プレミアム付き商品券（プレミアム付商品券）2026の使える店を一覧・地図で探す（非公式）</h2>
  <p>このページは、<strong>大分市プレミアム付き商品券（プレミアム付商品券）2026</strong>が使える加盟店<strong>{fmt(TOTAL)}店</strong>を検索・地図表示できる非公式のまとめです（株式会社plan8制作・データ最終更新 {BUILD_DATE}）。
  カテゴリ別では 買う{fmt(CAT_COUNT['買う'])}・食べる{fmt(CAT_COUNT['食べる'])}・暮らす{fmt(CAT_COUNT['暮らす'])}・遊ぶ{fmt(CAT_COUNT['遊ぶ'])}・泊まる{fmt(CAT_COUNT['泊まる'])}店。
  デジタル対応{fmt(STATS['digital'])}店／紙対応{fmt(STATS['paper'])}店／中小・小規模店{fmt(STATS['small'])}店。
  使えるお店は、大型店から中小・小規模店まで、コンビニ・スーパー・ドラッグストア・ガソリンスタンドなどの買い物、居酒屋・カフェ・焼肉などの飲食、暮らしのサービスまで幅広い業種が対象です。
  「どこで使える？」「近くの使えるお店は？」を、地図・現在地からの距離・カテゴリ/エリア/業種でかんたんに探せます。
  （「大分市プレミアム付き商品券」「大分市プレミアム付商品券」「大分市プレミアム商品券」とも表記されます。）</p>
  <p class="seo-links"><a href="/list/"><b>大分市プレミアム付き商品券2026の加盟店一覧（全{fmt(TOTAL)}店）を見る →</b></a>
  ・<a href="/guide/">制度のまとめ・使える店の探し方</a></p>
  <h3>使える店をカテゴリから探す</h3>
  <nav class="seo-links">{cat_links}</nav>
  <h3>使えるお店を業種から探す</h3>
  <nav class="seo-links">{genre_links}</nav>
  <h3>近くの使える店をエリアから探す</h3>
  <nav class="seo-links">{area_links}</nav>
  <h3>よくある質問</h3>
  {faq_html()}
  <h3>このデータについて</h3>
  <p>加盟店データは公式の店舗一覧（<a href="{OFFICIAL_JSON}" rel="noopener nofollow">store_list.json</a>）をもとにしています（最終更新 {BUILD_DATE}・全{fmt(TOTAL)}店）。
  位置情報は国土地理院の住所検索によるもので、{fmt(sum(1 for s in stores if not is_precise(s)))}店はおおよその位置（丁目の中心）です。
  地図は OpenStreetMap・CARTO を利用しています。電話番号はプライバシー配慮のため掲載していません。</p>
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
    txt = f"""# 大分市プレミアム付き商品券2026 加盟店マップ（非公式・株式会社plan8制作）

> {KW_BOTH}2026が使える加盟店{fmt(TOTAL)}店を検索・カテゴリ別・エリア別・業種別・地図表示できる非公式まとめ。データ最終更新 {BUILD_DATE}。本サイトは非公式であり、最新・正確な情報は公式サイト({OFFICIAL})でご確認ください。
> 別名・表記ゆれ（いずれも同一事業）: 大分市プレミアム付き商品券 / 大分市プレミアム付商品券 / 大分市プレミアム商品券 / 大分市 商品券。

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
