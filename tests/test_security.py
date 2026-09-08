import asyncio
import socket

import httpx
import pytest

from citefabric.documents import download, public_address
from citefabric.models import DocumentCandidate, FabricError


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "http://user:pass@example.org/test", "https://example.org:8080/test"],
)
async def test_unsupported_url_forms(url):
    with pytest.raises(FabricError):
        await public_address(httpx.URL(url))


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1", "::ffff:127.0.0.1"]
)
async def test_dns_rejects_nonpublic_addresses(monkeypatch, address):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (address, 443))],
    )
    with pytest.raises(FabricError) as exc:
        await public_address(httpx.URL("https://example.org/paper.pdf"))
    assert exc.value.code == "permission_denied"


async def test_redirect_rechecks_dns_and_pins_connection(monkeypatch, config):
    requests = []

    def resolve(host, *args, **kwargs):
        address = "93.184.216.34" if host == "example.org" else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (address, 443))]

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://internal.example/paper.pdf"})

    original = httpx.AsyncClient
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    config.offline = False
    with pytest.raises(FabricError) as exc:
        await download(
            DocumentCandidate(url="https://example.org/paper.pdf", provider="test"), config
        )
    assert exc.value.code == "permission_denied"
    assert len(requests) == 1
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["host"] == "example.org"
    assert requests[0].extensions["sni_hostname"] == "example.org"


async def test_parser_is_killed_on_cancellation(monkeypatch, config, tmp_path):
    from citefabric.documents import parse_pdf

    started, killed = asyncio.Event(), asyncio.Event()

    class Process:
        returncode = None

        async def communicate(self, data=None):
            started.set()
            await killed.wait()
            return b"", b""

        def kill(self):
            self.returncode = -9
            killed.set()

    async def create(*args, **kwargs):
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    task = asyncio.create_task(parse_pdf(tmp_path / "input.pdf", config))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert killed.is_set()
