"""Database layer for the crew log (guestbook).

Plain sqlite3 from the standard library: every query is SQL written in this
file, and every value reaches the database through ? placeholders, never by
pasting text into the query string.
"""

import sqlite3

NAME_MAX = 40
MESSAGE_MAX = 500
STATUSES = ("pending", "approved", "rejected")

# The limits come from the constants above, so each number is defined once.
# (Formatting these into the schema is safe: they are our own constants, not
# visitor input. Visitor input only ever goes through ? placeholders.)
_STATUS_LIST = ", ".join(f"'{s}'" for s in STATUSES)
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL CHECK (length(trim(name))    BETWEEN 1 AND {NAME_MAX}),
    message    TEXT NOT NULL CHECK (length(trim(message)) BETWEEN 1 AND {MESSAGE_MAX}),
    status     TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ({_STATUS_LIST})),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ip_hash    TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_status_created
    ON messages (status, created_at);
"""


def connect(path):
    """Open a connection. Cheap in SQLite, so callers open one per request."""
    conn = sqlite3.connect(path, timeout=5, check_same_thread=False)  # wait up to 5 s if another writer holds the lock
    conn.row_factory = sqlite3.Row           # rows readable by column name, not just position
    conn.execute("PRAGMA journal_mode = WAL")  # readers and one writer no longer block each other
    return conn


def init_db(conn):
    """Create the table and index if they do not exist yet. Safe to run every start."""
    conn.executescript(SCHEMA)


def add_message(conn, name, message, ip_hash=None):
    """Store a new message as 'pending' and return its id.

    The CHECK constraints in the schema are the backstop: bad input raises
    sqlite3.IntegrityError. Friendly validation belongs in the API layer.
    """
    with conn:  # commits on success, rolls back if an exception escapes
        cur = conn.execute(
            "INSERT INTO messages (name, message, ip_hash) VALUES (?, ?, ?)",
            (name, message, ip_hash),
        )
    return cur.lastrowid


def list_approved(conn, limit=50, offset=0):
    """Public view: approved messages, newest first. Never includes ip_hash or status."""
    rows = conn.execute(
        "SELECT id, name, message, created_at FROM messages "
        "WHERE status = 'approved' "
        "ORDER BY created_at DESC, id DESC "
        "LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [dict(row) for row in rows]


def list_messages(conn, status=None, limit=100, offset=0):
    """Admin view: all columns, optionally filtered by status, newest first."""
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, got {status!r}")
    rows = conn.execute(
        "SELECT id, name, message, status, created_at, ip_hash FROM messages "
        "WHERE (? IS NULL OR status = ?) "  # one query covers both 'all' and 'one status'
        "ORDER BY created_at DESC, id DESC "
        "LIMIT ? OFFSET ?",
        (status, status, limit, offset),
    ).fetchall()
    return [dict(row) for row in rows]


def get_message(conn, message_id):
    """One message as a dict (all columns), or None if the id does not exist."""
    row = conn.execute(
        "SELECT id, name, message, status, created_at, ip_hash FROM messages WHERE id = ?",
        (message_id,),
    ).fetchone()
    return dict(row) if row else None


def set_status(conn, message_id, status):
    """Change a message's status. Returns True if the message existed."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, got {status!r}")
    with conn:
        cur = conn.execute(
            "UPDATE messages SET status = ? WHERE id = ?", (status, message_id)
        )
    return cur.rowcount == 1


def delete_message(conn, message_id):
    """Remove a message for good. Returns True if it existed."""
    with conn:
        cur = conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
    return cur.rowcount == 1


def purge_old_ip_hashes(conn, days=30):
    """Forget the IP hash of messages older than `days`. Returns how many were cleared.

    This keeps the promise made on the form: hashes are kept for spam control only.
    """
    with conn:
        cur = conn.execute(
            "UPDATE messages SET ip_hash = NULL "
            "WHERE ip_hash IS NOT NULL "
            "AND created_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)",
            (f"-{int(days)} days",),
        )
    return cur.rowcount

def count_recent(conn, ip_hash, seconds):
    return conn.execute(
        "SELECT COUNT(*) FROM messages "
        "WHERE ip_hash = ? AND created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)",
        (ip_hash, f"-{seconds} seconds"),
    ).fetchone()[0]