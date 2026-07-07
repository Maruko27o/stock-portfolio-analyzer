from __future__ import annotations

import json

import pytest

from stock_analyzer import config, summary


def test_apply_tuning_overrides_scalar_and_partial_dict(tmp_path):
    original_cap = config.ALLOC_NAME_CAP
    original_caps = dict(config.CATEGORY_CAPS)
    try:
        path = tmp_path / "tuning.json"
        path.write_text(
            json.dumps({"ALLOC_NAME_CAP": 0.25, "CATEGORY_CAPS": {"valuation": 25}}),
            encoding="utf-8",
        )
        applied = config.apply_tuning_overrides(path)
        assert applied == {"ALLOC_NAME_CAP": 0.25, "CATEGORY_CAPS": {"valuation": 25}}
        assert config.ALLOC_NAME_CAP == 0.25
        assert config.CATEGORY_CAPS["valuation"] == 25  # 部分上書き
        assert config.CATEGORY_CAPS["technical"] == original_caps["technical"]  # 他は保持
    finally:
        config.ALLOC_NAME_CAP = original_cap
        config.CATEGORY_CAPS.clear()
        config.CATEGORY_CAPS.update(original_caps)


def test_apply_tuning_overrides_ignores_unknown_and_bad(tmp_path):
    original_cap = config.ALLOC_NAME_CAP
    # 未知キーは無視
    p1 = tmp_path / "a.json"
    p1.write_text(json.dumps({"UNKNOWN_KEY": 1, "__import__": "x"}), encoding="utf-8")
    assert config.apply_tuning_overrides(p1) == {}
    # 壊れたJSONでも例外にならず既定値のまま
    p2 = tmp_path / "b.json"
    p2.write_text("{not valid json", encoding="utf-8")
    assert config.apply_tuning_overrides(p2) == {}
    # 存在しないファイル
    assert config.apply_tuning_overrides(tmp_path / "nope.json") == {}
    assert config.ALLOC_NAME_CAP == original_cap


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
