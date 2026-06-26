# 大分市プレミアム付き商品券2026 加盟店マップ（非公式）

[公式の加盟店一覧](https://2026.oita-pay.jp/digital/MemberShipList)を**地図で探せる**ようにした非公式マップ。

🔗 公開サイト：**https://op2026.plan8.jp** ／ 制作：[株式会社plan8](https://plan8.jp)

## 特長

- 🗺 **地図表示**：加盟店をカテゴリ色分け＋クラスタ表示（拡大で1店ずつに展開）
- 🔎 **絞り込み**：カテゴリ（食べる／買う／暮らす／遊ぶ／泊まる）・業種・店名・住所・かなで検索
- 📍 **現在地**：現在地を中心に表示し、**近い順**に並べ替え
- 🔁 **地図 ⇄ リスト**切り替え（リストは現在地からの距離順）
- ⟳ **更新**：最新の加盟店データを取得し、**新規店舗だけ**自動で位置取得して追加
- 🌙 ダークモード対応／見やすい大きめフォント・シンプルなUI

## 仕組み

- 加盟店データは公式の `store_list.json` をブラウザが直接取得（住所のみ）
- 住所→緯度経度の変換は[国土地理院 住所検索API](https://msearch.gsi.go.jp/)（無料・キー不要）
- 既存店は再取得せず、新規・移転した店だけを位置取得して IndexedDB に保存
- 地図：Leaflet + markercluster、ベースマップは CARTO（light/dark）

## ローカルで動かす

現在地機能は `https` か `localhost` でのみ動作します。

```bash
python3 -m http.server 8000
# → http://localhost:8000
```

### データ更新＋SEOページの再生成

最新の公式データを取り込み、検索向けの静的ページ（後述）も作り直す手順：

```bash
curl -s https://2026.oita-pay.jp/docs/store_list/store_list.json -o data/store_list.raw.json
python3 scripts/refresh.py        # 公式の最新へ増分更新（既存店の座標は保持・新規のみジオコード）
python3 scripts/build_site.py     # 一覧/カテゴリ/エリア/業種ページ・sitemap・robots・llms を再生成
git add -A && git commit -m "data refresh" && git push   # GitHub Pages へ反映
```

- アプリ右上の ⟳ ボタンはブラウザ内（IndexedDB）だけを更新します。**検索エンジン向けの静的ページは ⟳ では更新されない**ので、SEO上の鮮度は必ず上記リビルドで反映します。
- `scripts/geocode.py` は全件ジオコーディングのフル再生成（QA済み座標を作り直したいときだけ）。通常は座標を保全する `scripts/refresh.py` を使います。

## SEO / AIO 用の静的ページ（自動生成）

`scripts/build_site.py` が `data/stores.geo.json` を唯一の真実の源として、検索エンジン・AI検索に拾われるテキストページを生成します（地図はJS描画なので単体ではクロール不可なため）。

- `index.html` … `<!-- GEN:jsonld -->` / `<!-- GEN:seo -->` の領域に JSON-LD と概要・FAQ・フッターを注入
- `list/index.html` … 加盟店一覧ハブ（全件の入口）
- `c/<slug>/` … カテゴリ別（買う/食べる/暮らす/遊ぶ/泊まる、大きいものは `/2/` で連番分割）
- `g/<slug>/` … 主要業種（居酒屋・コンビニ 等）／ `area/<slug>/` … 主要エリア（要町・中央町 等）
- `robots.txt`（AIクローラ明示許可）・`sitemap.xml`・`llms.txt`・`llms-full.txt`

方針：**非公式**表示と公式リンクを全ページ恒久表示／件数・日付はビルドで一括算出して常に同期／電話番号は出力しない（PII配慮）。

## 構成

```
├── index.html      地図UI（+ build_site.py が生成領域を注入）
├── style.css       スタイル（ライト/ダーク・SEOページ）
├── app.js          本体（地図・検索・現在地・更新・/#store= /?q= 受け）
├── data/
│   ├── store_list.raw.json   公式データ取得そのまま
│   └── stores.geo.json       加盟店データ（緯度経度付き・正本）
├── list/ c/ g/ area/         生成された検索向けページ（build_site.py 出力）
├── robots.txt sitemap.xml llms.txt llms-full.txt   生成物
└── scripts/
    ├── geocode.py    住所→緯度経度（フル再生成）
    ├── refresh.py    公式最新への増分更新（座標保全）
    └── build_site.py 静的SEO/AIOページ生成器
```

## 出典・注意

- 個人制作の**非公式**ツールです。最新・正確な情報は必ず[公式サイト](https://2026.oita-pay.jp/)でご確認ください。
- 加盟店データ © 大分市プレミアム付き商品券事業 ／ 地図 © OpenStreetMap contributors, © CARTO ／ 位置情報 © 国土地理院

## AIでおすすめ（フリーテキスト検索）

検索ボックスに「家族でランチ」「贈り物を買いたい」などを入力して **✨ボタン**（またはEnter）を押すと、Claude が要望から **カテゴリ・業種・キーワード** を判定し、ローカルの加盟店データを「おすすめ順」に並べ替えて提案します（理由文つき）。

- キーは静的サイトに置けないため、**Supabase Edge Function がプロキシ**としてキーを保持し Claude を呼びます。サイトは要望テキストだけを送信。
- モデル **Claude Haiku 4.5**。全店リストはClaudeに渡さず「絞り込み条件」を受け取ってクライアントが絞る（低コスト・店名のハルシネーション無し）。
- 保護：オリジン許可リスト＋IP単位レート制限＋入力長制限。
- 関数ソース：`supabase/functions/oitapay-recommend/index.ts`。デプロイ先・再デプロイ手順は社内メモ（`運用メモ.md`）参照。
