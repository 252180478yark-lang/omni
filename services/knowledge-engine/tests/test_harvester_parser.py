"""Unit tests for the Feishu block parser — no database required."""
import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.services.harvester import (
    parse_feishu_document,
    _blocks_to_md,
    _get_text,
    _cell_to_text,
    _parse_single_article_url,
    _ssr_raw_content_is_placeholder,
    _article_browse_url,
    _lark_embed_urls,
)


def _make_text_block(text_str: str, btype: str = "text", children=None, **extra):
    bd = {
        "type": btype,
        "text": {"initialAttributedTexts": {"text": {"0": text_str}}},
        "children": children or [],
    }
    bd.update(extra)
    return bd


def build_test_document():
    bmap = {
        "page1": {"data": {
            "type": "page",
            "text": {"initialAttributedTexts": {"text": {"0": "Test Document Title"}}},
            "children": ["h1", "text1", "bullet1", "table1", "callout1",
                         "code1", "grid1", "divider1", "todo1"],
        }},
        "h1": {"data": _make_text_block("Chapter 1 Overview", btype="heading1")},
        "text1": {"data": {
            "type": "text",
            "text": {"initialAttributedTexts": {"text": {"0": "Part A ", "1": "Part B ", "2": "Part C."}}},
            "children": [],
        }},
        # Bullet list with nested sub-bullet
        "bullet1": {"data": {"type": "bullet", "text": {}, "children": ["bl1", "bl2"]}},
        "bl1": {"data": {
            "type": "text",
            "text": {"initialAttributedTexts": {"text": {"0": "Feature 1: Analytics"}}},
            "children": ["bl_sub"],
        }},
        "bl_sub": {"data": {"type": "bullet", "text": {}, "children": ["bl_sub_item"]}},
        "bl_sub_item": {"data": _make_text_block("Sub feature: Trend charts")},
        "bl2": {"data": _make_text_block("Feature 2: Export")},
        # Table with complex cells
        "table1": {"data": {
            "type": "table", "text": {}, "children": [],
            "rows_id": ["r1", "r2"],
            "columns_id": ["c1", "c2"],
            "cell_set": {
                "r1c1": {"block_id": "cell_r1c1"},
                "r1c2": {"block_id": "cell_r1c2"},
                "r2c1": {"block_id": "cell_r2c1"},
                "r2c2": {"block_id": "cell_r2c2"},
            },
        }},
        "cell_r1c1": {"data": {"type": "table_cell", "children": ["ct1"]}},
        "cell_r1c2": {"data": {"type": "table_cell", "children": ["ct2"]}},
        "cell_r2c1": {"data": {"type": "table_cell", "children": ["ct3", "cb1"]}},
        "cell_r2c2": {"data": {"type": "table_cell", "children": ["ct4", "ct5"]}},
        "ct1": {"data": _make_text_block("Metric Name")},
        "ct2": {"data": _make_text_block("Description")},
        "ct3": {"data": _make_text_block("Supply Index")},
        "cb1": {"data": {"type": "bullet", "text": {}, "children": ["cb_i1", "cb_i2"]}},
        "cb_i1": {"data": _make_text_block("High demand low price")},
        "cb_i2": {"data": _make_text_block("Low demand high price")},
        "ct4": {"data": _make_text_block("Category analysis")},
        "ct5": {"data": _make_text_block("Market situation overview")},
        # Callout
        "callout1": {"data": {
            "type": "callout",
            "text": {"initialAttributedTexts": {"text": {"0": "Important Notice"}}},
            "children": ["callout_t1"],
        }},
        "callout_t1": {"data": _make_text_block("Data updates on T+1 cycle")},
        # Code block
        "code1": {"data": {
            "type": "code_block", "text": {},
            "snippet": {"text": "SELECT * FROM metrics"},
            "language": "sql", "children": [],
        }},
        # Grid layout
        "grid1": {"data": {"type": "grid", "text": {}, "children": ["gc1", "gc2"]}},
        "gc1": {"data": {"type": "grid_column", "text": {}, "children": ["gc1t"]}},
        "gc1t": {"data": _make_text_block("Left column content")},
        "gc2": {"data": {"type": "grid_column", "text": {}, "children": ["gc2t"]}},
        "gc2t": {"data": _make_text_block("Right column content")},
        # Divider
        "divider1": {"data": {"type": "divider", "text": {}, "children": []}},
        # Todo
        "todo1": {"data": {
            "type": "todo",
            "text": {"initialAttributedTexts": {"text": {"0": "Finish data integration"}}},
            "checked": True, "children": [],
        }},
    }
    return {"code": 0, "data": {"block_map": bmap}}


def test_full_parse():
    cv = build_test_document()
    result = parse_feishu_document(json.dumps(cv))
    assert result is not None, "parse_feishu_document returned None"

    md = result["markdown"]
    print(f"Title: {result['title']}")
    print(f"Block count: {result['block_count']}")
    print(f"Text length: {len(result['text'])} chars")
    print(f"Markdown length: {len(md)} chars")
    print()
    print("=== MARKDOWN OUTPUT ===")
    print(md)
    print()

    checks = [
        ("title", "Test Document Title" in result["title"]),
        ("heading1", "# Chapter 1 Overview" in md),
        ("multi-seg text join", "Part A Part B Part C." in md),
        ("bullet items", "Feature 1: Analytics" in md and "Feature 2: Export" in md),
        ("nested bullet", "Sub feature: Trend charts" in md),
        ("table header", "Metric Name" in md and "Description" in md),
        ("table cell nested bullet", "High demand low price" in md and "Low demand high price" in md),
        ("table multi-text cell", "Category analysis" in md and "Market situation overview" in md),
        ("callout quote", "> Important Notice" in md),
        ("callout content", "Data updates on T+1 cycle" in md),
        ("code_block", "SELECT * FROM metrics" in md),
        ("grid columns", "Left column content" in md and "Right column content" in md),
        ("divider", "---" in md),
        ("todo checked", "- [x] Finish data integration" in md),
    ]

    print("=== TEST RESULTS ===")
    all_pass = True
    for name, ok in checks:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  [{status}] {name}")

    assert all_pass, "Some tests failed"
    print("\nALL TESTS PASSED")


