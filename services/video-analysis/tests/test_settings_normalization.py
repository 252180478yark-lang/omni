from app.settings_normalization import normalize_optional_text


def test_normalize_optional_text_treats_null_and_missing_values_as_unset() -> None:
    assert normalize_optional_text(None) == ""
    assert normalize_optional_text({}.get("missing")) == ""


def test_normalize_optional_text_trims_valid_strings() -> None:
    assert normalize_optional_text("  gemini-2.0-flash  ") == "gemini-2.0-flash"
    assert normalize_optional_text("   ") == ""


def test_normalize_optional_text_rejects_non_string_values() -> None:
    assert normalize_optional_text(123) == ""
    assert normalize_optional_text({"model": "gemini"}) == ""
