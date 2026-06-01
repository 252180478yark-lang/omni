from datetime import date
from pathlib import Path

from app.services.catalog_loader import CatalogLoader, render_params, build_render_context

FIXT = Path(__file__).parent / "fixtures" / "catalog_yuntu_sample.json"
CONTEXT = {"yuntu": {"aadvid": "1805203190148185", "brand_id": "11835330", "industry_id": "14"}}


def _loader():
    return CatalogLoader.from_files({"yuntu": FIXT}, CONTEXT)


def test_get_by_key():
    ld = _loader()
    e = ld.get("yuntu.5a.asset_structure")
    assert e is not None and e["method"] == "GET"
    assert ld.get("nope.nope") is None


def test_search_by_platform_and_query():
    ld = _loader()
    assert {e["key"] for e in ld.search(platform="yuntu")} == {
        "yuntu.5a.asset_structure", "yuntu.gta.profile"
    }
    hits = ld.search(platform="yuntu", query="GTA")  # 命中 alias / category / key
    assert [e["key"] for e in hits] == ["yuntu.gta.profile"]


def test_search_verified_only():
    ld = _loader()
    hits = ld.search(platform="yuntu", verified_only=True)
    assert [e["key"] for e in hits] == ["yuntu.5a.asset_structure"]


def test_build_render_context_dates():
    ctx = build_render_context({"aadvid": "X"}, today=date(2026, 6, 1))
    assert ctx["today_yyyymmdd"] == "20260601"
    assert ctx["today_iso"] == "2026-06-01"
    assert ctx["this_month"] == "2026-06"
    assert ctx["aadvid"] == "X"


def test_render_params_fills_templates_and_overrides():
    ctx = build_render_context(CONTEXT["yuntu"], today=date(2026, 6, 1))
    params = {"audience_end_date": "{today_yyyymmdd}", "aadvid": "{aadvid}"}
    out = render_params(params, ctx, overrides={"audience_end_date": "20260520"})
    assert out == {"audience_end_date": "20260520", "aadvid": "1805203190148185"}


def test_render_params_unknown_placeholder_left_verbatim():
    ctx = build_render_context({}, today=date(2026, 6, 1))
    out = render_params({"x": "{not_a_key}"}, ctx, overrides=None)
    assert out == {"x": "{not_a_key}"}
