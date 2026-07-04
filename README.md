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

## 今後のロードマップ

- [ ] 毎日決まった時間に自動実行するスケジューラ
- [ ] LINE Notify / LINE Messaging APIによる通知連携
- [ ] 保有銘柄の入力をCSVからWeb UIまたは証券口座連携に置き換え
