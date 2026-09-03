from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import mimetypes
import os
import socket
import urllib.request
from copy import deepcopy
from datetime import UTC, datetime
from functools import partial
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote, urlencode, urlparse
from uuid import uuid4

from app.core.config import settings


ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MAX_REASONABLE_IMAGE_BYTES = 80 * 1024 * 1024
MAX_STORAGE_CLEANUP_ATTEMPTS = 5


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


def _is_ip_literal(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return True


def is_blocked_remote_image_address(hostname: str) -> bool:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    if getattr(address, "ipv4_mapped", None):
        mapped = address.ipv4_mapped
        return (
            mapped.is_private
            or mapped.is_loopback
            or mapped.is_link_local
            or mapped.is_reserved
            or mapped.is_unspecified
            or mapped.is_multicast
        )
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def resolve_remote_image_host_addresses(hostname: str) -> list[str]:
    try:
        results = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Photo proxy host is not allowed") from exc
    addresses: set[str] = set()
    for result in results:
        sockaddr = result[4]
        if sockaddr:
            addresses.add(str(sockaddr[0]))
    if not addresses:
        raise ValueError("Photo proxy host is not allowed")
    return sorted(addresses)


def validate_remote_image_url(
    url: str,
    *,
    allowed_hosts: Iterable[str] | None = None,
    app_env: str | None = None,
    resolver: Callable[[str], list[str]] | None = None,
) -> tuple[str, ...]:
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Invalid image URL")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or is_blocked_remote_image_address(hostname):
        raise ValueError("Photo proxy host is not allowed")
    allowed = {host.lower().rstrip(".") for host in (settings.photo_proxy_hosts if allowed_hosts is None else allowed_hosts)}
    if allowed and hostname not in allowed:
        raise ValueError("Photo proxy host is not allowed")
    current_env = (settings.app_env if app_env is None else app_env).lower()
    if not allowed and current_env in {"prod", "production"}:
        raise ValueError("Photo proxy host is not allowed")
    resolve = resolver or resolve_remote_image_host_addresses
    resolved_addresses = [hostname] if _is_ip_literal(hostname) else resolve(hostname)
    validated_addresses: list[str] = []
    for raw_address in resolved_addresses:
        try:
            address = ipaddress.ip_address(str(raw_address)).compressed
        except ValueError as exc:
            raise ValueError("Photo proxy host is not allowed") from exc
        if is_blocked_remote_image_address(address):
            raise ValueError("Photo proxy host is not allowed")
        if address not in validated_addresses:
            validated_addresses.append(address)
    if not validated_addresses:
        raise ValueError("Photo proxy host is not allowed")
    return tuple(validated_addresses)


class _PinnedConnectionMixin:
    _pinned_addresses: tuple[str, ...]

    def _connect_to_pinned_address(self):  # noqa: ANN202
        last_error: OSError | None = None
        for address in self._pinned_addresses:
            try:
                sock = self._create_connection(
                    (address, self.port),
                    self.timeout,
                    self.source_address,
                )
                peer_address = str(sock.getpeername()[0])
                if (
                    is_blocked_remote_image_address(peer_address)
                    or ipaddress.ip_address(peer_address) != ipaddress.ip_address(address)
                ):
                    sock.close()
                    raise OSError("Remote image peer address changed")
                return sock
            except OSError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise OSError("Remote image host has no validated address")


class _PinnedHTTPConnection(_PinnedConnectionMixin, http.client.HTTPConnection):
    def __init__(self, host: str, *, pinned_addresses: tuple[str, ...], **kwargs: Any) -> None:
        self._pinned_addresses = pinned_addresses
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        self.sock = self._connect_to_pinned_address()
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(_PinnedConnectionMixin, http.client.HTTPSConnection):
    def __init__(self, host: str, *, pinned_addresses: tuple[str, ...], **kwargs: Any) -> None:
        self._pinned_addresses = pinned_addresses
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        self.sock = self._connect_to_pinned_address()
        server_hostname = self.host
        if self._tunnel_host:
            self._tunnel()
            server_hostname = self._tunnel_host
        self.sock = self._context.wrap_socket(self.sock, server_hostname=server_hostname)


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, pinned_addresses: tuple[str, ...]) -> None:
        super().__init__()
        self._pinned_addresses = pinned_addresses

    def http_open(self, request):  # noqa: ANN001, ANN201
        connection = partial(_PinnedHTTPConnection, pinned_addresses=self._pinned_addresses)
        return self.do_open(connection, request)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, pinned_addresses: tuple[str, ...]) -> None:
        super().__init__()
        self._pinned_addresses = pinned_addresses

    def https_open(self, request):  # noqa: ANN001, ANN201
        connection = partial(_PinnedHTTPSConnection, pinned_addresses=self._pinned_addresses)
        return self.do_open(
            connection,
            request,
            context=self._context,
        )


