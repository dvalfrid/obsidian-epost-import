from __future__ import annotations

import socket
from unittest.mock import patch

from mailimporter.remote_fetch import (
    RemoteResource,
    _is_public_host,
    extract_remote_resources,
    remote_filename,
)


def test_extract_images_always_included():
    body = "Look: ![logo](https://example.com/logo.png) and text."
    resources = extract_remote_resources(body)
    assert resources == [RemoteResource(url="https://example.com/logo.png", is_image=True)]


def test_extract_links_only_for_document_extensions():
    body = (
        "See [our site](https://example.com/about) and "
        "[the invoice](https://example.com/files/invoice.pdf)."
    )
    resources = extract_remote_resources(body)
    assert resources == [
        RemoteResource(url="https://example.com/files/invoice.pdf", is_image=False)
    ]


def test_extract_dedupes_by_url():
    body = "![a](https://example.com/x.png) and again ![b](https://example.com/x.png)"
    resources = extract_remote_resources(body)
    assert len(resources) == 1


def test_extract_ignores_cid_and_relative_links():
    body = "![inline](cid:abc123) and [relative](/local/path.pdf)"
    assert extract_remote_resources(body) == []


def test_remote_filename_deterministic_and_uses_url_extension():
    name1 = remote_filename("https://example.com/path/photo.JPG", "image/jpeg")
    name2 = remote_filename("https://example.com/path/photo.JPG", "image/jpeg")
    assert name1 == name2
    assert name1.endswith(".jpg")


def test_remote_filename_falls_back_to_content_type_for_extension():
    name = remote_filename("https://example.com/download?id=42", "application/pdf")
    assert name.endswith(".pdf")


def test_remote_filename_differs_by_url():
    a = remote_filename("https://example.com/a.png", "image/png")
    b = remote_filename("https://example.com/b.png", "image/png")
    assert a != b


def test_is_public_host_rejects_loopback():
    with patch("mailimporter.remote_fetch.socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(socket.AF_INET, None, None, "", ("127.0.0.1", 0))]
        assert _is_public_host("localhost") is False


def test_is_public_host_rejects_private_range():
    with patch("mailimporter.remote_fetch.socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(socket.AF_INET, None, None, "", ("10.0.0.5", 0))]
        assert _is_public_host("internal.example.com") is False


def test_is_public_host_rejects_link_local_metadata():
    with patch("mailimporter.remote_fetch.socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(socket.AF_INET, None, None, "", ("169.254.169.254", 0))]
        assert _is_public_host("metadata.internal") is False


def test_is_public_host_allows_public_ip():
    with patch("mailimporter.remote_fetch.socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(socket.AF_INET, None, None, "", ("93.184.216.34", 0))]
        assert _is_public_host("example.com") is True


def test_is_public_host_rejects_unresolvable_host():
    with patch("mailimporter.remote_fetch.socket.getaddrinfo") as mock_dns:
        mock_dns.side_effect = socket.gaierror
        assert _is_public_host("does-not-exist.invalid") is False
