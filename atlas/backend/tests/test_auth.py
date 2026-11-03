"""Cloud login: off by default, signed expiring cookie, throttling, CSRF, websocket, public host, static web, refusal to run open."""
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from atlas_api import auth as A
from atlas_api.app import create_app

PW = "correct horse battery staple"
HOST = "http://127.0.0.1:8000"


def client(tmp_path, password=PW, base=HOST, name="a.db", **kw):
    return TestClient(create_app(db_path=str(tmp_path / name), demo=True, alert_loop=False, auth_password=password, **kw), base_url=base)


# --- unit: tokens, passwords, throttle -------------------------------------------------------------------------------------------------
def test_token_is_signed_expires_and_dies_with_a_password_change():
    a = A.Auth(PW)
    t = a.make_token(now=1000.0)
    assert a.valid_token(t, now=1001.0) and not a.valid_token(t, now=1000.0 + A.MAX_AGE + 1)
    exp, sig = t.split(".")
    assert not a.valid_token(f"{int(exp) + 999999}.{sig}", now=1001.0) and not a.valid_token(f"{exp}.{'0' * 64}", now=1001.0)
    assert not a.valid_token(None) and not a.valid_token("garbage") and not a.valid_token("")
    assert not A.Auth("another long password!").valid_token(t, now=1001.0)


def test_password_check_and_minimum_length():
    a = A.Auth(PW)
    assert a.check_password(PW) and not a.check_password(PW + "x") and not a.check_password("")
    with pytest.raises(ValueError):
        A.Auth("short")
    assert A.Auth(None).enabled is False and A.Auth("").enabled is False and not A.Auth(None).valid_token("1.2")


def test_throttle_blocks_after_five_failures_then_clears():
    a = A.Auth(PW)
    for i in range(5):
        assert a.retry_after("1.2.3.4", now=100.0 + i) == 0
        a.record_failure("1.2.3.4", now=100.0 + i)
    assert a.retry_after("1.2.3.4", now=110.0) > 0 and a.retry_after("9.9.9.9", now=110.0) == 0
    assert a.retry_after("1.2.3.4", now=100.0 + A.FAIL_WINDOW + 10) == 0                       # the window passes
    a.record_failure("1.2.3.4", now=1000.0)
    a.clear_failures("1.2.3.4")
    assert a.retry_after("1.2.3.4", now=1001.0) == 0


def test_server_refuses_to_listen_publicly_without_a_password():
    assert "Refusing" in A.refuse_open_server("0.0.0.0", None) and "Refusing" in A.refuse_open_server("0.0.0.0", "")
    assert A.refuse_open_server("0.0.0.0", PW) is None and A.refuse_open_server("127.0.0.1", None) is None and A.refuse_open_server("localhost", None) is None


# --- HTTP behaviour ------------------------------------------------------------------------------------------------------------------------
def test_login_is_off_by_default_and_changes_nothing(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "off.db"), demo=True, alert_loop=False)) as c:
        assert c.get("/api/auth/status").json()["data"] == {"required": False, "authenticated": True}
        assert c.get("/api/market/status").status_code == 200 and c.post("/api/auth/login", json={"password": "x"}).json()["data"]["authenticated"] is True


def test_everything_under_api_needs_the_cookie_except_login_status_and_liveness(tmp_path):
    with client(tmp_path) as c:
        assert c.get("/api/auth/status").json()["data"] == {"required": True, "authenticated": False}
        assert c.get("/api/health").status_code == 200
        for path in ("/api/market/status", "/api/quotes?ids=BTC", "/api/macro/overview", "/api/macro/fed", "/api/health/check", "/api/settings"):
            r = c.get(path)
            assert r.status_code == 401 and r.json()["error"]["code"] == "AUTH_REQUIRED", path
        assert c.post("/api/health/check", headers={"X-Atlas-Request": "health-check"}).status_code == 401
        assert c.post("/api/orders/live").status_code == 401                                   # unauthenticated: not even a 403 from the route


def test_login_sets_a_strict_httponly_cookie_and_unlocks_the_api(tmp_path):
    with client(tmp_path) as c:
        bad = c.post("/api/auth/login", json={"password": "wrong password here"})
        assert bad.status_code == 401 and bad.json()["error"]["code"] == "BAD_PASSWORD" and "atlas_session" not in bad.headers.get("set-cookie", "")
        r = c.post("/api/auth/login", json={"password": PW})
        cookie = r.headers["set-cookie"].lower()
        assert r.status_code == 200 and "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie and "secure" not in cookie         # http in this test
        assert c.get("/api/auth/status").json()["data"]["authenticated"] is True and c.get("/api/market/status").status_code == 200
        out = c.post("/api/auth/logout")
        assert out.status_code == 200 and c.get("/api/market/status").status_code == 401


