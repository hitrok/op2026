// oitapay-recommend — 大分市プレミアム商品券 加盟店マップ の「フリーテキスト→おすすめ条件」プロキシ
//
// 静的サイト(op2026.plan8.jp)はAnthropicキーを持てないため、このEdge Functionがキーを保持して
// Claude(Haiku)を呼ぶ。受け取るのは {query:"家族でランチ"} のみ。返すのは「どのカテゴリ/業種/
// キーワードで絞るか＋一言の理由」の構造化JSON。実際の店舗の絞り込み・並べ替えはクライアント側が
// ローカルの加盟店データに対して行う（Claudeに全2,600店は渡さない＝低コスト・ハルシネーション無し）。
//
// 保護: ①オリジン許可リスト ②入力長制限＋max_tokens上限 ③IP単位レート制限(SUPABASE_DB_URL・失敗時はfail-open)
// ホスト: santaku プロジェクトに間借り（ANTHROPIC_API_KEY は santaku の secrets）。
// デプロイ: supabase functions deploy oitapay-recommend --no-verify-jwt --project-ref noarrgikglfcprjiuqtf
//
// deno-lint-ignore-file no-explicit-any

import postgres from "https://deno.land/x/postgresjs@v3.4.5/mod.js";

const MODEL = "claude-haiku-4-5";
const MAX_QUERY_LEN = 200;
const RATE_MAX = 40; // 1IPあたり / RATE_WINDOW_MIN
const RATE_WINDOW_MIN = 10; // 分
const DAILY_MAX = 2000; // 全体の1日あたり呼び出し上限（コスト暴走の最終ガード。≈¥1,000/日）

const ALLOWED_ORIGINS = new Set([
  "https://op2026.plan8.jp",
  "http://localhost:8000",
  "http://localhost:8765",
  "http://127.0.0.1:8000",
]);

// Claude をグラウンディングするための語彙（加盟店データの主要カテゴリ・業種）。
const CATEGORIES = ["食べる", "買う", "暮らす", "遊ぶ", "泊まる"];
const GENRE_VOCAB = [
  "居酒屋・小料理", "和食・すし・割烹", "焼肉・肉料理・鉄板焼き", "ラーメン", "カフェ・喫茶店",
  "食堂・レストラン", "軽食・ファストフード", "中華料理", "洋食・イタリアン・フレンチ", "韓国料理",
  "そば・うどん", "スナック・ラウンジ・Bar", "和菓子・洋菓子", "惣菜・弁当屋", "パン・ベーカリー",
  "衣類・靴・雑貨・アクセサリー", "コンビニ", "スーパー", "ドラッグストア", "家電",
  "時計・宝石・メガネ・コンタクト", "美容・化粧品店", "書店・文具", "花・園芸", "ホームセンター",
  "エステ・サロン・マッサージ", "理容室・美容室", "クリーニング", "医療・介護・福祉",
  "自動車販売・整備・修理・タイヤ", "ガソリンスタンド", "リフォーム・建築", "学習塾・教室",
  "アミューズメント・娯楽", "スポーツ・フィットネス", "ホテル・旅館",
];

function corsHeaders(origin: string | null) {
  const allow = origin && ALLOWED_ORIGINS.has(origin) ? origin : "https://op2026.plan8.jp";
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "content-type",
    "Vary": "Origin",
  };
}

function json(body: unknown, status: number, origin: string | null) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...corsHeaders(origin) },
  });
}

// ---- レート制限（SUPABASE_DB_URL 経由・テーブルは無ければ作る・失敗時は通す） ----
let sql: ReturnType<typeof postgres> | null = null;
let tableReady = false;
function db() {
  if (sql) return sql;
  const url = Deno.env.get("SUPABASE_DB_URL");
  if (!url) return null;
  sql = postgres(url, { prepare: false, idle_timeout: 20, max: 2 });
  return sql;
}
// レート制限の判定。返り値 {ok, code?, msg?}。
//  - 1IPあたり RATE_MAX/RATE_WINDOW_MIN（fixed window）
//  - 全体で 1日 DAILY_MAX（日付キーで自動リセット。XFF偽装/IPローテでも効く最終ガード）
//  方針: DB_URL未設定は可用性優先で通す（既定で注入されるため通常起きない）。
//        DBがあるのにクエリが失敗した場合は fail-CLOSED（課金暴走を防ぐため拒否）。
async function checkLimits(ip: string): Promise<{ ok: boolean; code?: string; msg?: string }> {
  const conn = db();
  if (!conn) {
    console.error("SUPABASE_DB_URL not set — rate limiting disabled");
    return { ok: true };
  }
  try {
    if (!tableReady) {
      await conn`create table if not exists oitapay_rate_limits (
        key text primary key,
        count int not null default 0,
        window_start timestamptz not null default now()
      )`;
      tableReady = true;
    }
    // 全体の1日上限（JST日付をキーに。日付が変われば自然にリセット）
    const day = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
    const g = await conn`
      insert into oitapay_rate_limits (key, count, window_start)
      values (${"global:" + day}, 1, now())
      on conflict (key) do update set count = oitapay_rate_limits.count + 1
      returning count`;
    if ((g[0]?.count ?? 0) > DAILY_MAX) {
      return { ok: false, code: "daily_cap", msg: "本日は混み合っています。時間をおいてお試しください。" };
    }
    // 1IPあたり（fixed window）
    const r = await conn`
      insert into oitapay_rate_limits (key, count, window_start)
      values (${"ip:" + ip}, 1, now())
      on conflict (key) do update set
        count = case when oitapay_rate_limits.window_start < now() - (${RATE_WINDOW_MIN} || ' minutes')::interval
                     then 1 else oitapay_rate_limits.count + 1 end,
        window_start = case when oitapay_rate_limits.window_start < now() - (${RATE_WINDOW_MIN} || ' minutes')::interval
                     then now() else oitapay_rate_limits.window_start end
      returning count`;
    if ((r[0]?.count ?? 0) > RATE_MAX) {
      return { ok: false, code: "rate_limited", msg: "リクエストが多すぎます。少し時間をおいてからお試しください。" };
    }
    return { ok: true };
  } catch (e) {
    console.error("rate limit check failed (fail-closed)", e);
    return { ok: false, code: "limit_unavailable", msg: "混み合っています。少し時間をおいてお試しください。" };
  }
}

