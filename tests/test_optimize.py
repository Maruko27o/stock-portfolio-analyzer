from __future__ import annotations

from stock_analyzer.optimize import (
    char_count,
    compress,
    optimize_embeds,
    optimize_lines,
    reduction_pct,
)


def test_compress_removes_intensifier_and_politeness():
    out = compress("現在かなり割安です")
    assert "かなり" not in out and "です" not in out
    assert "割安" in out
    assert len(out) < len("現在かなり割安です")


def test_compress_maps_verbose_template():
    assert compress("保有継続が妥当。無理な追加は不要") == "保有継続が妥当・追加不要"


def test_compress_removes_connectives_and_hedges():
    out = compress("また、上昇すると思われます")
    assert "また、" not in out and "と思われます" not in out


def test_compress_preserves_numbers_and_honesty_labels():
    src = "半年〜1年 +18.5%(推定★★★／モデル推定) ※留意"
    out = compress(src)
    for keep in ["+18.5%", "推定", "★★★", "モデル", "留意"]:
        assert keep in out


def test_compress_bulletizes_sentence_break():
    assert compress("割安圏。決算接近に注意") == "割安圏・決算接近注意"


def test_optimize_lines_dedups_repeated_reasons():
    lines = ["・割安", "・割安", "・増収", ""]
    out = optimize_lines(lines)
    assert out.count("・割安") == 1
    assert "・増収" in out


def test_optimize_embeds_compresses_description():
    embeds = [{"title": "t", "description": "保有継続が妥当。無理な追加は不要\n保有継続が妥当。無理な追加は不要"}]
    out = optimize_embeds(embeds)
    # 重複行が1回になり、冗長表現も短縮される
    assert out[0]["description"] == "保有継続が妥当・追加不要"


def test_char_count_and_reduction():
    before = ["あいうえお", "かきくけこ"]
    after = ["あいうえお"]
    assert char_count(before) == 10
    assert char_count(after) == 5
    assert reduction_pct(char_count(before), char_count(after)) == 50.0
    assert reduction_pct(0, 0) == 0.0


def test_compress_empty_is_safe():
    assert compress("") == ""
    assert compress(None) is None
