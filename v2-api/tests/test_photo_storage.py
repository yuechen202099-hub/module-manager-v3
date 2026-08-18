from __future__ import annotations

import socket
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from app.services import photo_storage


class _PublicPeerSocket:
    def __init__(self, wrapped: socket.socket, public_address: str) -> None:
        self._wrapped = wrapped
        self._public_address = public_address

    def getpeername(self):  # noqa: ANN201
        peer = self._wrapped.getpeername()
        return (self._public_address, peer[1])

    def __getattr__(self, name: str):
        return getattr(self._wrapped, name)


def test_remote_image_opener_pins_validated_ip_without_second_dns_lookup(monkeypatch) -> None:
    received_hosts: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            received_hosts.append(self.headers.get("Host", ""))
            body = b"pinned-response"
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_create_connection = socket.create_connection
    public_address = "93.184.216.34"
    connection_targets: list[tuple[str, int]] = []

    def connect_to_test_server(address, timeout=None, source_address=None):  # noqa: ANN001, ANN202
        connection_targets.append(address)
        assert address[0] == public_address
        wrapped = original_create_connection(
            ("127.0.0.1", server.server_port),
            timeout=timeout,
            source_address=source_address,
        )
        return _PublicPeerSocket(wrapped, public_address)

    monkeypatch.setattr(photo_storage.socket, "create_connection", connect_to_test_server)
    url = f"http://rebind.test:{server.server_port}/photo.jpg"
    try:
        with photo_storage.open_validated_remote_image_url(
            url,
            headers={"Accept": "image/*"},
            timeout=2,
            allowed_hosts={"rebind.test"},
            app_env="production",
            resolver=lambda _hostname: [public_address],
        ) as response:
            assert response.read() == b"pinned-response"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert connection_targets == [(public_address, server.server_port)]
    assert received_hosts == [f"rebind.test:{server.server_port}"]


def test_pinned_https_connection_preserves_original_host_for_sni(monkeypatch) -> None:
    connection = photo_storage._PinnedHTTPSConnection(
        "images.example",
        pinned_addresses=("93.184.216.34",),
        timeout=2,
    )
    raw_socket = object()
    wrapped_socket = object()
    server_names: list[str] = []

    class Context:
        def wrap_socket(self, sock, *, server_hostname=None):  # noqa: ANN001, ANN201
            assert sock is raw_socket
            server_names.append(server_hostname)
            return wrapped_socket

    monkeypatch.setattr(connection, "_connect_to_pinned_address", lambda: raw_socket)
    connection._context = Context()

    connection.connect()

    assert connection.sock is wrapped_socket
    assert server_names == ["images.example"]


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.1.1", "::1"])
def test_private_or_rebound_remote_image_address_is_rejected(address: str) -> None:
    with pytest.raises(ValueError, match="not allowed"):
        photo_storage.validate_remote_image_url(
            "https://img.example/a.jpg",
            allowed_hosts={"img.example"},
            app_env="production",
            resolver=lambda _host: [address],
        )


def test_pinned_connection_rejects_peer_address_mismatch(monkeypatch) -> None:
    class MismatchedPeerSocket:
        closed = False

        def getpeername(self):  # noqa: ANN201
            return ("93.184.216.35", 443)

        def close(self) -> None:
            self.closed = True

    peer_socket = MismatchedPeerSocket()
    connection = photo_storage._PinnedHTTPConnection(
        "img.example",
        pinned_addresses=("93.184.216.34",),
        timeout=2,
    )
    monkeypatch.setattr(connection, "_create_connection", lambda *_args: peer_socket)

    with pytest.raises(OSError, match="peer address changed"):
        connection.connect()

    assert peer_socket.closed is True


def test_remote_image_opener_does_not_follow_redirects(monkeypatch) -> None:
    received_paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            received_paths.append(self.path)
            if self.path == "/photo.jpg":
                self.send_response(302)
                self.send_header("Location", "/redirected.jpg?token=secret")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()

        def log_message(self, _format: str, *_args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_create_connection = socket.create_connection
    public_address = "93.184.216.34"

    def connect_to_test_server(address, timeout=None, source_address=None):  # noqa: ANN001, ANN202
        assert address[0] == public_address
        wrapped = original_create_connection(
            ("127.0.0.1", server.server_port),
            timeout=timeout,
            source_address=source_address,
        )
        return _PublicPeerSocket(wrapped, public_address)

    monkeypatch.setattr(photo_storage.socket, "create_connection", connect_to_test_server)
    try:
        with pytest.raises(urllib.error.HTTPError) as caught:
            photo_storage.open_validated_remote_image_url(
                f"http://redirect.test:{server.server_port}/photo.jpg",
                timeout=2,
                allowed_hosts={"redirect.test"},
                app_env="production",
                resolver=lambda _hostname: [public_address],
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert caught.value.code == 302
    assert received_paths == ["/photo.jpg"]
