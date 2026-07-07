// Discord に /analyze スラッシュコマンドを登録する。1回だけ実行すればよい。
//
// 実行(いずれも Discord Developer Portal から取得):
//   DISCORD_APP_ID=xxx DISCORD_BOT_TOKEN=yyy [DISCORD_GUILD_ID=zzz] node register-commands.js
//
// DISCORD_GUILD_ID を指定するとそのサーバーに即時反映(テスト向き)。
// 省略するとグローバル登録(全サーバー・反映に最大1時間)。

const APP_ID = process.env.DISCORD_APP_ID;
const BOT_TOKEN = process.env.DISCORD_BOT_TOKEN;
const GUILD_ID = process.env.DISCORD_GUILD_ID;

if (!APP_ID || !BOT_TOKEN) {
  console.error("DISCORD_APP_ID と DISCORD_BOT_TOKEN を環境変数で指定してください。");
  process.exit(1);
}

const command = {
  name: "analyze",
  description: "指定した銘柄コードをAIファンドマネージャーで分析します",
  options: [
    {
      type: 3, // STRING
      name: "code",
      description: "銘柄コード（例: 7203 / AAPL）。カンマ区切りで複数指定も可",
      required: true,
    },
  ],
};

const url = GUILD_ID
  ? `https://discord.com/api/v10/applications/${APP_ID}/guilds/${GUILD_ID}/commands`
  : `https://discord.com/api/v10/applications/${APP_ID}/commands`;

const res = await fetch(url, {
  method: "POST",
  headers: { Authorization: `Bot ${BOT_TOKEN}`, "content-type": "application/json" },
  body: JSON.stringify(command),
});

const text = await res.text();
if (res.ok) {
  console.log(`✅ 登録しました (${GUILD_ID ? "guild" : "global"}):`, text);
} else {
  console.error(`❌ 登録失敗 ${res.status}:`, text);
  process.exit(1);
}