def test_get_text_apool():
    bd = {
        "text": {"initialAttributedTexts": {
            "text": {},
            "aPool": [
                {"insert": "Bold text "},
                {"insert": "normal text"},
            ],
        }},
    }
    result = _get_text(bd)
    assert result == "Bold text normal text", f"aPool extraction failed: {result!r}"
    print("[PASS] _get_text aPool fallback")


def test_get_text_snippet():
    bd = {"snippet": {"text": "console.log('hello')"}}
    result = _get_text(bd)
    assert result == "console.log('hello')", f"snippet extraction failed: {result!r}"
    print("[PASS] _get_text snippet fallback")


def test_get_text_ordered_keys():
    bd = {
        "text": {"initialAttributedTexts": {"text": {"2": "C", "0": "A", "1": "B"}}},
    }
    result = _get_text(bd)
    assert result == "ABC", f"Ordered key extraction failed: {result!r}"
    print("[PASS] _get_text ordered keys")


def test_cell_to_text():
    bmap = {
        "t1": {"data": _make_text_block("Line 1")},
        "t2": {"data": _make_text_block("Line 2")},
        "b1": {"data": {"type": "bullet", "text": {}, "children": ["bi1"]}},
        "bi1": {"data": _make_text_block("Bullet item")},
    }
    result = _cell_to_text(bmap, ["t1", "b1", "t2"])
    assert "Line 1" in result, f"Missing Line 1 in cell: {result!r}"
    assert "Bullet item" in result, f"Missing Bullet item in cell: {result!r}"
    assert "Line 2" in result, f"Missing Line 2 in cell: {result!r}"
    assert "<br>" in result, f"Missing <br> separator: {result!r}"
    print(f"[PASS] _cell_to_text: {result}")


def test_parse_support_single_article_url():
    u = (
        "https://support.oceanengine.com/help/content/206669"
        "?graphId=397&mappingType=2&pageId=221&spaceId=122"
    )
    p = _parse_single_article_url(u)
    assert p is not None
    assert p["mapping_id"] == "206669"
    assert p["graph_id"] == "397"
    assert p["page_id"] == "221"
    assert p["space_id"] == "122"


def test_ssr_placeholder_strings():
    assert _ssr_raw_content_is_placeholder(None)
    assert _ssr_raw_content_is_placeholder("")
    assert _ssr_raw_content_is_placeholder("null")
    assert _ssr_raw_content_is_placeholder("NULL")
    assert not _ssr_raw_content_is_placeholder("<p>hi</p>")


def test_article_browse_url_support_vs_yuntu():
    s = "https://support.oceanengine.com/help/content/206669?graphId=397&mappingType=2"
    assert "support.oceanengine.com/help/content/206669" in _article_browse_url(s, "206669", "397", "221", "122")
    y = "https://yuntu.oceanengine.com/support/content/root?graphId=1"
    assert "yuntu.oceanengine.com/support/content/206669" in _article_browse_url(y, "206669", "397", "221", "122")


def test_lark_embed_urls_wiki_root_prefers_wiki():
    tok = "XXf1ddEiDoyLvzxhEIfcmZGznLe"
    urls = _lark_embed_urls(tok, "feishu_docx_light_import_wiki_root")
    assert urls[0] == f"https://bytedance.larkoffice.com/wiki/{tok}"
    assert f"https://larkoffice.com/wiki/{tok}" in urls
    assert f"https://bytedance.larkoffice.com/docx/{tok}" in urls


def test_lark_embed_urls_plain_docx():
    tok = "abc123"
    urls = _lark_embed_urls(tok, "feishu_docx_new_import")
    assert urls[0] == f"https://bytedance.larkoffice.com/docx/{tok}"
    assert f"https://larkoffice.com/docx/{tok}" in urls
    assert all("/wiki/" not in u for u in urls)


def test_pipe_escape_in_table():
    bmap = {
        "page": {"data": {
            "type": "page", "text": {}, "children": ["tbl"],
        }},
        "tbl": {"data": {
            "type": "table", "text": {}, "children": [],
            "rows_id": ["r1"], "columns_id": ["c1"],
            "cell_set": {"r1c1": {"block_id": "cell1"}},
        }},
        "cell1": {"data": {"type": "table_cell", "children": ["tx"]}},
        "tx": {"data": _make_text_block("A|B|C")},
    }
    lines = _blocks_to_md(bmap, ["page"])
    md = "\n".join(lines)
    assert "A\\|B\\|C" in md, f"Pipe not escaped in table: {md!r}"
    print(f"[PASS] pipe escape in table")


if __name__ == "__main__":
    test_get_text_apool()
    test_get_text_snippet()
    test_get_text_ordered_keys()
    test_cell_to_text()
    test_pipe_escape_in_table()
    print()
    test_full_parse()
