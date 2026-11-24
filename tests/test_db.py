# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nova Nightingale
import sqlite3

import pytest

from crewlog import db


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    db.init_db(connection)
    yield connection
    connection.close()

def backdate(conn, message_id, days):
    with conn:
        conn.execute(
            "UPDATE messages SET created_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?) WHERE id = ?",
            (f"-{days} days", message_id),
        )

def test_init_is_idempotent(conn):
    db.init_db(conn)  # second run must not fail or wipe anything
    db.add_message(conn, "Ada", "hello")
    db.init_db(conn)
    assert len(db.list_messages(conn)) == 1


def test_wal_mode_is_on(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_new_message_is_pending_and_hidden_from_public(conn):
    message_id = db.add_message(conn, "Ada", "hello")
    assert db.get_message(conn, message_id)["status"] == "pending" # type: ignore
    assert db.list_approved(conn) == []


def test_approved_message_appears_without_private_fields(conn):
    message_id = db.add_message(conn, "Ada", "hello", ip_hash="abc123")
    assert db.set_status(conn, message_id, "approved") is True
    (public,) = db.list_approved(conn)
    assert set(public) == {"id", "name", "message", "created_at"}
    assert public["name"] == "Ada"


def test_rejected_message_is_not_public(conn):
    message_id = db.add_message(conn, "Spam", "buy things")
    db.set_status(conn, message_id, "rejected")
    assert db.list_approved(conn) == []


def test_public_list_is_newest_first_with_paging(conn):
    ids = [db.add_message(conn, f"n{i}", f"m{i}") for i in range(5)]
    for message_id in ids:
        db.set_status(conn, message_id, "approved")
    # all five were created within the same second: id breaks the tie
    assert [m["id"] for m in db.list_approved(conn)] == ids[::-1]
    assert [m["id"] for m in db.list_approved(conn, limit=2)] == ids[::-1][:2]
    assert [m["id"] for m in db.list_approved(conn, limit=2, offset=2)] == ids[::-1][2:4]


def test_list_messages_filters_by_status(conn):
    a = db.add_message(conn, "A", "one")
    b = db.add_message(conn, "B", "two")
    db.set_status(conn, b, "approved")
    assert {m["id"] for m in db.list_messages(conn)} == {a, b}
    assert [m["id"] for m in db.list_messages(conn, status="pending")] == [a]
    assert [m["id"] for m in db.list_messages(conn, status="approved")] == [b]
    with pytest.raises(ValueError):
        db.list_messages(conn, status="nonsense")


@pytest.mark.parametrize("name, message", [
    ("", "hello"),                         # empty name
    ("   ", "hello"),                      # whitespace-only name
    ("x" * (db.NAME_MAX + 1), "hello"),    # name too long
    ("Ada", ""),                           # empty message
    ("Ada", "   "),                        # whitespace-only message
    ("Ada", "y" * (db.MESSAGE_MAX + 1)),   # message too long
])
def test_schema_rejects_bad_input(conn, name, message):
    with pytest.raises(sqlite3.IntegrityError):
        db.add_message(conn, name, message)
    assert db.list_messages(conn) == []    # and nothing was half-saved


def test_limits_are_inclusive(conn):
    db.add_message(conn, "x" * db.NAME_MAX, "y" * db.MESSAGE_MAX)
    assert len(db.list_messages(conn)) == 1


def test_sql_injection_text_is_stored_as_plain_text(conn):
    nasty_name = "x'); DROP TABLE messages; --"
    nasty_message = "Robert'); DELETE FROM messages; --"
    message_id = db.add_message(conn, nasty_name, nasty_message)
    stored = db.get_message(conn, message_id)
    assert stored["name"] == nasty_name and stored["message"] == nasty_message # type: ignore
    assert db.set_status(conn, message_id, "approved") is True  # table still there


def test_set_status_validation_and_unknown_id(conn):
    message_id = db.add_message(conn, "Ada", "hello")
    with pytest.raises(ValueError):
        db.set_status(conn, message_id, "published")
    assert db.get_message(conn, message_id)["status"] == "pending" # type: ignore
    assert db.set_status(conn, 9999, "approved") is False


def test_delete(conn):
    message_id = db.add_message(conn, "Ada", "hello")
    assert db.delete_message(conn, message_id) is True
    assert db.get_message(conn, message_id) is None
    assert db.delete_message(conn, message_id) is False


def test_purge_old_ip_hashes_only_touches_old_rows(conn):
    old = db.add_message(conn, "Old", "hello", ip_hash="oldhash")
    new = db.add_message(conn, "New", "hello", ip_hash="newhash")
    backdate(conn, old, 31)
    assert db.purge_old_ip_hashes(conn, days=30) == 1
    assert db.get_message(conn, old)["ip_hash"] is None # type: ignore
    assert db.get_message(conn, new)["ip_hash"] == "newhash" # type: ignore
    assert db.purge_old_ip_hashes(conn, days=30) == 0   # nothing left to clear


def test_failed_insert_rolls_back_cleanly(conn):
    db.add_message(conn, "Ada", "hello")
    with pytest.raises(sqlite3.IntegrityError):
        db.add_message(conn, "", "bad")
    db.add_message(conn, "Grace", "still works after an error")
    assert len(db.list_messages(conn)) == 2


def test_only_matching_hash_is_counted(conn):
    db.add_message(conn, "Person A", "First", ip_hash="a")
    db.add_message(conn, "Person B", "Second", ip_hash="b")
    assert db.count_recent(conn, "a", 300) == 1


def test_window_recognition(conn):
    old = db.add_message(conn, "Ada", "Hello", ip_hash="a")
    db.add_message(conn, "Ada", "Hello Again", ip_hash="a")
    backdate(conn, old, 1)
    assert db.count_recent(conn, "a", 60) == 1
    assert db.count_recent(conn, "a", 2 * 86400) == 2

def test_rejected_messages_still_count(conn):
    ids = [db.add_message(conn, "Spam", "buy", ip_hash="a") for _ in range(3)]
    for message_id in ids:
        db.set_status(conn, message_id, "rejected")
    assert db.count_recent(conn, "a", 3600) == 3