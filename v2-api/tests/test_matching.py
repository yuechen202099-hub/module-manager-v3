import pytest

from app.services.matching import (
    build_long_scan_match_key,
    build_total_catalog_match_key,
    is_match,
    normalize_meter_text,
)


def test_normalize_meter_text_strips_all_whitespace() -> None:
    assert normalize_meter_text("  AB 12\t34\n ") == "AB1234"


def test_long_scan_match_key_removes_first_11_and_last_1_chars() -> None:
    assert build_long_scan_match_key("ABCDEFGHIJK123456789X") == "123456789"


def test_total_catalog_match_key_removes_first_2_chars() -> None:
    assert build_total_catalog_match_key("ZZ123456789") == "123456789"


def test_scan_and_total_catalog_keys_match() -> None:
    assert is_match("ABCDEFGHIJK123456789X", "ZZ123456789")


@pytest.mark.parametrize("value", ["", "123456789012"])
def test_long_scan_match_key_requires_enough_characters(value: str) -> None:
    with pytest.raises(ValueError):
        build_long_scan_match_key(value)


@pytest.mark.parametrize("value", ["", "12"])
def test_total_catalog_match_key_requires_enough_characters(value: str) -> None:
    with pytest.raises(ValueError):
        build_total_catalog_match_key(value)

