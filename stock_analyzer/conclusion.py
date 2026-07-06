"""本日の結論(3行以内)と「今日は何もしない」の能動判定。

毎日のレポートの先頭に置く、行動最優先のサマリー。判断フロー⑦売買優先順位・
⑧「何もしない」が最適かの出力にあたる。decisions(保有+新規候補の判断)、
allocation(資金配分)、rebalance(保有比率の是正)を統合し、
「今日買う/売る/現金比率」を最大3行で提示する。

「何もしない」は消極的な放置ではなく、売買コスト・税・回転率を避ける積極的判断
として扱う。買い増し方向の強いシグナルも、売却すべき保有も、過度な偏りの是正も
無いときに do_nothing=True とする。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from stock_analyzer.allocation import AllocationPlan
from stock_analyzer.decision import SELL_ACTIONS, HoldingDecision
from stock_analyzer.rebalance import RebalancePlan

BUY_ACTIONS = {"強く買い増し", "買い増し"}

# リバランスで「売却」方向かつこの%以上の乖離があれば、是正を今日の行動候補にする。
REBALANCE_SELL_THRESHOLD = 10.0


@dataclass
class ActionItem:
    symbol: str
    name: str | None
    action: str  # 表示するアクション名(買い増し/一部売却/縮小 など)
    reason: str  # 一言の根拠
    is_candidate: bool = False


@dataclass
class DailyConclusion:
    do_nothing: bool
    headline: list[str]  # 3行以内の結論
    buys: list[ActionItem]  # 今日買う(優先度順)
    sells: list[ActionItem]  # 今日売る(優先度順)
    cash_pct: float | None  # 推奨現金比率
    rebalance_moves: list[ActionItem] = field(default_factory=list)  # 比率是正(売買以外の調整)


def _buy_reason(d: HoldingDecision) -> str:
    lt = next((h.pct for h in d.expected_returns if h.label == "半年〜1年"), None)
    bits = [d.overall_stars]
    if d.discount_pct is not None and d.discount_pct <= -10:
        bits.append("割安圏")
    if lt is not None and lt >= 15:
        bits.append(f"中長期+{lt:.0f}%期待")
    return "・".join(bits)


def _sell_reason(d: HoldingDecision) -> str:
    bits = [d.action]
    if d.tax_sell_bias > 0:
        bits.append("税負担軽く売りやすい")
    elif d.tax_sell_bias < 0:
        bits.append("NISA・温存も検討")
    if d.discount_pct is not None and d.discount_pct >= 10:
        bits.append("割高圏")
    return "・".join(bits)


def _sell_priority(d: HoldingDecision) -> tuple[int, int]:
    """売却優先度の並び。税で売りやすい(bias高)ほど先、次にスコアが低いほど先。"""
    return (-d.tax_sell_bias, d.overall_score)


def build_conclusion(
    decisions: list[HoldingDecision],
    allocation: AllocationPlan | None,
    rebalance: RebalancePlan | None,
) -> DailyConclusion:
    """保有・配分・リバランスを統合して本日の結論を組み立てる。"""
    # --- 今日買う: 配分ランキングから買い増し方向の上位(保有+新規候補) ---
    ranking = allocation.ranking if allocation else decisions
    buys = [
        ActionItem(d.symbol, d.name, d.action, _buy_reason(d), d.is_candidate)
        for d in ranking
        if d.action in BUY_ACTIONS
    ][:3]

    # --- 今日売る: 保有のうち売却シグナル ---
    sell_decisions = sorted(
        (d for d in decisions if not d.is_candidate and d.action in SELL_ACTIONS),
        key=_sell_priority,
    )
    sells = [
        ActionItem(d.symbol, d.name, d.action, _sell_reason(d), False) for d in sell_decisions
    ]

    # --- 比率是正: リバランスで大きく縮小推奨の銘柄 ---
    # 買い候補に入っている銘柄(買いシグナルあり)は矛盾するので比率是正から除く。
    # 「新規資金では魅力的だが、既に持ちすぎ」は買い側を優先し、縮小は載せない。
    buy_symbols = {b.symbol for b in buys}
    rebalance_moves: list[ActionItem] = []
    if rebalance is not None:
        for it in rebalance.items:
            if it.symbol in buy_symbols:
                continue
            if it.direction == "売却" and it.diff_pct <= -REBALANCE_SELL_THRESHOLD:
                shares = f"（約{it.approx_shares}株）" if it.approx_shares else ""
                rebalance_moves.append(
                    ActionItem(
                        it.symbol,
                        it.name,
                        "縮小",
                        f"{it.current_pct:.0f}%→{it.target_pct:.0f}%に偏り是正{shares}",
                    )
                )

    cash_pct = allocation.cash_pct if allocation else None

    do_nothing = not buys and not sells and not rebalance_moves

    headline = _build_headline(buys, sells, rebalance_moves, cash_pct, do_nothing)

    return DailyConclusion(
        do_nothing=do_nothing,
        headline=headline,
        buys=buys,
        sells=sells,
        cash_pct=cash_pct,
        rebalance_moves=rebalance_moves,
    )


def _names(items: list[ActionItem]) -> str:
    return "・".join(it.name or it.symbol for it in items)


def _build_headline(
    buys: list[ActionItem],
    sells: list[ActionItem],
    rebalance_moves: list[ActionItem],
    cash_pct: float | None,
    do_nothing: bool,
) -> list[str]:
    if do_nothing:
        cash = f"（現金比率の推奨は {cash_pct:.0f}%）" if cash_pct is not None else ""
        return [
            "本日は「何もしない」が最適。",
            "急いで買う銘柄も、売るべき保有もありません。保有継続でOK。" + cash,
        ]

    lines: list[str] = []
    if buys:
        lines.append(f"買い: {_names(buys)}")
    else:
        lines.append("買い: 新規・買い増しの急ぎはなし")

    sell_names = _names(sells + rebalance_moves)
    if sell_names:
        lines.append(f"売り: {sell_names}")
    else:
        lines.append("売り: 売却すべき保有はなし")

    if cash_pct is not None:
        lines.append(f"現金比率の推奨: {cash_pct:.0f}%")
    return lines[:3]


def format_conclusion_lines(conclusion: DailyConclusion) -> list[str]:
    """CLI/テキスト用に本日の結論を整形する。"""
    lines = ["📌 本日の結論", *conclusion.headline]
    if conclusion.buys:
        lines.append("")
        lines.append("■今日の買い候補")
        for it in conclusion.buys:
            tag = "（新規）" if it.is_candidate else ""
            lines.append(f"・{it.name or it.symbol}{tag} {it.action}（{it.reason}）")
    if conclusion.sells:
        lines.append("")
        lines.append("■今日の売り候補")
        for it in conclusion.sells:
            lines.append(f"・{it.name or it.symbol} {it.action}（{it.reason}）")
    if conclusion.rebalance_moves:
        lines.append("")
        lines.append("■比率の是正")
        for it in conclusion.rebalance_moves:
            lines.append(f"・{it.name or it.symbol} {it.reason}")
    return lines
