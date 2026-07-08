from __future__ import annotations

from stock_analyzer import aliases, stability
from stock_analyzer.decision import stars_from_score, star_count


# --- カテゴリ4: スコア安定性 ---
def test_flag_jump_when_fundamentals_unchanged():
    # 総合が20点以上動き、ファンダは不変 → 注意書き
    note = stability.flag_jump(prev_total=60, prev_fund=10, cur_total=85, cur_fund=10)
    assert note is not None and "要目視確認" in note


def test_no_flag_when_fundamentals_moved():
    # ファンダも動いていれば正当な変化 → 注意書きなし
    assert stability.flag_jump(60, 10, 85, 0) is None


def test_no_flag_for_small_move():
    assert stability.flag_jump(60, 10, 70, 10) is None


def test_check_entries_maps_symbols():
    prev = {"7203.T": stability.SubscoreRecord("7203.T", 60, {"fundamental": 10})}
    cur = [stability.SubscoreRecord("7203.T", 85, {"fundamental": 10})]
    alerts = stability.check_entries(cur, prev)
    assert "7203.T" in alerts


def test_log_roundtrip(tmp_path):
    path = tmp_path / "subscore_log.csv"
    recs = [stability.SubscoreRecord("7203.T", 72, {"technical": 15, "fundamental": 8})]
    stability.append_records(path, recs)
    back = stability.read_last_by_symbol(path)
    assert back["7203.T"].total == 72
    assert back["7203.T"].subscores["technical"] == 15


# --- カテゴリ5: スター関数 ---
def test_stars_from_score_never_exceeds_five():
    for s in [0, 19, 20, 40, 79, 80, 99, 100, 120]:
        assert star_count(stars_from_score(s)) <= 5
    assert stars_from_score(100) == "★★★★★"
    assert stars_from_score(0) == "☆☆☆☆☆"
    assert stars_from_score(85) == "★★★★☆"  # floor(85/20)=4


# --- カテゴリ6: エイリアス ---
def test_alias_maps_adr_to_domestic():
    assert aliases.company_key("TM") == aliases.company_key("7203.T")
    assert aliases.is_alias_pair("TM", "7203.T") is True


def test_alias_falls_back_to_name():
    assert aliases.company_key("XXXX", "テスト株式会社") == aliases.company_key("YYYY", "テスト")
