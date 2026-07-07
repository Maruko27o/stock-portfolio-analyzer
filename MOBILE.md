# iPhoneだけで改修・運用する（すべて無料）

このツールは GitHub 上にあり、分析は GitHub Actions（クラウド）で動きます。
なので **PCが無くても、iPhoneのブラウザ／GitHubアプリだけで改修・運用**できます。追加費用はかかりません。

## できること早見表

| やりたいこと | iPhoneでの方法 | 無料 |
|---|---|---|
| 分析のしきい値を調整 | `stock_analyzer/data/tuning.json` を編集（下記①） | ✅ |
| コードを直接編集 | github.dev（下記②） | ✅ |
| AIの提案(PR)を確認して反映 | GitHubアプリでPRをレビュー→Merge（下記③） | ✅ |
| いますぐ再分析する | Actionsを手動実行 or Discordで `/analyze`（下記④） | ✅ |

---

## ① コードを書かずに“調整”する（一番かんたん）

分析の重み・上限・しきい値は `stock_analyzer/data/tuning.json` の**1ファイル**で上書きできます。

1. iPhoneのブラウザで、このリポジトリの `stock_analyzer/data/` を開く
2. 見本の `tuning.example.json` を参考に、`tuning.json` を新規作成（または編集）
   - GitHubの画面右上「Add file」→「Create new file」→ ファイル名に `stock_analyzer/data/tuning.json`
   - 例：`{ "ALLOC_NAME_CAP": 0.25, "CATEGORY_CAPS": { "valuation": 25 } }`
3. 「Commit changes」→ **次回の自動実行（毎日12:00/21:00）から反映**
   - すぐ試したいときは ④ で手動実行

> 壊れたJSONや知らないキーは無視され、既定値のまま安全に動きます（通知は止まりません）。
> 調整できるキーの一覧は `tuning.example.json` を参照。

## ② コードそのものを編集する（github.dev＝ブラウザ版VS Code）

1. iPhoneのブラウザでリポジトリを開き、URLの **`github.com` を `github.dev` に打ち替える**
   （例：`https://github.dev/Maruko27o/stock-portfolio-analyzer`）
2. 無料のブラウザ版エディタが開く。ファイルを編集
3. 左の「ソース管理」タブ→メッセージを入れて **Commit & Push**
4. `main` に直接コミットすれば Actions が自動で走る。慎重にやるならブランチを切ってPRに（③）

## ③ AIの提案（PR）を確認して反映する

②③④のAI（レビューAI・自己改修AI・最適化AI）は、改善案を **Pull Request** として作ります。

1. 無料の **GitHubアプリ**（App Store）を入れる
2. リポジトリの「Pull requests」を開く
3. 変更点（Files changed）を確認し、問題なければ **Merge** → 反映
4. 気に入らなければ Close するだけ

## ④ いますぐ再分析する

- **Discordで** `/analyze code:7203`（設定済みなら。`discord-bot/README.md` 参照）
- **GitHubで**：Actions タブ →「Daily Portfolio Notification」→「Run workflow」→ 実行
  （`symbols` に銘柄コードを入れると、その銘柄だけオンデマンド分析）

---

## 補足
- 保有・監視銘柄は Google スプレッドシートを iPhone で編集すれば反映されます（数量を空欄にすると「監視銘柄」）。
- 通知先の Discord は iPhone アプリで受け取れます。
- ここでの操作はすべて GitHub / Google / Discord / Cloudflare の無料枠で完結します。
