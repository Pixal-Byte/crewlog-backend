# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nova Nightingale
import pytest
from fastapi.testclient import TestClient
from crewlog.main import create_app
from crewlog.db import MESSAGE_MAX, NAME_MAX
from crewlog import db
from crewlog.security import hash_ip

class FakeClock:
    def __init__(self, now):
        self.now = now
    def __call__(self):
        return self.now

@pytest.fixture
def clock():
    return FakeClock(1_732_271_324)

@pytest.fixture
def dev_client(db_path, tmp_path):
    return TestClient(create_app(db_path, token_secret_key="x" * 40, ip_secret_key="y" * 40, dev_static=tmp_path))

@pytest.fixture
def timed_client(db_path, clock):
    return TestClient(create_app(db_path, token_secret_key="x" * 40, ip_secret_key="y" * 40, rate_per_day=1000,rate_per_hour=1000, min_age=3, max_age=3600, clock=clock))

@pytest.fixture
def client(db_path):
    return TestClient(create_app(db_path, token_secret_key="x" * 40, ip_secret_key="y" * 40, rate_per_day=1000, rate_per_hour=1000, min_age=0))

@pytest.fixture
def limited_client(db_path):
    return TestClient(create_app(db_path, token_secret_key="x" * 40, ip_secret_key="y" * 40, rate_per_hour=3, rate_per_day=5, min_age=0))

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "t.db")

def backdate(conn, message_id, seconds):
    with conn:
        conn.execute(
            "UPDATE messages SET created_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?) WHERE id = ?",
            (f"-{seconds} seconds", message_id),
        )

@pytest.fixture
def conn(db_path):
    connection = db.connect(db_path)
    yield connection
    connection.close()

def post_message(client, headers=None, **fields):
    token = client.get("/api/guestbook/token").json()["token"]
    return client.post("/api/guestbook", json={**fields, "token": token}, headers=headers)

def use_up_allowance(client, ip, n=3):
    for _ in range(n):
        assert post_message(client, headers={"CF-Connecting-IP": ip},
            name="Ada", message="hi").status_code == 202

def test_valid_post_is_accepted_but_not_public(client):
    response = post_message(client, name="Ada", message="hello")
    assert response.status_code == 202
    assert client.get("/api/guestbook").json() == []

def test_approved_message_is_public(client, conn):
    post_message(client, name="Ada", message="hello")
    db.set_status(conn, 1, "approved")
    (message,) = client.get("/api/guestbook").json()
    assert set(message) == {"id", "name", "message", "created_at"}
    assert (message["name"], message["message"]) == ("Ada", "hello")


@pytest.mark.parametrize("payload", [
    {"name": "", "message": "hello"},
    {"name": "   ", "message": "hello"},
    {"message": "hello"},
    {"name": "x" * (NAME_MAX + 1), "message": "hello"},
    {"name": "Ada", "message": ""},
    {"name": "Ada", "message": "  "},
    {"name": "Ada"},
    {"name": "Ada", "message": "y" * (MESSAGE_MAX + 1)},
    {"name": "Ada", "message": "hi", "extra": "x"}
])
def test_invalid_posts_are_rejected_and_not_stored(client, conn, payload):
    response = client.post("/api/guestbook", json=payload)
    assert response.status_code == 422, response.json()
    assert not db.list_messages(conn)

def test_honeypot_gets_tripped_when_website_field_is_populated(client, conn):
    response = client.post("/api/guestbook", json={
        "name": "bot212",
        "message": "Spammy spam spam",
        "website": "ddosbotswarm.test"
    })
    assert response.status_code == 202
    assert not db.list_messages(conn)

def test_bot_response_is_identical_to_a_real_one(client):
    real = post_message(client, name="Ada", message="hi")
    bot = post_message(client, name="bot", message="spam", website="x.xyz")
    assert (bot.status_code, bot.json()) == (real.status_code, real.json())

@pytest.mark.parametrize("website", ["", "   "])
def test_blank_website_field_is_not_a_bot(client, conn, website):
    response = post_message(client, name="Ada", message="hello", website=website)
    assert response.status_code == 202
    (stored,) = db.list_messages(conn, status="pending")
    assert stored["name"] == "Ada"

def test_post_too_soon_is_rejected_then_accepted(conn, timed_client, clock):
    token = timed_client.get("/api/guestbook/token").json()["token"]
    body = {"name": "Ada", "message": "hi", "token": token}

    clock.now += 1                                          # 1 s after issue
    assert timed_client.post("/api/guestbook", json=body).status_code == 400
    assert not db.list_messages(conn)                       # nothing stored

    clock.now += 5                                          # 6 s after issue
    assert timed_client.post("/api/guestbook", json=body).status_code == 202
    assert len(db.list_messages(conn)) == 1