const SYSTEM = `あなたは「大分市プレミアム付き商品券2026」が使える加盟店を探す手伝いをするアシスタントです。
利用者の自由な要望（例:「家族でランチ」「雨の日に子どもと遊べる」「贈り物を買いたい」「近くで飲みたい」）から、
加盟店の絞り込み条件をJSONで出力します。

ルール:
- categories は次から0〜3個選ぶ: 食べる / 買う / 暮らす / 遊ぶ / 泊まる
- genres は店の業種名。できるだけ次の語彙から選ぶ（無ければ近い表現でよい）: ${GENRE_VOCAB.join(" / ")}
- keywords は店名・業種・住所に含まれそうな日本語の手がかり語（例:「座敷」「個室」「子連れ」「テイクアウト」「24時間」「駐車場」）。1〜6個。
- payment: 利用者がデジタル/紙を明示していれば "digital" か "paper"、無ければ "any"
- size: 大型店志向なら "large"、小規模・個人店志向なら "small"、無ければ "any"
- reason: 利用者に向けた日本語の一言提案（1〜2文・80字以内）。具体的な店名は作らない（実在を保証できないため）。
要望が曖昧なら無理に絞り込まず、categories/genresは広めに、keywordsは少なめにします。日本語で簡潔に。`;

const SCHEMA = {
  type: "object",
  additionalProperties: false,
  properties: {
    categories: { type: "array", items: { type: "string", enum: CATEGORIES } },
    genres: { type: "array", items: { type: "string" } },
    keywords: { type: "array", items: { type: "string" } },
    payment: { type: "string", enum: ["any", "digital", "paper"] },
    size: { type: "string", enum: ["any", "small", "large"] },
    reason: { type: "string" },
  },
  required: ["categories", "genres", "keywords", "payment", "size", "reason"],
};

Deno.serve(async (req) => {
  const origin = req.headers.get("origin");
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders(origin) });
  if (req.method !== "POST") return json({ error: "method not allowed" }, 405, origin);

  // ① オリジン許可リスト（ブラウザからの他サイト埋め込み・タダ乗りを遮断）
  // Origin が無い/許可外は拒否。正規のブラウザはクロスオリジンPOSTで必ずOriginを送るため、
  // 「Origin省略(curl等)で素通り」を塞ぐ。
  if (!origin || !ALLOWED_ORIGINS.has(origin)) {
    return json({ error: "forbidden origin" }, 403, origin);
  }

  // ② 入力検証
  let query = "";
  try {
    const body = await req.json();
    query = String(body?.query ?? "").trim();
  } catch {
    return json({ error: "invalid request" }, 400, origin);
  }
  if (!query) return json({ error: "query is required" }, 400, origin);
  if (query.length > MAX_QUERY_LEN) query = query.slice(0, MAX_QUERY_LEN);

  // ③ レート制限（IP単位＋全体1日上限）
  const ip = (req.headers.get("x-forwarded-for") ?? "").split(",")[0].trim() || "unknown";
  const lim = await checkLimits(ip);
  if (!lim.ok) {
    return json({ error: lim.code, message: lim.msg }, 429, origin);
  }

  const apiKey = Deno.env.get("ANTHROPIC_API_KEY");
  if (!apiKey) return json({ error: "server misconfigured" }, 500, origin);

  try {
    const res = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model: MODEL,
        max_tokens: 500,
        system: SYSTEM,
        output_config: { format: { type: "json_schema", schema: SCHEMA } },
        messages: [{ role: "user", content: query }],
      }),
    });
    if (!res.ok) {
      const t = await res.text();
      console.error("anthropic error", res.status, t.slice(0, 300));
      return json({ error: "upstream_error" }, 502, origin);
    }
    const data = await res.json();
    const text = (data?.content ?? []).filter((b: any) => b.type === "text").map((b: any) => b.text).join("");
    let parsed: any;
    try {
      parsed = JSON.parse(text);
    } catch {
      return json({ error: "parse_error" }, 502, origin);
    }
    // 出力の検証＋上限（max_tokensに頼らず明示的にキャップ）
    const arr = (v: any, n: number) => (Array.isArray(v) ? v : []).map((x) => String(x)).slice(0, n);
    return json({
      categories: (Array.isArray(parsed.categories) ? parsed.categories : []).filter((c: any) => CATEGORIES.includes(c)).slice(0, 5),
      genres: arr(parsed.genres, 12),
      keywords: arr(parsed.keywords, 8),
      payment: ["any", "digital", "paper"].includes(parsed.payment) ? parsed.payment : "any",
      size: ["any", "small", "large"].includes(parsed.size) ? parsed.size : "any",
      reason: String(parsed.reason ?? "").slice(0, 200),
    }, 200, origin);
  } catch (e) {
    console.error("handler error", e);
    return json({ error: "internal_error" }, 500, origin);
  }
});
