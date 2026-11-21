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

def test_valid_post_is_accepted_but_not_public(client):
    response = client.post("/api/guestbook", json={"name": "Ada", "message": "hello"})
    assert response.status_code == 202
    assert client.get("/api/guestbook").json() == []

def test_approved_message_is_public(client, db_path):
    client.post("/api/guestbook", json={"name": "Ada", "message": "Helo"})
    conn = db.connect(db_path)
    db.set_status(conn, 1, "approved")
    conn.close()
    (message,) = client.get("/api/guestbook").json()
    assert set(message) == {"id", "name", "message", "created_at"}


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
def test_invalid_posts_are_rejected_and_not_stored(client, db_path, payload):
    response = client.post("/api/guestbook", json=payload)
    assert response.status_code == 422, response.json()

    conn = db.connect(db_path)
    try:
        assert db.list_messages(conn) == []
    finally:
        conn.close()