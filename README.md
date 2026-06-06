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

### 初期データの再生成（任意）

```bash
curl -s https://2026.oita-pay.jp/docs/store_list/store_list.json -o data/store_list.raw.json
python3 scripts/geocode.py        # → data/stores.geo.json を再生成
```

通常はアプリの ⟳ ボタンで最新化できるため、再生成はほぼ不要です。

## 構成

```
├── index.html      UI
├── style.css       スタイル（ライト/ダーク）
├── app.js          本体（地図・検索・現在地・更新・ジオコーディング）
├── data/
│   └── stores.geo.json   加盟店データ（緯度経度付き）
└── scripts/
    └── geocode.py        住所→緯度経度の生成スクリプト
```

## 出典・注意

- 個人制作の**非公式**ツールです。最新・正確な情報は必ず[公式サイト](https://2026.oita-pay.jp/)でご確認ください。
- 加盟店データ © 大分市プレミアム付き商品券事業 ／ 地図 © OpenStreetMap contributors, © CARTO ／ 位置情報 © 国土地理院
