"""最適化AI: 情報量を維持したまま、文字数・トークン数・処理時間を削減する。

最終出力(通知テキスト/Discord embed)に対する仕上げの圧縮パス。
① 同義の冗長表現を短縮(現在かなり割安です→割安) ② 数値で足りる説明を削除
③ 繰り返し禁止(重複行の削除) ④⑤ 同じ理由は1回だけ ⑥ 箇条書き化(。→・)
⑦ 無駄な接続詞削除 ⑧ 推測(あいまいな)表現削除 ⑨ 1項目100字以内を目安
⑩ 可能なら20%以上削減、無理ならそのまま。

重要: 分析品質は絶対に落とさない。数値・★評価・誠実ラベル(推定/検証/需給★/モデル/
留意 等)は削らない。ここで消すのは「意味を持たない飾り言葉」だけ。
"""

from __future__ import annotations

import re

# 自前テンプレの冗長句 → 簡潔形(意味は保持)。
SET_PHRASES = {
    "保有中で最も優先して追加購入したい銘柄": "最優先で追加購入",
    "追加購入を前向きに検討したい銘柄": "追加購入を検討",
    "保有継続が妥当。無理な追加は不要": "保有継続が妥当・追加不要",
    "今は様子見。次のシグナル待ち": "様子見・次シグナル待ち",
    "利益の一部確定を検討したい局面": "一部利確を検討",
    "売却・撤退を検討したい局面": "売却・撤退を検討",
    "値ごろ感は乏しく押し目待ち": "押し目待ち",
    "52週高値圏(値ごろ感は乏しく押し目待ち)": "52週高値圏・押し目待ち",
    "下降トレンドの安値圏(底打ち未確認)": "安値圏・底打ち未確認",
    "割安に見えるがアナリストは慎重(バリュートラップ警戒)": "バリュートラップ警戒",
    "現在値がアナリスト目標を超過(上値限定)": "アナリスト目標超過・上値限定",
    "決算接近に注意": "決算接近注意",
    "中長期の伸びしろ大": "中長期の伸びしろ大",
    "トレンド継続を想定": "トレンド継続",
    "上値の重い展開を想定": "上値重い",
    "出来高を伴う需給改善中": "需給改善中",
    "売られすぎからの短期反発余地": "短期反発余地",
}

# ① 強調の飾り(意味を変えない)。
INTENSIFIERS = ["かなり", "非常に", "とても", "極めて", "すごく", "大きく"]
# ⑦ 無駄な接続詞。
CONNECTIVES = ["また、", "そして、", "さらに、", "なお、", "加えて、", "そのため、", "したがって、"]
# ⑧ あいまいな推測表現(誠実ラベルの「推定/想定/見込み」は残す。ここは飾りだけ)。
HEDGES = [
    "と思われます", "と思われる", "と考えられます", "と考えられる",
    "かもしれません", "かもしれない", "おそらく", "たぶん", "でしょう",
]


def compress(text: str) -> str:
    """1つの文字列を、意味を保ったまま短縮する。"""
    if not text:
        return text
    for verbose, concise in SET_PHRASES.items():
        text = text.replace(verbose, concise)
    for word in INTENSIFIERS + CONNECTIVES + HEDGES:
        text = text.replace(word, "")
    # ⑥ 文末の句点を除去し、途中の句点は箇条書きの区切り(・)へ。
    text = text.rstrip("。")
    text = text.replace("。", "・")
    # ⑨ 文末の丁寧表現(です/ます)は意味を持たないので落とす。
    text = re.sub(r"(です|ます)$", "", text)
    text = re.sub(r"[ \t　]+", " ", text).strip()
    return text


def _dedup_keep_order(lines: list[str]) -> list[str]:
    """③⑤ すぐ隣の重複行を1回に(空行の連続もまとめる)。

    連続重複のみを対象にする。銘柄カードの見出し(①結論 等)や、別銘柄が偶然同じ理由を
    持つケースは正当な繰り返しなので消さない(全体一致で消すと構造が壊れる)。
    """
    out: list[str] = []
    for line in lines:
        if out and line == out[-1]:
            continue  # 直前と同じ行(重複した理由/空行)は1回だけ
        out.append(line)
    return out


def optimize_lines(lines: list[str]) -> list[str]:
    """テキスト行を圧縮する(各行を短縮→重複除去)。"""
    compressed = [compress(line) for line in lines]
    return _dedup_keep_order(compressed)


def optimize_embeds(embeds: list[dict]) -> list[dict]:
    """Discord embed の description を圧縮する(タイトル・色・数値は保持)。"""
    for embed in embeds:
        desc = embed.get("description")
        if not desc:
            continue
        lines = desc.split("\n")
        embed["description"] = "\n".join(_dedup_keep_order([compress(x) for x in lines]))
    return embeds


def char_count(obj) -> int:
    """文字数を数える(list[str] / list[embed] / str のいずれも可)。"""
    if isinstance(obj, str):
        return len(obj)
    total = 0
    for item in obj:
        if isinstance(item, str):
            total += len(item)
        elif isinstance(item, dict):
            total += len(item.get("title", "")) + len(item.get("description", ""))
    return total


def reduction_pct(before: int, after: int) -> float:
    if before <= 0:
        return 0.0
    return (before - after) / before * 100
