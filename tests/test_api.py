import pytest
from fastapi.testclient import TestClient
from crewlog.main import create_app
from crewlog.db import MESSAGE_MAX, NAME_MAX
from crewlog import db

class FakeClock:
    def __init__(self, now):
        self.now = now
    def __call__(self):
        return self.now

@pytest.fixture
def clock():
    return FakeClock(1_732_271_400)

@pytest.fixture
def timed_client(db_path, clock):
    return TestClient(create_app(db_path, secret_key="x" * 40, min_age=3, max_age=3600, clock=clock))

@pytest.fixture
def client(db_path):
    return TestClient(create_app(db_path, secret_key="x" * 40, min_age=0))

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "t.db")

@pytest.fixture
def conn(db_path):
    connection = db.connect(db_path)
    yield connection
    connection.close()

def post_message(client, **fields):
    token = client.get("/api/guestbook/token").json()["token"]
    return client.post("/api/guestbook", json={**fields, "token": token})

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
    {"name": "Ada", "message": "y" * (MESSAGE_MAX + 1)}
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
    monkeypatch.delenv("CREWLOG_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="CREWLOG_SECRET"):
        create_app(db_path)

def test_short_secret_is_refused(db_path):
    with pytest.raises(RuntimeError):
        create_app(db_path, secret_key="short")

def test_token_route_returns_a_token_and_is_not_cacheable(timed_client):
    response = timed_client.get("/api/guestbook/token")
    assert response.status_code == 200
    assert response.json()["token"]
    assert response.headers["cache-control"] == "no-store"