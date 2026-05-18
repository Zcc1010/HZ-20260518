import socket

from webui.__main__ import _apply_patches


def _patch_resolution(monkeypatch, mapping):
    def fake_getaddrinfo(host, port, family=0, socktype=0, proto=0, flags=0):
        if host not in mapping:
            raise socket.gaierror(f"unmapped host: {host}")
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, 0))
            for addr in mapping[host]
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def test_validate_url_target_allows_rfc1918_after_patches(monkeypatch):
    from nanobot.security import network

    _patch_resolution(
        monkeypatch,
        {
            "intranet-10.local": ["10.34.38.115"],
            "intranet-172.local": ["172.16.8.9"],
            "intranet-192.local": ["192.168.1.20"],
        },
    )

    _apply_patches()

    assert network.validate_url_target("http://intranet-10.local/") == (True, "")
    assert network.validate_url_target("http://intranet-172.local/") == (True, "")
    assert network.validate_url_target("http://intranet-192.local/") == (True, "")


def test_contains_internal_url_allows_rfc1918_urls_after_patches(monkeypatch):
    from nanobot.security import network

    _patch_resolution(monkeypatch, {"intranet.local": ["10.34.38.115"]})

    _apply_patches()

    assert network.contains_internal_url("curl -I http://intranet.local/llm/") is False


def test_loopback_and_link_local_remain_blocked(monkeypatch):
    from nanobot.security import network

    _patch_resolution(
        monkeypatch,
        {
            "loopback.local": ["127.0.0.1"],
            "linklocal.local": ["169.254.10.20"],
        },
    )

    _apply_patches()

    loopback_ok, loopback_error = network.validate_url_target("http://loopback.local/")
    linklocal_ok, linklocal_error = network.validate_url_target("http://linklocal.local/")

    assert loopback_ok is False
    assert "private/internal address" in loopback_error
    assert linklocal_ok is False
    assert "private/internal address" in linklocal_error
