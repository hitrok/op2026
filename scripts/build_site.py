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
MAKER = "https://plan8.jp"
PER_PAGE = 250

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
}
# 上位エリア（address_1 の町名）→ ローマ字slug。ここに無い町はエリアページを作らない。
AREA_SLUG = {
    "大分市要町": "kanamemachi", "大分市中央町": "chuomachi", "大分市府内町": "funaimachi",
    "大分市公園通り西": "koendori-nishi", "大分市都町": "miyakomachi", "大分市玉沢": "tamazawa",
    "大分市森町": "morimachi", "大分市萩原": "hagiwara", "大分市田中町": "tanakamachi",
    "大分市中戸次": "nakahetsugi", "大分市下郡": "shimogori", "大分市金池町": "kanaikemachi",
    "大分市大手町": "otemachi", "大分市皆春": "minaharu", "大分市畑中": "hatanaka",
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
GENRES = [(g, GENRE_SLUG[g], genre_counter[g]) for g in GENRE_SLUG if genre_counter[g] >= 40]
GENRES.sort(key=lambda x: -x[2])
AREAS = [(a, AREA_SLUG[a], area_counter[a]) for a in AREA_SLUG if area_counter[a] >= 20]
AREAS.sort(key=lambda x: -x[2])


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
             "url": f"{BASE}/#store={s['store_id']}"}
            for i, s in enumerate(items)
        ],
    }


def jsonld(*objs):
    graph = [o for o in objs if o]
    doc = {"@context": "https://schema.org", "@graph": graph}
    return '<script type="application/ld+json">' + json.dumps(doc, ensure_ascii=False) + "</script>"


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
        f'<a class="n" href="/#store={esc(s["store_id"])}">{esc(s["store_name"])}</a> '
        f'<span class="g">{esc(minor)}</span>'
        f'<span class="a">{esc(addr(s))}</span>'
        f'<div class="badges">{"".join(badges)}</div>'
        "</li>"
    )


