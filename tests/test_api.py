import pytest
from fastapi.testclient import TestClient
from crewlog.main import create_app
from crewlog.db import MESSAGE_MAX, NAME_MAX
from crewlog import db

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "t.db")

@pytest.fixture
def client(db_path):
    return TestClient(create_app(db_path))

@pytest.fixture
def conn(db_path):
    connection = db.connect(db_path)
    yield connection
    connection.close()

def test_valid_post_is_accepted_but_not_public(client):
    response = client.post("/api/guestbook", json={"name": "Ada", "message": "hello"})
    assert response.status_code == 202
    assert client.get("/api/guestbook").json() == []

def test_approved_message_is_public(client, conn):
    client.post("/api/guestbook", json={"name": "Ada", "message": "Helo"})
    db.set_status(conn, 1, "approved")
    (message,) = client.get("/api/guestbook").json()
    assert set(message) == {"id", "name", "message", "created_at"}
    assert (message["name"], message["message"]) == ("Ada", "Helo")


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
    real = client.post("/api/guestbook", json={"name": "Ada", "message": "hi"})
    bot = client.post("/api/guestbook", json={"name": "Bot", "message": "hi", "website": "x.test"})
    assert (bot.status_code, bot.json()) == (real.status_code, real.json())

@pytest.mark.parametrize("website", ["", "   "])
def test_blank_website_field_is_not_a_bot(client, conn, website):
    response = client.post("/api/guestbook", json={
        "name": "Ada", "message": "hello", "website": website,
    })
    assert response.status_code == 202
    (stored,) = db.list_messages(conn, status="pending")
    assert stored["name"] == "Ada"