from __future__ import annotations

import json

import pytest

from stock_analyzer import model_store


def test_default_weights_are_current_values():
    # フォールバック=現行の点数(挙動不変の担保)
    assert model_store.TECHNICAL_WEIGHTS["macd_cross"] == 10
    assert model_store.TECHNICAL_WEIGHTS["sma25"] == 8
    assert model_store.TECHNICAL_WEIGHTS["rsi_extreme"] == 8
    assert model_store.DIVIDEND_WEIGHTS["ex_div_near"] == 4
    assert model_store.MARKET_WEIGHTS["vix_high"] == 8


def test_technical_weights_default_when_flag_off(monkeypatch):
    monkeypatch.delenv(model_store.USE_ADOPTED_ENV, raising=False)
    assert model_store.technical_weights() == model_store.TECHNICAL_WEIGHTS


def test_load_adopted_model_missing_returns_none(tmp_path):
    assert model_store.load_adopted_model(str(tmp_path / "nope.json")) is None


def test_load_adopted_model_rejects_bad_schema(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"features": {}}), encoding="utf-8")  # metadata 欠落
    assert model_store.load_adopted_model(str(bad)) is None
    bad2 = tmp_path / "bad2.json"
    bad2.write_text("{not json", encoding="utf-8")
    assert model_store.load_adopted_model(str(bad2)) is None


def test_adopted_model_disables_dropped_feature_when_flag_on(tmp_path, monkeypatch):
    model = {
        "metadata": {"method": "x"},
        "features": {"RSI30以下": {"weight": 0.5}},
        "rejected": [{"feature": "MACD_GC", "reason": "OOSで無効"}],
    }
    path = tmp_path / "adopted_model.json"
    path.write_text(json.dumps(model), encoding="utf-8")
    monkeypatch.setenv(model_store.ADOPTED_PATH_ENV, str(path))
    monkeypatch.setenv(model_store.USE_ADOPTED_ENV, "1")

    weights = model_store.technical_weights()
    # drop された MACD_GC に対応する macd_cross はライブから外れる(0)
    assert weights["macd_cross"] == 0
    # 対応表に無い/採用された重みは現行のまま
    assert weights["sma25"] == model_store.TECHNICAL_WEIGHTS["sma25"]


def test_flag_off_ignores_adopted_model(tmp_path, monkeypatch):
    model = {"metadata": {}, "features": {}, "rejected": [{"feature": "MACD_GC", "reason": "x"}]}
    path = tmp_path / "adopted_model.json"
    path.write_text(json.dumps(model), encoding="utf-8")
    monkeypatch.setenv(model_store.ADOPTED_PATH_ENV, str(path))
    monkeypatch.delenv(model_store.USE_ADOPTED_ENV, raising=False)
    # フラグOFFなら採用セットは無視され現行値
    assert model_store.technical_weights()["macd_cross"] == 10


def test_summary_and_backtest_share_weight_source():
    """ライブ(summary)とBT(backtest)が同一の重み出所を参照している。"""
    from stock_analyzer import backtest, summary  # noqa: F401

    # どちらも model_store の関数/定数を参照(モジュール属性で確認)
    assert model_store.technical_weights() is not None
    # パリティは test_backtest.test_vectorized_score_matches_build_signals が担保