def page(path, title, desc, h1, lead_html, body_html, breadcrumb, itemlist=None, extra_head=""):
    """1ページを書き出す。path は ROOT 相対（例 'c/kau/index.html'）。"""
    url = BASE + "/" + os.path.dirname(path).replace("index.html", "")
    url = url.rstrip("/") + "/"
    if path == "index.html":
        url = BASE + "/"
    ld = jsonld(breadcrumb, itemlist)
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
def render_store_pages(items, slug_dir, title_base, h1_base, desc_base, crumb_parent, kind_label):
    """items を PER_PAGE ごとに分割して slug_dir/[n/]index.html を生成。生成URL一覧を返す。"""
    items = sorted(items, key=lambda s: s.get("store_id", ""))
    npages = max(1, (len(items) + PER_PAGE - 1) // PER_PAGE)
    urls = []
    for p in range(1, npages + 1):
        chunk = items[(p - 1) * PER_PAGE: p * PER_PAGE]
        sub = "" if p == 1 else f"{p}/"
        path = f"{slug_dir}/{sub}index.html"
        suffix = "" if p == 1 else f"（{p}/{npages}ページ）"
        title = f"{title_base}{suffix}｜大分市プレミアム商品券2026 加盟店一覧（非公式）"
        h1 = f"{h1_base}{suffix}"
        # ページ2以降は meta description を一意にする（重複説明の回避）
        desc = desc_base if p == 1 else f"{desc_base}（{p}/{npages}ページ）"
        lead = f'<p class="lead">{desc_base}このページでは{esc(kind_label)}の加盟店を一覧で確認できます（{fmt(len(items))}店中 {(p-1)*PER_PAGE+1}〜{min(p*PER_PAGE,len(items))}店）。店名をタップすると地図で場所を確認できます。電話番号は各店・公式サイトでご確認ください。</p>'
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
        body = pager + lst + pager
        url = page(path, title, desc[:158], h1, lead, body,
                   crumb, itemlist=itemlist_json(chunk, h1), extra_head=extra)
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
        em = CAT_EMOJI[c]
        title_base = f"{em}{c}（{fmt(len(items))}店）"
        h1_base = f"大分市プレミアム商品券2026 「{c}」で使える加盟店一覧（{fmt(len(items))}店）"
        desc = (f"大分市プレミアム付き商品券2026が使える「{c}」カテゴリの加盟店{fmt(len(items))}店の一覧（非公式）。"
                f"店名・業種・住所・デジタル/紙対応がわかります。制作:plan8。")
        urls = render_store_pages(items, f"c/{slug}", title_base, h1_base, desc,
                                  HOME_CRUMB, f"カテゴリ「{c}」")
        for u, f in urls:
            add_url(u, f, "0.7" if u.endswith(f"/c/{slug}/") else "0.5")


def build_genres():
    for name, slug, count in GENRES:
        items = [s for s in stores if s.get("store_category_minor_name") == name]
        short = name.split("・")[0].split(" [")[0]
        title_base = f"{short}（{fmt(count)}店）"
        h1_base = f"大分市プレミアム商品券2026が使える{short}の加盟店一覧（{fmt(count)}店）"
        desc = (f"大分市プレミアム付き商品券2026が使える{short}（{esc(name)}）の加盟店{fmt(count)}店の一覧（非公式）。"
                f"店名・住所・デジタル/紙対応がわかります。制作:plan8。")
        urls = render_store_pages(items, f"g/{slug}", title_base, h1_base, desc,
                                  HOME_CRUMB, short)
        for u, f in urls:
            add_url(u, f, "0.6" if u.endswith(f"/g/{slug}/") else "0.5")


def build_areas():
    for name, slug, count in AREAS:
        items = [s for s in stores if area_of(s) == name]
        title_base = f"{name}（{fmt(count)}店）"
        h1_base = f"{name}でプレミアム商品券2026が使える加盟店一覧（{fmt(count)}店）"
        desc = (f"大分市プレミアム付き商品券2026が使える{name}周辺の加盟店{fmt(count)}店の一覧（非公式）。"
                f"店名・業種・デジタル/紙対応がわかります。制作:plan8。")
        urls = render_store_pages(items, f"area/{slug}", title_base, h1_base, desc,
                                  HOME_CRUMB, name)
        for u, f in urls:
            add_url(u, f, "0.5")


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
        f'<p class="lead">大分市プレミアム付き商品券2026が使える加盟店は全<b>{fmt(TOTAL)}店</b>です（最終更新 {BUILD_DATE}・非公式まとめ）。'
        f'カテゴリ別では 買う{fmt(CAT_COUNT["買う"])}・食べる{fmt(CAT_COUNT["食べる"])}・暮らす{fmt(CAT_COUNT["暮らす"])}・遊ぶ{fmt(CAT_COUNT["遊ぶ"])}・泊まる{fmt(CAT_COUNT["泊まる"])}。'
        f'デジタル対応{fmt(STATS["digital"])}店／紙対応{fmt(STATS["paper"])}店。'
        f'下のカテゴリ・ジャンル・エリアから、使えるお店を探せます。地図で探す場合は <a href="/">加盟店マップ</a> をご利用ください。</p>'
    )
    body = (
        '<h2>カテゴリから探す</h2>'
        f'<div class="links">{cat_links}</div>'
        '<h2>ジャンルから探す（主要業種）</h2>'
        f'<div class="links">{genre_links}</div>'
        '<h2>エリアから探す（主要地区）</h2>'
        f'<div class="links">{area_links}</div>'
        '<h2>よくある質問</h2>'
        + faq_html()
        + '<p style="margin-top:18px"><a class="pill" href="/llms-full.txt">全店データ（テキスト版）</a> '
          '<a class="pill" href="/">地図で探す</a></p>'
    )
    dataset = dataset_json()
    crumb = breadcrumb_json([("ホーム", "/"), ("加盟店一覧", None)])
    title = f"大分市プレミアム商品券2026 加盟店一覧（全{fmt(TOTAL)}店）｜カテゴリ・エリア・業種別で探す（非公式）"
    desc = (f"大分市プレミアム付き商品券2026の加盟店一覧（全{fmt(TOTAL)}店・非公式）。"
            f"買う{fmt(CAT_COUNT['買う'])}・食べる{fmt(CAT_COUNT['食べる'])}など、カテゴリ・業種・エリア別に使えるお店を一覧で探せます。制作:plan8。")
    # list hub では itemlist の代わりに dataset と faq を @graph に積む
    ld = jsonld(crumb, dataset, faqpage_json())
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
<h1>大分市プレミアム商品券2026 加盟店一覧（全{fmt(TOTAL)}店）</h1>
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


