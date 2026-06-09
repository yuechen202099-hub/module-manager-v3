def normalize_meter_text(value: str) -> str:
    return "".join(str(value).strip().split())


def build_long_scan_match_key(scanned_barcode: str) -> str:
    normalized = normalize_meter_text(scanned_barcode)
    if len(normalized) <= 12:
        raise ValueError("Long scanned barcode must be longer than 12 characters.")
    return normalized[11:-1]


def build_total_catalog_match_key(meter_no: str) -> str:
    normalized = normalize_meter_text(meter_no)
    if len(normalized) <= 2:
        raise ValueError("Total catalog meter number must be longer than 2 characters.")
    return normalized[2:]


def build_stage_catalog_match_key(meter_no: str) -> str:
    return build_total_catalog_match_key(meter_no)


def is_match(scanned_barcode: str, total_catalog_meter_no: str) -> bool:
    return build_long_scan_match_key(scanned_barcode) == build_total_catalog_match_key(total_catalog_meter_no)

