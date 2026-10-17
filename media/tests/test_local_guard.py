"""La API local rechaza Host/Origin ajenos (CSRF y DNS rebinding)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from media.services import local_guard as lg

HOSTS = lg.allowed_hostnames()
PORTS = frozenset({8000, 3000})


def ok(method="GET", **h):
    return lg.check(method, {"host": "127.0.0.1:8000", **h}, HOSTS, PORTS)


def test_loopback_hosts_pass():
    for host in ("127.0.0.1:8000", "localhost:3000", "[::1]:8000", "localhost"):
        assert lg.check("GET", {"host": host}, HOSTS, PORTS) is None


@pytest.mark.parametrize("host", ["evil.example.com", "evil.example.com:8000", "127.0.0.1.evil.com", "", "10.0.0.5:8000"])
def test_foreign_host_is_rebinding(host):
    assert lg.check("GET", {"host": host}, HOSTS, PORTS) is not None


def test_origin_must_be_local_app_port():
    assert ok("POST", origin="http://127.0.0.1:3000") is None
    assert ok("POST", origin="http://localhost:3000") is None
    for bad in ("https://evil.example.com", "null", "http://127.0.0.1:5173", "http://127.0.0.1", "http://localhost.evil.com:3000"):
        assert ok("POST", origin=bad) is not None, bad


def test_no_origin_is_server_to_server():
    assert ok("POST") is None


def test_cross_site_only_allowed_for_reads():
    assert ok("GET", **{"sec-fetch-site": "cross-site"}) is None
    assert ok("POST", **{"sec-fetch-site": "cross-site"}) is not None
    assert ok("POST", **{"sec-fetch-site": "same-origin"}) is None


def test_extra_hosts_from_env_list():
    hosts = lg.allowed_hostnames("mi-pc.local, otra.lan")
    assert lg.check("GET", {"host": "mi-pc.local:8000"}, hosts, PORTS) is None


def test_middleware_blocks_with_403_and_lets_good_requests_through():
    app = FastAPI()
    app.add_middleware(lg.LocalGuard, hosts=HOSTS, ports=PORTS)

    @app.post("/x")
    def x():
        return {"ok": True}

    good = TestClient(app, base_url="http://127.0.0.1:8000")
    assert good.post("/x").status_code == 200
    assert good.post("/x", headers={"Origin": "https://evil.example.com"}).status_code == 403
    assert TestClient(app, base_url="http://evil.example.com").post("/x").status_code == 403