def test_expired_token_is_400(conn, clock, timed_client):
    token = timed_client.get("/api/guestbook/token").json()["token"]
    body = {"name": "Ada", "message": "hi", "token": token}

    clock.now += 3601
    assert timed_client.post("/api/guestbook", json=body).status_code == 400
    assert not db.list_messages(conn)

def test_no_token(conn, client):
    body = {"name": "Ada", "message": "hi"}
    assert client.post("/api/guestbook", json=body).status_code == 400
    assert not db.list_messages(conn)

def test_garbage_token(conn, client):
    body = {"name": "Ada", "message": "hi", "token": "token"}
    assert client.post("/api/guestbook", json=body).status_code == 400
    assert not db.list_messages(conn)

def test_missing_secret_is_refused(db_path, monkeypatch):
    monkeypatch.delenv("CREWLOG_TOKEN_KEY", raising=False)
    with pytest.raises(RuntimeError, match="CREWLOG_TOKEN_KEY"):
        create_app(db_path)

def test_short_secret_is_refused(db_path):
    with pytest.raises(RuntimeError):
        create_app(db_path, token_secret_key="short")

def test_token_route_returns_a_token_and_is_not_cacheable(timed_client):
    response = timed_client.get("/api/guestbook/token")
    assert response.status_code == 200
    assert response.json()["token"]
    assert response.headers["cache-control"] == "no-store"

def test_missing_ip_secret_is_refused(db_path, monkeypatch):
    monkeypatch.delenv("CREWLOG_IP_KEY", raising=False)
    with pytest.raises(RuntimeError, match="CREWLOG_IP_KEY"):
        create_app(db_path, token_secret_key="x" * 40)

def test_short_ip_secret_is_refused(db_path):
    with pytest.raises(RuntimeError, match="CREWLOG_IP_KEY"):
        create_app(db_path, token_secret_key="x" * 40, ip_secret_key="short")

def test_old_messages_stop_counting(limited_client, conn):
    ip = {"CF-Connecting-IP": "1.1.1.1"}
    for _ in range(3):
        assert post_message(limited_client, headers=ip, name="Ada", message="hi").status_code == 202
    assert post_message(limited_client, headers=ip, name="Ada", message="hi").status_code == 429

    for m in db.list_messages(conn):
        backdate(conn, m["id"], 2 * 3600)                    # now outside the hourly window

    assert post_message(limited_client, headers=ip, name="Ada", message="hi").status_code == 202

def test_stored_ip_is_hashed(limited_client, conn):
    post_message(limited_client, headers={"CF-Connecting-IP": "1.1.1.1"}, name="Ada", message="hi")
    stored = db.get_message(conn, 1)["ip_hash"] # type: ignore
    assert stored != "1.1.1.1"
    assert stored == hash_ip("y" * 40, "1.1.1.1")

def test_allowance(limited_client):
    ip = "1.1.1.1"
    use_up_allowance(limited_client, ip)
    assert post_message(limited_client, headers={"CF-Connecting-IP": ip}, name="Ada", message="hi").status_code == 429

def test_different_ips_have_diferent_allowances(limited_client):
    ip_a = "1.1.1.1"
    ip_b = "8.8.8.8"
    use_up_allowance(limited_client, ip_a)
    assert post_message(limited_client, headers={"CF-Connecting-IP": ip_b}, name="Ada", message="hi").status_code == 202
    assert post_message(limited_client, headers={"CF-Connecting-IP": ip_a}, name="Ada", message="hi").status_code == 429

def test_any_message_after_allowance_is_not_stored(limited_client, conn):
    ip = "1.1.1.1"
    use_up_allowance(limited_client, ip)
    response = post_message(limited_client, headers={"CF-Connecting-IP": ip}, name="Ada", message="hi")
    assert len(db.list_messages(conn)) == 3
    assert response.headers["retry-after"] == "3600"

@pytest.mark.parametrize("route", [
    "/docs",
    "/redoc",
    "/openapi.json"
])
def test_default_app_routes(client, route):
    assert client.get(route).status_code == 404

@pytest.mark.parametrize("route", [
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/guestbook"
])
def test_dev_static_routes(dev_client, route):
    assert dev_client.get(route).status_code == 200

def test_dev_static_serves_the_site(db_path, tmp_path):
    page = tmp_path / "crew-log"
    page.mkdir()
    (page / "index.html").write_text("<h1>crew log</h1>")

    client = TestClient(create_app(db_path, token_secret_key="x" * 40, ip_secret_key="y" * 40, dev_static=str(tmp_path)))
    response = client.get("/crew-log/")
    assert response.status_code == 200
    assert "crew log" in response.text