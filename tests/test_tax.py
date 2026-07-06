from __future__ import annotations

from stock_analyzer import tax


def test_unrealized_pl_basic():
    assert tax.unrealized_pl_yen(1000.0, 100, 1200.0) == 20000.0
    assert tax.unrealized_pl_yen(1000.0, 100, 800.0) == -20000.0


def test_unrealized_pl_missing_data_returns_none():
    assert tax.unrealized_pl_yen(None, 100, 1200.0) is None
    assert tax.unrealized_pl_yen(1000.0, 0, 1200.0) is None
    assert tax.unrealized_pl_yen(1000.0, 100, None) is None


def test_nisa_hold_note_and_neutral_bias():
    a = tax.assess("NISA", 1000.0, 100, 1200.0, "保有")
    assert a.account == "NISA"
    assert "非課税" in a.note
    assert a.sell_bias == 0
    assert a.tax_if_sold_yen is None  # NISA は課税されない


def test_nisa_sell_is_deferred():
    # NISA の売却は税メリットが無く枠も再利用不可 → 温存(後ろ倒し)
    a = tax.assess("NISA", 1000.0, 100, 1200.0, "売却推奨")
    assert a.sell_bias == -1
    assert "枠" in a.note


def test_tokutei_small_profit_is_easy_to_sell():
    # 特定・含み益が20万円以下 → 売りやすい(bias +1)
    a = tax.assess("特定", 1000.0, 100, 1100.0, "一部売却")  # 利益1万円
    assert a.account == "特定"
    assert a.unrealized_pl_yen == 10000.0
    assert a.tax_if_sold_yen == 10000.0 * tax.TAX_RATE
    assert a.sell_bias == 1


def test_tokutei_large_profit_is_neutral():
    a = tax.assess("特定", 1000.0, 1000, 1500.0, "一部売却")  # 利益50万円
    assert a.unrealized_pl_yen == 500000.0
    assert a.sell_bias == 0
    assert "税負担を考慮" in a.note


def test_tokutei_loss_can_offset_when_selling():
    # 含み損は損益通算に使える。売却シグナル時に bias +1。
    a = tax.assess("特定", 1000.0, 100, 800.0, "売却推奨")
    assert a.unrealized_pl_yen == -20000.0
    assert a.tax_if_sold_yen is None
    assert a.sell_bias == 1
    assert "損益通算" in a.note


def test_tokutei_loss_hold_is_neutral():
    a = tax.assess("特定", 1000.0, 100, 800.0, "保有")
    assert a.sell_bias == 0


def test_unknown_account_treated_as_tokutei():
    a = tax.assess("一般", 1000.0, 100, 1100.0, "保有")
    assert a.account == "特定"
