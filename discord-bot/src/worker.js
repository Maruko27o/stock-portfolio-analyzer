// Cloudflare Worker: Discord のスラッシュコマンド /analyze を受け取り、
// GitHub Actions(daily-report.yml)を銘柄指定で起動する。分析結果は既存の
// Discord Webhook 通知としてチャンネルに届く仕組み。
//
// 必要な環境変数(wrangler.toml の [vars] と `wrangler secret put`):
//   DISCORD_PUBLIC_KEY … Discord アプリの Public Key(署名検証。secret 推奨)
//   GITHUB_TOKEN       … repo の actions:write 権限を持つ PAT(secret)
//   GITHUB_OWNER / GITHUB_REPO / WORKFLOW_FILE / GITHUB_REF … 起動先(vars)

const PING = 1;
const APPLICATION_COMMAND = 2;
const PONG = { type: 1 };
const CHANNEL_MESSAGE = 4;
const EPHEMERAL = 64; // 実行者だけに見える「受付」メッセージ(結果は全員に届く)

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "POST") {
      return new Response("Discord analyze worker is running.", { status: 200 });
    }
    const body = await request.text();
    const valid = await verifyDiscordRequest(request, body, env.DISCORD_PUBLIC_KEY);
    if (!valid) return new Response("invalid request signature", { status: 401 });

    const interaction = JSON.parse(body);
    if (interaction.type === PING) return json(PONG);
    if (interaction.type === APPLICATION_COMMAND) return handleCommand(interaction, env);
    return json({ type: CHANNEL_MESSAGE, data: { content: "未対応のリクエストです。", flags: EPHEMERAL } });
  },
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json" },
  });
}

async function handleCommand(interaction, env) {
  const option = (interaction.data.options || []).find((o) => o.name === "code");
  const raw = option && option.value ? String(option.value).trim() : "";
  if (!raw) {
    return json({
      type: CHANNEL_MESSAGE,
      data: { content: "銘柄コードを指定してください。例: /analyze code:7203", flags: EPHEMERAL },
    });
  }
  try {
    await triggerWorkflow(raw, env);
  } catch (e) {
    return json({
      type: CHANNEL_MESSAGE,
      data: { content: `⚠️ 分析の起動に失敗しました（${e}）。管理者に連絡してください。`, flags: EPHEMERAL },
    });
  }
  return json({
    type: CHANNEL_MESSAGE,
    data: {
      content: `🔍 ${raw} を分析中… 結果はこのチャンネルに届きます（30〜60秒ほど）。`,
      flags: EPHEMERAL,
    },
  });
}

async function triggerWorkflow(symbols, env) {
  const url =
    `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}` +
    `/actions/workflows/${env.WORKFLOW_FILE}/dispatches`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "discord-analyze-worker",
      "content-type": "application/json",
    },
    body: JSON.stringify({ ref: env.GITHUB_REF || "main", inputs: { symbols } }),
  });
  if (!res.ok) {
    throw new Error(`GitHub ${res.status}: ${await res.text()}`);
  }
}

// Discord は Ed25519 署名で正当なリクエストか検証させる。WebCrypto で検証する
// (npm 依存なし)。Cloudflare Workers は Ed25519 に対応。
async function verifyDiscordRequest(request, body, publicKeyHex) {
  const signature = request.headers.get("x-signature-ed25519");
  const timestamp = request.headers.get("x-signature-timestamp");
  if (!signature || !timestamp || !publicKeyHex) return false;
  try {
    const key = await crypto.subtle.importKey(
      "raw",
      hexToBytes(publicKeyHex),
      { name: "Ed25519" },
      false,
      ["verify"]
    );
    return await crypto.subtle.verify(
      { name: "Ed25519" },
      key,
      hexToBytes(signature),
      new TextEncoder().encode(timestamp + body)
    );
  } catch (e) {
    return false;
  }
}

function hexToBytes(hex) {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = parseInt(hex.substr(i * 2, 2), 16);
  }
  return bytes;
}