class _NoRemoteImageRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def open_validated_remote_image_url(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int | float = 30,
    allowed_hosts: Iterable[str] | None = None,
    app_env: str | None = None,
    resolver: Callable[[str], list[str]] | None = None,
):  # noqa: ANN201
    pinned_addresses = validate_remote_image_url(
        url,
        allowed_hosts=allowed_hosts,
        app_env=app_env,
        resolver=resolver,
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRemoteImageRedirectHandler(),
        _PinnedHTTPHandler(pinned_addresses),
        _PinnedHTTPSHandler(pinned_addresses),
    )
    request = urllib.request.Request(url, headers=headers or {})
    return opener.open(request, timeout=timeout)


def validate_image_content(content: bytes, content_type: str = "", source: str = "image") -> None:
    if not content:
        raise ValueError(f"{source} is empty")
    if len(content) > MAX_REASONABLE_IMAGE_BYTES:
        raise ValueError(f"{source} is too large")

    content_type = str(content_type or "").split(";", 1)[0].strip().lower()
    if content_type and not content_type.startswith("image/") and content_type != "application/octet-stream":
        raise ValueError(f"{source} is not an image response: {content_type}")

    try:
        from PIL import Image

        with Image.open(BytesIO(content)) as image:
            image.verify()
    except Exception as exc:
        raise ValueError(f"{source} has unsupported image bytes") from exc

    if content.startswith(b"\xff\xd8"):
        if not content.rstrip().endswith(b"\xff\xd9"):
            if b"\xff\xd9" not in content:
                raise ValueError(f"{source} jpeg is incomplete")
            try:
                with Image.open(BytesIO(content)) as image:
                    image.load()
            except Exception as exc:
                raise ValueError(f"{source} jpeg is incomplete") from exc
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


def oss_server_endpoint(*, require_internal: bool = False) -> str:
    if require_internal:
        return normalize_oss_endpoint(settings.oss_internal_endpoint)
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
    cleanup_safe: bool = False,
) -> dict[str, Any]:
    if not content:
        raise ValueError("Uploaded image is empty")
    suffix = normalize_suffix(filename)
    content_type = content_type or mimetypes.types_map.get(suffix, "application/octet-stream")
    validate_image_content(content, content_type, filename or "Uploaded image")
    sha256 = hashlib.sha256(content).hexdigest()
    scope = sanitize_part(scope, "uploads")
    key_hint = sanitize_part(key_hint, "") if key_hint else ""
    backend = active_storage_backend()

    if backend == "oss":
        if cleanup_safe:
            prefix = settings.oss_prefix.strip().strip("/") or "module-manager-v2"
            unique_name = key_hint or uuid4().hex
            key = "/".join(
                [
                    prefix,
                    sanitize_part(team_id, "default-team"),
                    "photos",
                    scope,
                    f"{sanitize_part(unique_name)}-{sha256[:16]}{suffix}",
                ]
            )
        else:
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
            "created_new": bool(cleanup_safe),
        }

    filename_part = key_hint or f"{uuid4().hex}-{sha256[:16]}"
    target_name = f"{filename_part}-{sha256[:16]}{suffix}" if key_hint else f"{filename_part}{suffix}"
    target_dir = static_upload_root() / scope
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / target_name
    created_new = not target.exists()
    if created_new:
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
        "created_new": created_new,
    }


def delete_saved_image(stored: dict[str, Any]) -> bool:
    if not bool(stored.get("created_new")):
        return False
    storage_type = str(stored.get("storage_type") or "").strip().lower()
    storage_key = str(stored.get("storage_key") or "").strip().lstrip("/")
    if not storage_key:
        return False
    if storage_type == "oss":
        bucket_name = str(stored.get("storage_bucket") or "").strip()
        if bucket_name and bucket_name != oss_bucket_name():
            return False
        require_oss_client().delete_object(storage_key)
        return True
    if storage_type == "local_upload":
        root = static_upload_root().resolve()
        target = (root / storage_key).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return False
        target.unlink(missing_ok=True)
        return True
    return False