# ---------------------------------------------------------------- FAQ + structured data shared
def faqs():
    s = STATS
    return [
        ("大分市プレミアム商品券が使える店は？",
         f"{BUILD_DATE}時点で、大分市プレミアム付き商品券2026が使える加盟店は全{fmt(TOTAL)}店です。"
         f"カテゴリ別では買う{fmt(CAT_COUNT['買う'])}・食べる{fmt(CAT_COUNT['食べる'])}・暮らす{fmt(CAT_COUNT['暮らす'])}・遊ぶ{fmt(CAT_COUNT['遊ぶ'])}・泊まる{fmt(CAT_COUNT['泊まる'])}に分かれ、"
         f"本サイトでカテゴリ・エリア・業種から検索・地図表示できます。最新・正確な情報は公式サイト（2026.oita-pay.jp）でご確認ください。"),
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
        "keywords": ["大分市プレミアム付き商品券", "プレミアム商品券", "加盟店", "店舗一覧", "大分市"],
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
        "alternateName": "大分市プレミアム商品券2026 店舗一覧・加盟店マップ",
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

    head_ld = jsonld(website_json(), organization_json(), dataset_json(), faqpage_json())

    cat_links = "".join(
        f'<a href="/c/{CAT_SLUG[c]}/">{c}（{fmt(CAT_COUNT[c])}）</a>' for c in CAT_ORDER if CAT_COUNT[c])
    genre_links = "".join(
        f'<a href="/g/{slug}/">{esc(name.split("・")[0].split(" [")[0])}</a>' for name, slug, count in GENRES[:10])
    area_links = "".join(
        f'<a href="/area/{slug}/">{esc(name.replace("大分市",""))}</a>' for name, slug, count in AREAS[:10])

    seo = f"""<section class="seo-content" id="about">
  <h2>大分市プレミアム付き商品券2026の加盟店を一覧・地図で探す（非公式）</h2>
  <p>このページは、<strong>大分市プレミアム付き商品券2026</strong>が使える加盟店<strong>{fmt(TOTAL)}店</strong>を検索・地図表示できる非公式のまとめです（株式会社plan8制作・データ最終更新 {BUILD_DATE}）。
  カテゴリ別では 買う{fmt(CAT_COUNT['買う'])}・食べる{fmt(CAT_COUNT['食べる'])}・暮らす{fmt(CAT_COUNT['暮らす'])}・遊ぶ{fmt(CAT_COUNT['遊ぶ'])}・泊まる{fmt(CAT_COUNT['泊まる'])}店。
  デジタル対応{fmt(STATS['digital'])}店／紙対応{fmt(STATS['paper'])}店／中小・小規模店{fmt(STATS['small'])}店。
  「大分市プレミアム商品券が使える店」「加盟店一覧」「使える飲食店」を、地図・現在地からの距離・カテゴリ/エリア/業種でかんたんに探せます。</p>
  <p class="seo-links"><a href="/list/"><b>加盟店一覧（全{fmt(TOTAL)}店）を見る →</b></a></p>
  <h3>カテゴリから探す</h3>
  <nav class="seo-links">{cat_links}</nav>
  <h3>業種から探す</h3>
  <nav class="seo-links">{genre_links}</nav>
  <h3>エリアから探す</h3>
  <nav class="seo-links">{area_links}</nav>
  <h3>よくある質問</h3>
  {faq_html()}
  <h3>このデータについて</h3>
  <p>加盟店データは公式の店舗一覧（<a href="{OFFICIAL_JSON}" rel="noopener nofollow">store_list.json</a>）をもとにしています（最終更新 {BUILD_DATE}・全{fmt(TOTAL)}店）。
  位置情報は国土地理院の住所検索によるもので、{fmt(sum(1 for s in stores if not is_precise(s)))}店はおおよその位置（丁目の中心）です。
  地図は OpenStreetMap・CARTO を利用しています。電話番号はプライバシー配慮のため掲載していません。</p>
  {FOOTER}
</section>"""

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
    g = "".join(f"\n- ジャンル: {n.split('・')[0]}({fmt(c)}店) → {BASE}/g/{s}/" for n, s, c in GENRES[:10])
    a = "".join(f"\n- エリア: {n.replace('大分市','')}({fmt(c)}店) → {BASE}/area/{s}/" for n, s, c in AREAS[:8])
    txt = f"""# 大分市プレミアム付き商品券2026 加盟店マップ（非公式・株式会社plan8制作）

> 大分市プレミアム付き商品券2026が使える加盟店{fmt(TOTAL)}店を検索・カテゴリ別・エリア別・業種別・地図表示できる非公式まとめ。データ最終更新 {BUILD_DATE}。本サイトは非公式であり、最新・正確な情報は公式サイト({OFFICIAL})でご確認ください。

## 概要（件数）
- 総加盟店数: {fmt(TOTAL)}店
- カテゴリ別: 買う {fmt(CAT_COUNT['買う'])} / 食べる {fmt(CAT_COUNT['食べる'])} / 暮らす {fmt(CAT_COUNT['暮らす'])} / 遊ぶ {fmt(CAT_COUNT['遊ぶ'])} / 泊まる {fmt(CAT_COUNT['泊まる'])}
- 対応: デジタル対応 {fmt(STATS['digital'])}店 / 紙対応 {fmt(STATS['paper'])}店
- 規模: 中小・小規模店 {fmt(STATS['small'])}店 / 大規模店 {fmt(STATS['large'])}店

## 主要ページ
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

    lines = [f"# 大分市プレミアム付き商品券2026 加盟店一覧（全{fmt(TOTAL)}店・非公式 / plan8）",
             f"# データ最終更新 {BUILD_DATE} ・ 出典 {OFFICIAL_JSON} ・ 電話番号は非掲載",
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
            lines.append(f"- {s['store_name']}｜{s.get('store_category_minor_name','')}｜{addr(s)}｜{pay}｜{sz}")
    open(os.path.join(ROOT, "llms-full.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


# ---------------------------------------------------------------- PII guard
def assert_no_phone():
    """生成物に電話番号らしき文字列が混入していないか検査（将来の回帰防止）。"""
    import glob
    pat = re.compile(r"0[789]0\d{7,8}|0\d{1,3}-\d{2,4}-\d{3,4}|tel:\s*0\d")
    targets = ["index.html", "robots.txt", "sitemap.xml", "llms.txt", "llms-full.txt"]
    for d in ("list", "c", "g", "area"):
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
    build_list_hub()
    inject_index()
    write_robots()
    n = write_sitemap()
    write_llms()
    assert_no_phone()
    print(f"built: {TOTAL} stores | categories {len([c for c in CAT_ORDER if CAT_COUNT[c]])} "
          f"| genres {len(GENRES)} | areas {len(AREAS)} | sitemap urls {n} | updated {BUILD_DATE} | PII-check OK")


if __name__ == "__main__":
    main()
