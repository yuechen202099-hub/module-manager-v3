from __future__ import annotations

import hashlib
import mimetypes
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlparse
from uuid import uuid4

from app.core.config import settings


ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MAX_REASONABLE_IMAGE_BYTES = 80 * 1024 * 1024


def static_upload_root() -> Path:
    return Path(__file__).resolve().parents[1] / "static" / "uploads"


def active_storage_backend() -> str:
    backend = (settings.storage_backend or "local").strip().lower()
    return "oss" if backend == "oss" else "local"


def sanitize_part(value: str, fallback: str = "item") -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(value or "").strip())
    safe = "-".join(part for part in safe.split("-") if part)
    return safe[:80] or fallback


def normalize_suffix(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower() or ".jpg"
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise ValueError(f"Unsupported image type: {filename}")
    return suffix


def validate_image_content(content: bytes, content_type: str = "", source: str = "image") -> None:
    if not content:
        raise ValueError(f"{source} is empty")
    if len(content) > MAX_REASONABLE_IMAGE_BYTES:
        raise ValueError(f"{source} is too large")

    content_type = str(content_type or "").split(";", 1)[0].strip().lower()
    if content_type and not content_type.startswith("image/") and content_type != "application/octet-stream":
        raise ValueError(f"{source} is not an image response: {content_type}")

    if content.startswith(b"\xff\xd8"):
        if not content.rstrip().endswith(b"\xff\xd9"):
            raise ValueError(f"{source} jpeg is incomplete")
        return
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        if b"IEND" not in content[-32:]:
            raise ValueError(f"{source} png is incomplete")
        return
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return
    if content.startswith(b"BM"):
        return
    if content.startswith((b"GIF87a", b"GIF89a")):
        return

    if content_type.startswith("image/"):
        return
    raise ValueError(f"{source} has unsupported image bytes")


def local_public_url(storage_key: str) -> str:
    return f"/static/uploads/{storage_key.lstrip('/')}"


def oss_bucket_name() -> str:
    return settings.oss_bucket.strip()


def normalize_oss_endpoint(endpoint: str) -> str:
    value = str(endpoint or "").strip()
    if value and "://" not in value:
        return f"https://{value}"
    return value


def oss_public_endpoint() -> str:
    return normalize_oss_endpoint(settings.oss_endpoint)


def oss_server_endpoint() -> str:
    return normalize_oss_endpoint(settings.oss_internal_endpoint or settings.oss_endpoint)


def oss_object_key(scope: str, filename: str, content_sha256: str, team_id: str = "", group_id: str = "", key_hint: str = "") -> str:
    prefix = settings.oss_prefix.strip().strip("/") or "module-manager-v2"
    suffix = normalize_suffix(filename)
    # OSS objects are content-addressed so repeated imports of the same image do
    # not create duplicate objects even when the source URL changes.
    digest = content_sha256.strip().lower()
    parts = [prefix, sanitize_part(team_id, "default-team"), "photos", digest[:2] or "xx", f"{digest}{suffix}"]
    return "/".join(parts)


def require_oss_client(endpoint: str = ""):
    endpoint_value = normalize_oss_endpoint(endpoint) or oss_server_endpoint()
    missing = [
        name
        for name, value in {
            "OSS_ENDPOINT/OSS_INTERNAL_ENDPOINT": endpoint_value,
            "OSS_BUCKET": settings.oss_bucket,
            "OSS_ACCESS_KEY_ID": settings.oss_access_key_id,
            "OSS_ACCESS_KEY_SECRET": settings.oss_access_key_secret,
        }.items()
        if not str(value or "").strip()
    ]
    if missing:
        raise RuntimeError(f"OSS storage is enabled but missing config: {', '.join(missing)}")
    try:
        import oss2
    except ImportError as exc:
        raise RuntimeError("OSS storage requires the oss2 Python package") from exc
    auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
    return oss2.Bucket(auth, endpoint_value, settings.oss_bucket)


def save_image_bytes(
    *,
    scope: str,
    filename: str,
    content: bytes,
    content_type: str = "",
    team_id: str = "",
    group_id: str = "",
    key_hint: str = "",
) -> dict[str, Any]:
    if not content:
        raise ValueError("Uploaded image is empty")
    suffix = normalize_suffix(filename)
    sha256 = hashlib.sha256(content).hexdigest()
    content_type = content_type or mimetypes.types_map.get(suffix, "application/octet-stream")
    scope = sanitize_part(scope, "uploads")
    key_hint = sanitize_part(key_hint, "") if key_hint else ""
    backend = active_storage_backend()

    if backend == "oss":
        key = oss_object_key(scope, filename, sha256, team_id=team_id, group_id=group_id, key_hint=key_hint)
        bucket = require_oss_client()
        headers = {"Content-Type": content_type}
        bucket.put_object(key, content, headers=headers)
        image_url = f"oss://{oss_bucket_name()}/{key}"
        return {
            "url": image_url,
            "sha256": sha256,
            "storage_type": "oss",
            "storage_key": key,
            "storage_bucket": oss_bucket_name(),
            "storage_source": f"{scope}-oss-upload",
            "content_type": content_type,
        }

    filename_part = key_hint or f"{uuid4().hex}-{sha256[:16]}"
    target_name = f"{filename_part}-{sha256[:16]}{suffix}" if key_hint else f"{filename_part}{suffix}"
    target_dir = static_upload_root() / scope
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / target_name
    if not target.exists():
        target.write_bytes(content)
    storage_key = f"{scope}/{target.name}"
    return {
        "url": local_public_url(storage_key),
        "sha256": sha256,
        "storage_type": "local_upload",
        "storage_key": storage_key,
        "storage_bucket": "",
        "storage_source": f"{scope}-local-upload",
        "content_type": content_type,
    }


def parse_oss_image_url(image_url: str) -> tuple[str, str]:
    parsed = urlparse(str(image_url or ""))
    if parsed.scheme != "oss":
        return "", ""
    return parsed.netloc, parsed.path.lstrip("/")


def sign_oss_url(storage_key: str, process: str = "") -> str:
    if not storage_key:
        return ""
    process = str(process or "").strip()
    public_base = settings.oss_public_base_url.strip().rstrip("/")
    if public_base:
        url = f"{public_base}/{quote(storage_key, safe='/')}"
        if process:
            return f"{url}?{urlencode({'x-oss-process': process}, safe=',/')}"
        return url
    bucket = require_oss_client(oss_public_endpoint())
    params = {"x-oss-process": process} if process else None
    return bucket.sign_url(
        "GET",
        storage_key,
        settings.oss_signed_url_expire_seconds,
        params=params,
        slash_safe=True,
    )


def sign_oss_server_url(storage_key: str, process: str = "") -> str:
    if not storage_key:
        return ""
    bucket = require_oss_client()
    params = {"x-oss-process": str(process or "").strip()} if process else None
    return bucket.sign_url(
        "GET",
        storage_key,
        settings.oss_signed_url_expire_seconds,
        params=params,
        slash_safe=True,
    )


def unresolved_oss_reference(photo: dict[str, Any], storage_key: str = "") -> str:
    image_url = str(photo.get("image_url") or "").strip()
    if image_url.startswith("oss://"):
        return image_url
    key = storage_key or str(photo.get("storage_key") or "").strip()
    bucket = str(photo.get("storage_bucket") or settings.oss_bucket or "").strip()
    if bucket and key:
        return f"oss://{bucket}/{key}"
    return image_url


def resolve_oss_processed_url(photo: dict[str, Any], process: str) -> str:
    storage_type = str(photo.get("storage_type") or "").strip()
    storage_key = str(photo.get("storage_key") or "").strip()
    image_url = str(photo.get("image_url") or "").strip()

    if storage_type == "oss":
        key = storage_key or parse_oss_image_url(image_url)[1]
        try:
            return sign_oss_url(key, process)
        except RuntimeError:
            return unresolved_oss_reference(photo, key)
    if image_url.startswith("oss://"):
        _, key = parse_oss_image_url(image_url)
        key = storage_key or key
        try:
            return sign_oss_url(key, process)
        except RuntimeError:
            return unresolved_oss_reference(photo, key)
    return resolve_photo_image_url(photo)


def resolve_photo_image_url(photo: dict[str, Any]) -> str:
    storage_type = str(photo.get("storage_type") or "").strip()
    storage_key = str(photo.get("storage_key") or "").strip()
    image_url = str(photo.get("image_url") or "").strip()

    if storage_type == "oss":
        key = storage_key or parse_oss_image_url(image_url)[1]
        try:
            return sign_oss_url(key)
        except RuntimeError:
            return unresolved_oss_reference(photo, key)
    if image_url.startswith("oss://"):
        _, key = parse_oss_image_url(image_url)
        key = storage_key or key
        try:
            return sign_oss_url(key)
        except RuntimeError:
            return unresolved_oss_reference(photo, key)
    if storage_type == "local_upload" and storage_key and not image_url.startswith("/static/uploads/"):
        return local_public_url(storage_key)
    return image_url


def resolve_photo_thumbnail_url(photo: dict[str, Any]) -> str:
    return resolve_oss_processed_url(photo, settings.oss_thumbnail_process)


def resolve_photo_preview_url(photo: dict[str, Any]) -> str:
    return resolve_oss_processed_url(photo, settings.oss_preview_process)


def resolve_photo_for_response(photo: dict[str, Any]) -> dict[str, Any]:
    item = deepcopy(photo)
    canonical_url = str(item.get("image_url") or "")
    item["canonical_image_url"] = canonical_url
    item["module_asset_no"] = item.get("module_asset_no") or item.get("asset_no") or ""
    item["collector"] = item.get("collector") or ""
    item["creator"] = item.get("creator") or ""
    resolved_url = resolve_photo_image_url(item)
    thumbnail_url = resolve_photo_thumbnail_url(item)
    preview_url = resolve_photo_preview_url(item)
    if resolved_url:
        item["image_url"] = resolved_url
    fallback_url = resolved_url or canonical_url or str(item.get("url") or "")
    item["thumbnail_url"] = thumbnail_url or fallback_url
    item["preview_url"] = preview_url or fallback_url
    return item


def resolve_group_for_response(group: dict[str, Any] | None) -> dict[str, Any] | None:
    if group is None:
        return None
    item = deepcopy(group)
    if "photos" in item:
        item["photos"] = [resolve_photo_for_response(photo) for photo in item.get("photos", [])]
    return item


def resolve_group_collection_for_response(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload)
    if isinstance(result.get("items"), list):
        result["items"] = [resolve_group_for_response(item) if isinstance(item, dict) else item for item in result["items"]]
    return result


def resolve_result_for_response(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload)
    if isinstance(result.get("group"), dict):
        result["group"] = resolve_group_for_response(result["group"])
    if isinstance(result.get("deleted_photo"), dict):
        result["deleted_photo"] = resolve_photo_for_response(result["deleted_photo"])
    return result


def resolve_manifest_for_response(manifest: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(manifest)
    for group in result.get("groups", []):
        if isinstance(group, dict):
            group["photos"] = [resolve_photo_for_response(photo) for photo in group.get("photos", [])]
    return result
