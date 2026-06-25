import re


def normalize_code(value: str | int | None) -> str:
    if value is None:
        return ""
    return re.sub(r"[^0-9A-Za-z]", "", str(value)).upper()


def total_meter_match_key(meter_no: str | int | None) -> str:
    normalized = normalize_code(meter_no)
    if len(normalized) >= 12:
        return normalized[2:]
    return normalized


def scanned_barcode_match_key(barcode: str | int | None) -> str:
    normalized = normalize_code(barcode)
    if len(normalized) >= 22:
        return normalized[11:-1]
    if len(normalized) >= 13:
        return normalized[:-1]
    return total_meter_match_key(normalized)

