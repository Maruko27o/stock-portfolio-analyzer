# stock-portfolio-analyzer

保有銘柄のポートフォリオを分析し、テクニカル・ファンダメンタル両面から評価スコアと売買の目安を表示するツールです。

## 現在のフェーズ

**フェーズ1: MVP**
- 保有銘柄をCSVで管理(銘柄コード・数量・平均取得価格)
- 株価データの取得(yfinance)
- テクニカル指標の計算(SMA20 / RSI14)
- RSIに基づく簡易シグナル判定(買い検討 / 売り検討 / 様子見)をコンソールに表示

**フェーズ2: ファンダメンタル指標**
- PER・PBRの取得(yfinance)
- 閾値に基づく割安 / 割高判定をコンソールに表示

**フェーズ3: 総合スコアリング**
- テクニカル(RSI)とファンダメンタル(PER・PBR)を0-100点のスコアに統合
- スコアに基づく総合判定(買い / 売り / 様子見)をコンソールに表示

**フェーズ4・5: 定期実行 + LINE通知**
- GitHub Actionsで毎日決まった時刻(デフォルト: 07:00 JST)に自動実行
- 分析結果をLINE Messaging API(Broadcast API)経由で通知
- LINEのチャネルアクセストークンはGitHub Actionsの Secrets で管理し、コードやログには一切出力しない

**フェーズ6: 保有銘柄の入力をGoogleスプレッドシートに変更**
- 保有銘柄(symbol・quantity・avg_cost)を非公開のGoogleスプレッドシートで管理
- 専用のGoogleサービスアカウントにのみ閲覧権限を付与し、外部には非公開のまま
- スプレッドシートを編集するだけで、次回の自動実行に反映される(CSVやSecretsを直接触る必要がなくなった)

## セットアップ

```bash
pip install -r requirements.txt
```

## 使い方

```bash
python -m stock_analyzer.cli --portfolio portfolio.sample.csv
```

`portfolio.sample.csv` を参考に、自分の保有銘柄を記載したCSVを用意してください。

```csv
symbol,quantity,avg_cost
AAPL,10,150.00
```

## テスト

```bash
python -m pytest
```

## セキュリティ / 秘密情報の取り扱い

- **実際の保有銘柄データはコミットしないでください。** `portfolio.sample.csv` はサンプルのみです。自分の保有銘柄は `portfolio.csv` として作成してください(`.gitignore` で除外済み)。
- **APIキー・トークン(LINE Notifyのトークンなど)はコードに直接書かず、`.env` など `.gitignore` 対象のファイルや環境変数で管理してください。**
- このリポジトリはPublicのため、上記を守らないとコード・データが誰でも閲覧可能な状態で公開されます。

## Googleスプレッドシートの準備(保有銘柄の入力)

1. [Google Cloud Console](https://console.cloud.google.com/) で新規プロジェクトを作成
2. 「APIとサービス」→「ライブラリ」から **Google Sheets API** と **Google Drive API** を有効化
3. 「APIとサービス」→「認証情報」→「認証情報を作成」→「サービスアカウント」を作成(役割は付与不要)
4. 作成したサービスアカウント →「キー」タブ →「鍵を追加」→「新しい鍵を作成」で **JSON** 形式のキーをダウンロード
   - JSON内の `client_email` がサービスアカウントのメールアドレス
5. 保有銘柄用のスプレッドシートを新規作成し、1行目に `symbol,quantity,avg_cost` の見出しを入れて保有銘柄を入力
6. スプレッドシートの「共有」から、手順4のサービスアカウントのメールアドレスを**閲覧者**として追加(これ以外には非公開のまま)
7. スプレッドシートのURL `https://docs.google.com/spreadsheets/d/【ここがID】/edit` からIDを控える

## GitHub Actionsのセットアップ(定期実行 + LINE通知)

以下をリポジトリの Settings → Secrets and variables → Actions → New repository secret から登録してください(値はGitHubの画面上で直接入力し、他の場所に貼り付けないでください)。

| Secret名 | 内容 |
| --- | --- |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Developersで発行したチャネルアクセストークン(長期) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | ダウンロードしたサービスアカウントJSONキーの中身全体 |
| `GOOGLE_SHEET_ID` | 保有銘柄スプレッドシートのID |

登録後は `.github/workflows/daily-report.yml` のcronで指定した時刻に自動実行されます。手動で試したい場合はGitHubの Actions タブから `workflow_dispatch` で即時実行できます。以降、保有銘柄を変更したい場合はスプレッドシートを直接編集するだけで、次回の自動実行に反映されます。

## 今後のロードマップ

- [ ] 保有銘柄の入力を、より使いやすい専用Web UIや証券口座連携に置き換え