def test_cookie_is_secure_behind_https(tmp_path):
    with client(tmp_path, base="https://atlas.example.com") as c:
        assert "secure" in c.post("/api/auth/login", json={"password": PW}).headers["set-cookie"].lower()


def test_forged_and_expired_cookies_are_rejected(tmp_path):
    with client(tmp_path) as c:
        c.cookies.set("atlas_session", "9999999999." + "0" * 64)
        assert c.get("/api/market/status").status_code == 401
        c.cookies.set("atlas_session", A.Auth(PW).make_token(now=1.0))                          # expired long ago
        assert c.get("/api/market/status").status_code == 401


def test_repeated_wrong_passwords_are_throttled_even_for_the_right_one(tmp_path, monkeypatch):
    async def fast(_):
        return None
    monkeypatch.setattr("atlas_api.app.asyncio.sleep", fast)
    with client(tmp_path) as c:
        codes = [c.post("/api/auth/login", json={"password": f"wrong password {i}"}).status_code for i in range(5)]
        assert codes == [401] * 5
        r = c.post("/api/auth/login", json={"password": PW})
        assert r.status_code == 429 and r.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"


def test_state_changing_requests_from_other_sites_are_refused_even_when_logged_in(tmp_path):
    with client(tmp_path) as c:
        c.post("/api/auth/login", json={"password": PW})
        evil = c.post("/api/prefs", json={"theme": "light"}, headers={"Origin": "https://evil.example"})
        assert evil.status_code == 403 and evil.json()["error"]["code"] == "FORBIDDEN_ORIGIN"
        assert c.post("/api/prefs", json={"theme": "light"}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert c.post("/api/auth/login", json={"password": PW}, headers={"Origin": "https://evil.example"}).status_code == 403          # login CSRF too
        assert c.get("/api/market/status", headers={"Origin": "https://evil.example"}).status_code == 200                      # reads carry no side effects; the cookie is SameSite=Strict


def test_websocket_needs_the_cookie(tmp_path):
    with client(tmp_path) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws/market-data"):
                pass
        c.post("/api/auth/login", json={"password": PW})
        token = c.cookies.get("atlas_session")                                                  # the test client does not forward its cookie jar to websockets
        with c.websocket_connect("/ws/market-data", headers={"cookie": f"atlas_session={token}"}) as ws:
            ws.send_json({"subscribe": []})
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws/market-data", headers={"cookie": "atlas_session=1.deadbeef"}):
                pass


def test_public_hostname_is_allowed_by_the_origin_checks_and_the_health_check_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_ALLOWED_HOST", "atlas.example.com")
    with client(tmp_path, base="https://atlas.example.com", name="h.db") as c:
        c.post("/api/auth/login", json={"password": PW}, headers={"Origin": "https://atlas.example.com"})
        ok = c.post("/api/health/check", headers={"X-Atlas-Request": "health-check", "Origin": "https://atlas.example.com"})
        assert ok.status_code == 200
        assert c.post("/api/health/check", headers={"X-Atlas-Request": "health-check", "Origin": "https://other.example"}).status_code == 403
        assert c.post("/api/health/check", headers={"X-Atlas-Request": "health-check", "Host": "evil.example"}).status_code == 403


def test_without_the_public_host_setting_a_public_hostname_is_still_refused(tmp_path):
    with client(tmp_path, base="https://atlas.example.com", name="n.db") as c:
        c.post("/api/auth/login", json={"password": PW})
        assert c.post("/api/health/check", headers={"X-Atlas-Request": "health-check"}).status_code == 403


# --- serving the web app from the backend ----------------------------------------------------------------------------------------------------
def test_built_web_app_is_served_publicly_but_never_shadows_the_api(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>ATLAS web</body></html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setenv("ATLAS_WEB_DIST", str(dist))
    with client(tmp_path, name="s.db") as c:
        assert "ATLAS web" in c.get("/").text and c.get("/assets/app.js").status_code == 200                # the login screen must load before login
        assert c.get("/api/market/status").status_code == 401                                              # but data does not
        c.post("/api/auth/login", json={"password": PW})
        assert c.get("/api/market/status").json()["ok"] is True and c.get("/api/auth/status").json()["ok"] is True


def test_no_web_dist_means_no_static_mount(tmp_path, monkeypatch):
    monkeypatch.delenv("ATLAS_WEB_DIST", raising=False)
    with client(tmp_path, name="d.db") as c:
        assert c.get("/").status_code == 404


def test_public_host_may_include_a_port_for_testing(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_ALLOWED_HOST", "atlas.example.com:8443")
    with client(tmp_path, base="https://atlas.example.com:8443", name="p.db") as c:
        h = {"Origin": "https://atlas.example.com:8443"}
        assert c.post("/api/auth/login", json={"password": PW}, headers=h).status_code == 200
        assert c.post("/api/health/check", headers={**h, "X-Atlas-Request": "health-check"}).status_code == 200
        assert c.post("/api/auth/login", json={"password": PW}, headers={"Origin": "https://atlas.example.com"}).status_code == 403


# --- mobile: bearer tokens and opt-in CORS ---------------------------------------------------------------------------------------------------
def mobile_login(c, password=PW):
    r = c.post("/api/auth/login", json={"password": password, "client": "mobile"})
    return r


def test_mobile_login_returns_a_long_lived_token_and_sets_no_cookie(tmp_path):
    with client(tmp_path) as c:
        r = mobile_login(c)
        d = r.json()["data"]
        assert r.status_code == 200 and d["authenticated"] is True and d["expires_in"] == A.MOBILE_MAX_AGE and "set-cookie" not in r.headers
        assert A.Auth(PW).valid_token(d["token"], now=time.time() + 29 * 86400) and not A.Auth(PW).valid_token(d["token"], now=time.time() + 31 * 86400)
        assert "token" not in c.post("/api/auth/login", json={"password": PW}).json()["data"]                  # the web login never hands the token to page scripts
        assert mobile_login(c, "wrong password here").status_code == 401


def test_bearer_token_unlocks_the_api_without_cookies_and_bad_tokens_do_not(tmp_path):
    with client(tmp_path) as c:
        tok = mobile_login(c).json()["data"]["token"]
        c.cookies.clear()
        assert c.get("/api/signal/meta").status_code == 401
        ok = c.get("/api/signal/meta", headers={"Authorization": f"Bearer {tok}"})
        assert ok.status_code == 200 and ok.json()["data"]["live_trading"] is False
        assert c.get("/api/auth/status", headers={"Authorization": f"Bearer {tok}"}).json()["data"]["authenticated"] is True
        for bad in (f"Bearer {tok}x", "Bearer ", "Bearer", "Basic abc", tok, "Bearer 9999999999." + "0" * 64):
            assert c.get("/api/signal/meta", headers={"Authorization": bad}).status_code == 401, bad
        other = A.Auth("a completely different password").make_token(ttl=A.MOBILE_MAX_AGE)
        assert c.get("/api/signal/meta", headers={"Authorization": f"Bearer {other}"}).status_code == 401
        with c.websocket_connect("/ws/market-data", headers={"Authorization": f"Bearer {tok}"}) as ws:          # websockets accept the token too
            ws.send_json({"subscribe": []})


def test_bearer_requests_skip_the_browser_cross_site_check_but_cookies_still_need_it(tmp_path):
    with client(tmp_path) as c:
        tok = mobile_login(c).json()["data"]["token"]
        h = {"Authorization": f"Bearer {tok}", "Origin": "http://localhost:8081"}
        assert c.post("/api/signal/watchlist", json={"id": "EQUITY:NASDAQ:AAPL"}, headers=h).status_code == 200           # a token is not sent automatically by browsers: no CSRF risk
        c.post("/api/auth/login", json={"password": PW})                                                                # cookie session
        assert c.post("/api/signal/watchlist", json={"id": "ETF:ARCA:SPY"}, headers={"Origin": "http://localhost:8081"}).status_code == 403   # cookies need the origin check


def test_cors_is_closed_by_default_and_opt_in_for_listed_origins(tmp_path, monkeypatch):
    ask = {"Origin": "http://localhost:8081", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"}
    monkeypatch.delenv("ATLAS_CORS_ORIGINS", raising=False)
    with client(tmp_path, name="c1.db") as c:
        assert "access-control-allow-origin" not in c.options("/api/signal/meta", headers=ask).headers
    monkeypatch.setenv("ATLAS_CORS_ORIGINS", "http://localhost:8081, https://signal.example.com, not-a-url")
    with client(tmp_path, name="c2.db") as c:
        r = c.options("/api/signal/meta", headers=ask)
        assert r.headers["access-control-allow-origin"] == "http://localhost:8081" and "authorization" in r.headers["access-control-allow-headers"].lower()
        assert "access-control-allow-origin" not in c.options("/api/signal/meta", headers={**ask, "Origin": "https://evil.example"}).headers
        assert c.post("/api/auth/login", json={"password": PW, "client": "mobile"}, headers={"Origin": "http://localhost:8081"}).status_code == 200   # the listed origin may log in
        assert c.post("/api/auth/login", json={"password": PW, "client": "mobile"}, headers={"Origin": "https://evil.example"}).status_code == 403
