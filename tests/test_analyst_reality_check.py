"""アナリスト合意アンカリング(horizon_model)と割安の現実性チェック(summary)の検証。

ANA(高値圏・アナリスト慎重)は下方修正、中外(安値寄り・アナリスト強気)は維持、を
銘柄名ではなく「入力→妥当な出力」の原則で確かめる。実データ取得はせず namespace で入力する。
"""

from __future__ import annotations

from types import SimpleNamespace

from stock_analyzer.horizon_model import _anchor_to_analysts
from stock_analyzer.summary import _price_position, _valuation_signals


def _ns(**kw):
    base = dict(
        current_price=1000.0,
        target_mean_price=None,
        target_high_price=None,
        target_low_price=None,
        num_analysts=None,
        recommendation_mean=None,
        period_high=None,
        period_low=None,
        sma_long=None,
        eps=None,
        sector="Industrials",
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ---- アナリスト・アンカリング -------------------------------------------------

def test_anchor_pulls_overshoot_toward_analysts():
    # モデルが+38%でもアナリスト平均+7.5%・強気+30%なら、大きく引き戻される
    ns = _ns(target_mean_price=1075.0, target_high_price=1300.0, target_low_price=730.0, num_analysts=12)
    total, anchored, divergence = _anchor_to_analysts(38.0, ns)
    assert anchored is True
    assert 7.5 < total < 38.0  # 平均とモデルの間、かつモデル未満
    assert total < 20  # アナリストに近い側へ強く寄る
    assert divergence > 25


def test_anchor_keeps_model_when_agreeing_with_analysts():
    # モデル+28%がアナリスト平均+31%とほぼ一致 → モデルをほぼ維持
    ns = _ns(target_mean_price=1310.0, target_high_price=1770.0, target_low_price=1080.0, num_analysts=15)
    total, anchored, divergence = _anchor_to_analysts(28.0, ns)
    assert anchored is True
    assert abs(total - 28.0) < 3  # ほぼモデル通り
    assert divergence < 10


def test_anchor_skipped_without_coverage():
    ns = _ns(target_mean_price=1075.0, num_analysts=1)  # カバレッジ不足
    total, anchored, _ = _anchor_to_analysts(38.0, ns)
    assert anchored is False
    assert total == 38.0


# ---- 割安の現実性チェック(バリュエーション・シグナル) ------------------------

def _points(signals):
    return sum(s.points for s in signals)


def test_near_52w_high_and_thin_upside_is_penalized():
    # 高値圏(位置76%)・アナリスト上値わずか(+7.5%)・社内は割安判定 → 減点(バリュートラップ)
    ns = _ns(
        current_price=3164.0,
        target_mean_price=3402.0,
        num_analysts=12,
        recommendation_mean=2.17,
        period_high=3330.0,  # 位置≈78%(高値圏)
        period_low=2570.0,
        eps=321.0,
        sector="Industrials",
    )
    signals = _valuation_signals(ns)
    assert _points(signals) <= -12  # 明確な減点
    assert any("高値圏" in s.reason for s in signals)
    assert any("バリュートラップ" in s.reason for s in signals)


def test_off_high_with_strong_upside_is_rewarded():
    # 高値から下げ・アナリスト上値大(+31%)・強気推奨 → 加点
    ns = _ns(
        current_price=7620.0,
        target_mean_price=10006.0,
        num_analysts=15,
        recommendation_mean=1.93,
        period_high=10700.0,
        period_low=7249.0,
        eps=263.0,
        sector="Healthcare",
    )
    signals = _valuation_signals(ns)
    assert _points(signals) >= 5
    assert not any("高値圏" in s.reason for s in signals)


def test_price_position_helper():
    ns = _ns(current_price=3164.0, period_high=3419.0, period_low=2690.0)
    pos = _price_position(ns)
    assert 0.6 < pos < 0.7
