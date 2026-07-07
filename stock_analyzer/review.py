"""レビューAI: 分析結果の品質を第三者視点で点検し、改善点だけを出す。

分析を鵜呑みにせず、ロジック矛盾・ファンダ/テクニカル評価・リスク・ポートフォリオ整合・
説明性・スコアの妥当性を確認する。各指摘は「なぜ問題か(why)」「どう直すか(fix)」まで示す。
問題が無ければ「改善不要」。

2系統を用意する:
- rule_based_review: ネット/API不要・無料・決定論的。既定でこれを使い通知に載せる。
- llm_review: ANTHROPIC_API_KEY があれば、下の REVIEW_SYSTEM_PROMPT で Claude に依頼する
  (より踏み込んだレビュー。任意・従量課金)。自己改修AI(次段)もこの出力を使う。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from stock_analyzer import config
from stock_analyzer.conclusion import BUY_ACTIONS
from stock_analyzer.decision import SELL_ACTIONS, HoldingDecision

# ユーザー提供のレビュープロンプト(LLM版でそのまま system として使う)。
REVIEW_SYSTEM_PROMPT = """あなたは株式分析システム専用のレビューAIです。
目的は「分析結果の品質向上」であり、分析内容を鵜呑みにしません。
以下の分析結果を第三者のプロ投資家・システムアーキテクト・定量分析者の視点でレビューしてください。
必ず以下を確認します。
■1. ロジック矛盾: 割高なのに強い買いになっていないか / 割安なのに評価が低すぎないか / 期待リターンとRRが一致しているか / スコアと最終判断が一致しているか / 売却理由と買い理由が矛盾していないか
■2. ファンダメンタル: PER PBR ROE EPS 配当 利益成長率 が適切に評価されているか
■3. テクニカル: MACD RSI 移動平均 出来高 ボリンジャー 需給 の評価が過不足ないか
■4. リスク: 決算リスク 市場リスク セクターリスク イベントリスク 信用倍率 貸借倍率 空売り を考慮できているか
■5. ポートフォリオ: 資金配分 セクター偏り NISA優先 利益確定 損切り との整合性
■6. 説明性: 根拠不足 説明不足 推定だけになっている部分 数値根拠不足 を探す
■7. スコア: 100点が出すぎていないか 重み付けが妥当か 期待値が高すぎないか
■出力: 改善点のみ出力する。問題が無ければ「改善不要」のみ返す。曖昧な改善は禁止。必ず「なぜ問題なのか」「どう直すか」まで提案する。"""

# 高スコアが「出すぎ」と見なす基準。
HIGH_SCORE = 95
MAX_HIGH_SCORES = 3
# 期待リターンが「高すぎ」と見なす基準(検証範囲を超える誇大)。
EXPECTED_RETURN_CAP = 40.0


@dataclass
class ReviewFinding:
    category: str  # "1.ロジック矛盾" などの区分
    symbol: str | None  # 対象銘柄(全体の指摘は None)
    issue: str  # 何が問題か
    why: str  # なぜ問題か
    fix: str  # どう直すか


def _long_term(decision: HoldingDecision):
    for h in decision.expected_returns:
        if h.label == "半年〜1年":
            return h
    return None


def _label(decision: HoldingDecision) -> str:
    return f"{decision.symbol} {decision.name}" if decision.name else decision.symbol


def _logic_findings(d: HoldingDecision) -> list[ReviewFinding]:
    out: list[ReviewFinding] = []
    lt = _long_term(d)

    # 割高なのに買い
    if d.discount_pct is not None and d.discount_pct >= 10 and d.action in BUY_ACTIONS:
        out.append(ReviewFinding(
            "1.ロジック矛盾", d.symbol,
            f"割高(適正比{d.discount_pct:+.0f}%)なのに「{d.action}」",
            "割高圏での買い増しは高値掴みのリスク。割安率と買い判断が矛盾している。",
            "買い方向にするなら割高分を相殺する強い成長/モメンタム根拠を明示。無ければ様子見へ格下げ。",
        ))
    # 割安なのに売り
    if d.discount_pct is not None and d.discount_pct <= -15 and d.action in SELL_ACTIONS:
        out.append(ReviewFinding(
            "1.ロジック矛盾", d.symbol,
            f"割安(適正比{d.discount_pct:+.0f}%)なのに「{d.action}」",
            "割安なのに売り。税/権利日など別要因が無ければ評価が低すぎる。",
            "売り理由(業績悪化・需給悪化・税最適化)を明示。無ければ保有以上へ格上げ。",
        ))
    # RRと買い判断
    if d.action in BUY_ACTIONS and d.risk_reward is not None and d.risk_reward < 1.0:
        out.append(ReviewFinding(
            "1.ロジック矛盾", d.symbol,
            f"「{d.action}」なのにRRが{d.risk_reward:.1f}(<1)",
            "上値余地より下値余地が大きい(RR<1)のに買い。期待リターンとRRが不整合。",
            "利確/損切り水準を見直すか、RR<1なら買いを見送り様子見に。",
        ))
    # 期待リターンがマイナスなのに買い
    if lt is not None and lt.pct is not None and lt.pct < 0 and d.action in BUY_ACTIONS:
        out.append(ReviewFinding(
            "1.ロジック矛盾", d.symbol,
            f"半年〜1年の期待{lt.pct:+.0f}%(マイナス)なのに「{d.action}」",
            "期待リターンが負なのに買い。判断根拠が一貫していない。",
            "期待リターンの符号と最終判断を一致させる(負なら保有/様子見以下)。",
        ))
    # スコアと判断
    if d.overall_score >= 85 and d.action in SELL_ACTIONS:
        out.append(ReviewFinding(
            "1.ロジック矛盾", d.symbol,
            f"総合{d.overall_score}点(高)なのに「{d.action}」",
            "高スコアなのに売り。スコアと最終判断が食い違う。",
            "税/リバランス等の売り理由を明示。無ければ判断をスコアに合わせる。",
        ))
    if d.overall_score < 43 and d.action in BUY_ACTIONS:
        out.append(ReviewFinding(
            "1.ロジック矛盾", d.symbol,
            f"総合{d.overall_score}点(低)なのに「{d.action}」",
            "低スコアなのに買い。スコアと判断が不一致。",
            "買い根拠を明示できないなら様子見以下へ。",
        ))
    return out


def _risk_findings(d: HoldingDecision) -> list[ReviewFinding]:
    out: list[ReviewFinding] = []
    if d.earnings_alert and d.action in BUY_ACTIONS:
        out.append(ReviewFinding(
            "4.リスク", d.symbol,
            f"決算まで{d.days_to_earnings}日で「{d.action}」",
            "決算跨ぎは業績サプライズで急変しうる。イベントリスク未考慮の買い。",
            "決算前は数量を抑えるか、決算後の確認まで買いを待つ設計に。",
        ))
    return out


def _explain_findings(d: HoldingDecision) -> list[ReviewFinding]:
    out: list[ReviewFinding] = []
    lt = _long_term(d)
    # 推定だけで確度が低いのに強い買い
    if (
        d.action == "強く買い増し"
        and lt is not None and lt.pct is not None
        and (lt.stars is None or lt.stars.count("★") <= 1)
    ):
        out.append(ReviewFinding(
            "6.説明性", d.symbol,
            f"「強く買い増し」だが半年〜1年の確度が低い({lt.stars or '—'})",
            "確度の低いモデル推定だけで最上位判断。数値根拠が薄い。",
            "検証実績や複数根拠の一致が無いなら判断を1段下げる/確度を明示。",
        ))
    # 割安根拠が無いのに買い
    if d.action in BUY_ACTIONS and d.discount_pct is None and (d.dividend_yield or 0) == 0:
        out.append(ReviewFinding(
            "6.説明性", d.symbol,
            "買い判断だが適正価格・配当の数値根拠が無い",
            "バリュエーション/インカムの裏付け無しの買いは説明不足。",
            "EPS・アナリスト目標・配当のいずれかで数値根拠を補う。",
        ))
    return out


def _portfolio_findings(data) -> list[ReviewFinding]:
    out: list[ReviewFinding] = []
    alloc = getattr(data, "allocation", None)
    if alloc is not None and alloc.sector_breakdown:
        top, weight = max(alloc.sector_breakdown.items(), key=lambda kv: kv[1])
        if weight > config.ALLOC_SECTOR_CAP * 100 + 0.5:
            out.append(ReviewFinding(
                "5.ポートフォリオ", None,
                f"{top}への配分が{weight:.0f}%(上限{config.ALLOC_SECTOR_CAP*100:.0f}%超)",
                "セクター偏りは分散不足。個別/セクター要因で全体が振れやすい。",
                "上限を超えるセクターは比例縮小し、他セクター/現金へ振り分ける。",
            ))
    # NISA売却の優先度
    for d in getattr(data, "decisions", []):
        if getattr(d, "account", None) == "NISA" and d.action in SELL_ACTIONS and d.tax_sell_bias < 0:
            out.append(ReviewFinding(
                "5.ポートフォリオ", d.symbol,
                "NISA(非課税)銘柄に売却提案",
                "NISA枠は再利用できず非課税メリットが大きい。特定口座の利確を優先すべき局面かも。",
                "同等の売り候補が特定口座にあればそちらを優先し、NISAは温存を検討。",
            ))
    return out


def _score_findings(data) -> list[ReviewFinding]:
    out: list[ReviewFinding] = []
    decisions = list(getattr(data, "decisions", []))
    alloc = getattr(data, "allocation", None)
    if alloc is not None:
        decisions = list({id(x): x for x in decisions + list(alloc.ranking)}.values())

    high = [d for d in decisions if d.overall_score >= HIGH_SCORE]
    if len(high) > MAX_HIGH_SCORES:
        out.append(ReviewFinding(
            "7.スコア", None,
            f"総合{HIGH_SCORE}点以上が{len(high)}件(出すぎ)",
            "高スコアが多いと銘柄間の判別力が落ちる(全部『強い買い』は無情報)。",
            "カテゴリ上限/重みを見直し、上位が相対的に際立つ分布へ。tuning.jsonで調整可。",
        ))
    for d in decisions:
        lt = _long_term(d)
        if lt is not None and lt.pct is not None and lt.pct > EXPECTED_RETURN_CAP:
            out.append(ReviewFinding(
                "7.スコア", d.symbol,
                f"半年〜1年の期待+{lt.pct:.0f}%が高すぎ(>{EXPECTED_RETURN_CAP:.0f}%)",
                "検証範囲を超える誇大な期待値。アナリスト目標を超過している可能性。",
                "アナリスト目標でのアンカリング上限を強める(horizon_model)/tuningで抑制。",
            ))
    return out


def rule_based_review(data) -> list[ReviewFinding]:
    """ReportData を決定論的に点検して改善点を返す(無料・API不要)。"""
    findings: list[ReviewFinding] = []
    for d in getattr(data, "decisions", []):
        findings.extend(_logic_findings(d))
        findings.extend(_risk_findings(d))
        findings.extend(_explain_findings(d))
    # 候補(スイング)側もロジック矛盾だけは見る
    alloc = getattr(data, "allocation", None)
    if alloc is not None:
        held_ids = {id(d) for d in getattr(data, "decisions", [])}
        for d in alloc.ranking:
            if id(d) not in held_ids and d.is_candidate:
                findings.extend(_logic_findings(d))
    findings.extend(_portfolio_findings(data))
    findings.extend(_score_findings(data))
    return findings


def format_review_lines(findings: list[ReviewFinding]) -> list[str]:
    """CLI/テキスト用にレビュー結果を整形する。"""
    if not findings:
        return ["🔍 レビュー(自己点検)", "改善不要"]
    lines = ["🔍 レビュー(自己点検)"]
    for f in findings:
        head = f"[{f.category}]" + (f" {f.symbol}" if f.symbol else "")
        lines.append(f"・{head} {f.issue}")
        lines.append(f"    なぜ: {f.why}")
        lines.append(f"    直し方: {f.fix}")
    return lines


# ---------------------------------------------------------------------------
# LLM 版(任意): ANTHROPIC_API_KEY があれば Claude に上のプロンプトでレビューさせる。
# ---------------------------------------------------------------------------
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
REVIEW_MODEL = "claude-sonnet-5"


def llm_review(analysis_text: str, api_key: str | None = None, model: str = REVIEW_MODEL) -> str | None:
    """Claude にレビューを依頼して本文を返す。キーが無い/失敗時は None(無料運用を壊さない)。"""
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    import requests

    try:
        res = requests.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 1500,
                "system": REVIEW_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": analysis_text}],
            },
            timeout=60,
        )
        if res.status_code >= 400:
            return None
        payload = res.json()
        parts = payload.get("content", [])
        text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
        return text.strip() or None
    except Exception:
        return None