def storage_cleanup_queue_root() -> Path:
    configured = str(getattr(settings, "storage_cleanup_queue_path", "") or "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "data" / "storage_cleanup_jobs"


def _storage_cleanup_job_id(stored: dict[str, Any]) -> str:
    identity = "|".join(
        (
            str(stored.get("storage_type") or "").strip().lower(),
            str(stored.get("storage_bucket") or "").strip(),
            str(stored.get("storage_key") or "").strip().lstrip("/"),
        )
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _write_storage_cleanup_job(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.{os.getpid()}.{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def enqueue_storage_cleanup_retry(
    stored: dict[str, Any],
    *,
    reason: str,
    error: str,
) -> dict[str, Any] | None:
    storage_type = str(stored.get("storage_type") or "").strip().lower()
    storage_key = str(stored.get("storage_key") or "").strip().lstrip("/")
    if not bool(stored.get("created_new")) or storage_type not in {"oss", "local_upload"} or not storage_key:
        return None
    job_id = _storage_cleanup_job_id(stored)
    path = storage_cleanup_queue_root() / f"{job_id}.json"
    existing: dict[str, Any] = {}
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        existing = {}
    now = datetime.now(UTC).isoformat()
    payload = {
        "id": job_id,
        "status": "pending",
        "attempt_count": int(existing.get("attempt_count") or 0),
        "reason": str(reason or "cleanup_failed")[:128],
        "last_error": str(error or "cleanup failed")[:500],
        "requested_at": existing.get("requested_at") or now,
        "updated_at": now,
        "stored": {
            "url": str(stored.get("url") or ""),
            "storage_type": storage_type,
            "storage_bucket": str(stored.get("storage_bucket") or ""),
            "storage_key": storage_key,
            "created_new": True,
        },
    }
    _write_storage_cleanup_job(path, payload)
    return payload


def process_storage_cleanup_jobs(limit: int = 20) -> dict[str, int]:
    root = storage_cleanup_queue_root()
    bounded = max(0, min(20, int(limit or 0)))
    if bounded == 0 or not root.exists():
        return {"processed": 0, "completed": 0, "failed": 0, "manual_required": 0}
    processed = 0
    completed = 0
    failed = 0
    manual_required = 0
    for source in sorted(root.glob("*.json")):
        if processed >= bounded:
            break
        try:
            if json.loads(source.read_text(encoding="utf-8")).get("status") == "manual_required":
                continue
        except (json.JSONDecodeError, OSError):
            pass
        claimed = root / f"{source.stem}.processing-{os.getpid()}-{uuid4().hex}.json"
        try:
            source.replace(claimed)
        except FileNotFoundError:
            continue
        processed += 1
        payload: dict[str, Any] = {}
        try:
            payload = json.loads(claimed.read_text(encoding="utf-8"))
            canonical = root / f"{source.stem}.json"
            if payload.get("status") == "manual_required":
                _write_storage_cleanup_job(canonical, payload)
                manual_required += 1
                continue
            if not delete_saved_image(dict(payload.get("stored") or {})):
                raise RuntimeError("Stored object was not eligible for cleanup")
            completed += 1
        except Exception as exc:
            attempts = int(payload.get("attempt_count") or 0) + 1
            payload.update(
                {
                    "attempt_count": attempts,
                    "status": "pending" if attempts < MAX_STORAGE_CLEANUP_ATTEMPTS else "manual_required",
                    "last_error": str(exc)[:500],
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
            canonical = root / f"{source.stem}.json"
            _write_storage_cleanup_job(canonical, payload)
            failed += 1
            if payload["status"] == "manual_required":
                manual_required += 1
        finally:
            claimed.unlink(missing_ok=True)
    return {
        "processed": processed,
        "completed": completed,
        "failed": failed,
        "manual_required": manual_required,
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
    if isinstance(result.get("groups"), list):
        result["groups"] = [resolve_group_for_response(item) if isinstance(item, dict) else item for item in result["groups"]]
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
