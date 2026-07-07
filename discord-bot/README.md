# Discord で銘柄コードを入力して分析する (Cloudflare Worker)

Discord で `/analyze code:7203` と入力すると、GitHub Actions が起動してその銘柄を
AIファンドマネージャーで分析し、結果を**このチャンネルの通知**として返します。
Cloudflare Worker(無料・サーバー管理不要・常時稼働)が Discord と GitHub の橋渡しをします。
PC を閉じていても動きます。

```
Discord /analyze 7203
      │  (スラッシュコマンド)
      ▼
Cloudflare Worker  ──►  GitHub Actions (daily-report.yml, symbols=7203)
                              │
                              ▼
                   既存の Discord Webhook 通知でチャンネルに結果が届く
```

## 必要なもの
- Discord アカウント(サーバーの管理権限)
- Cloudflare アカウント(無料)
- この GitHub リポジトリへの `workflow_dispatch` 権限を持つ Personal Access Token
- Node.js 18 以上(コマンド登録・デプロイに使用)

---

## セットアップ手順

### 1. Discord アプリを作る
1. https://discord.com/developers/applications →「New Application」で作成
2. **General Information** の以下を控える
   - `APPLICATION ID` → 後で `DISCORD_APP_ID`
   - `PUBLIC KEY` → 後で `DISCORD_PUBLIC_KEY`
3. **Bot** タブ →「Reset Token」でトークンを発行 → `DISCORD_BOT_TOKEN`
4. **Installation**(または OAuth2 → URL Generator)で、スコープ `applications.commands` を
   付けた招待URLを作り、自分のサーバーにアプリを追加

### 2. GitHub トークンを作る
1. GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate new token
2. Repository access: この `stock-portfolio-analyzer` のみ
3. Permissions → **Actions: Read and write** を付与
4. 生成された `github_pat_...` を控える → `GITHUB_TOKEN`

### 3. スラッシュコマンドを登録する
このディレクトリで:
```bash
npm install
DISCORD_APP_ID=xxxx DISCORD_BOT_TOKEN=yyyy DISCORD_GUILD_ID=zzzz npm run register
```
- `DISCORD_GUILD_ID`(= 対象サーバーのID。開発者モードでサーバー右クリック→IDをコピー)を
  付けると**即時反映**。省略するとグローバル登録(最大1時間で反映)。

### 4. Cloudflare Worker をデプロイする
`wrangler.toml` の `GITHUB_OWNER` / `GITHUB_REPO` が正しいことを確認し:
```bash
npx wrangler login
npx wrangler secret put DISCORD_PUBLIC_KEY   # 手順1のPublic Key を貼る
npx wrangler secret put GITHUB_TOKEN         # 手順2のPAT を貼る
npm run deploy
```
デプロイ後に表示される URL(例: `https://discord-analyze.<account>.workers.dev`)を控える。

### 5. Discord にエンドポイントを教える
1. Discord Developer Portal → 対象アプリ → **General Information**
2. **INTERACTIONS ENDPOINT URL** に手順4の Worker URL を貼って保存
   - 保存時に Discord が検証リクエストを送る。成功すれば設定完了(Worker が署名検証に対応済み)

---

## 使い方
Discord のチャンネルで:
```
/analyze code:7203
/analyze code:7203,6758   （カンマ区切りで複数）
```
「🔍 分析中…」の受付メッセージ(本人のみ表示)の後、30〜60秒でチャンネルに分析結果が届きます。

## 補足・トラブルシュート
- 応答が来ない場合は、GitHub の **Actions** タブで `Daily Portfolio Notification` の
  手動実行(workflow_dispatch)が走っているか確認。
- INTERACTIONS ENDPOINT URL の保存に失敗する場合、`DISCORD_PUBLIC_KEY` の値が
  正しく設定されているか(手順4の secret)を確認。
- 分析対象の銘柄は保有していなくてOK(オンデマンド分析)。日本株は数字コードだけでOK(例 `7203`)。
