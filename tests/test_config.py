from __future__ import annotations

import pytest

from stock_analyzer import config, summary


def test_summary_reexports_config_constants():
    """後方互換: summary から従来の名前で参照でき、config と同一オブジェクト。"""
    assert summary.CATEGORY_CAPS is config.CATEGORY_CAPS
    assert summary.SECTOR_PER_THRESHOLD is config.SECTOR_PER_THRESHOLD
    assert summary.SECTOR_PBR_THRESHOLD is config.SECTOR_PBR_THRESHOLD
    assert summary.DEFAULT_PER_THRESHOLD == config.DEFAULT_PER_THRESHOLD
    assert summary.DEFAULT_PBR_THRESHOLD == config.DEFAULT_PBR_THRESHOLD


def test_per_pbr_threshold_helpers():
    assert config.per_threshold("Financial Services") == 10
    assert config.per_threshold("Technology") == 25
    assert config.per_threshold(None) == config.DEFAULT_PER_THRESHOLD
    assert config.per_threshold("未知セクター") == config.DEFAULT_PER_THRESHOLD
    assert config.pbr_threshold("Financial Services") == 0.7
    assert config.pbr_threshold(None) == config.DEFAULT_PBR_THRESHOLD


def test_normalized_weights_drops_news_and_sums_to_one():
    """ニュースはデータ源が無いので除外され、残りが合計1.0へ再正規化される。"""
    w = config.normalized_weights("1週間")
    assert "news" not in w
    assert pytest.approx(sum(w.values()), abs=1e-9) == 1.0
    # 元の比率(テクニカル40 : 需給35 : ファンダ10、newsを除く)が保たれる
    assert w["technical"] == pytest.approx(40 / 85)
    assert w["supply_demand"] == pytest.approx(35 / 85)
    assert w["fundamental"] == pytest.approx(10 / 85)


def test_normalized_weights_long_horizon_fundamental_heavy():
    w = config.normalized_weights("半年〜1年")
    assert pytest.approx(sum(w.values()), abs=1e-9) == 1.0
    # 長期はファンダが最大比重
    assert max(w, key=w.get) == "fundamental"


def test_normalized_weights_unknown_horizon_empty():
    assert config.normalized_weights("存在しない期間") == {}


def test_cash_floor_by_regime_and_vix():
    assert config.cash_floor("上昇", None) == 0.10
    assert config.cash_floor("下落", None) == 0.35
    assert config.cash_floor(None, None) == config.DEFAULT_CASH_FLOOR
    # 高VIXは相場に関わらず現金下限を引き上げる
    assert config.cash_floor("上昇", 32.0) == config.VIX_RISK_OFF_CASH_FLOOR
    # 平時VIXは相場ベースの下限のまま
    assert config.cash_floor("上昇", 15.0) == 0.10
