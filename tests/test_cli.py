import pytest
from crewlog import cli, db


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "t.db"
    connection = db.connect(path)
    db.init_db(connection)
    connection.close()
    return str(path)


@pytest.fixture
def conn(db_path):
    connection = db.connect(db_path)
    yield connection
    connection.close()


def test_list_shows_only_pending_by_default(db_path, conn, capsys):
    db.add_message(conn, "PendingPerson", "waiting")
    approved = db.add_message(conn, "ApprovedPerson", "visible")
    db.set_status(conn, approved, "approved")

    assert cli.main(["--db", db_path, "list"]) == 0
    out = capsys.readouterr().out
    assert "PendingPerson" in out
    assert "ApprovedPerson" not in out


def test_list_can_filter_by_status(db_path, conn, capsys):
    db.add_message(conn, "PendingPerson", "waiting")
    approved = db.add_message(conn, "ApprovedPerson", "visible")
    db.set_status(conn, approved, "approved")

    assert cli.main(["--db", db_path, "list", "--status", "approved"]) == 0
    out = capsys.readouterr().out
    assert "ApprovedPerson" in out
    assert "PendingPerson" not in out


@pytest.mark.parametrize("status", db.STATUSES)
def test_empty_list_says_so(db_path, capsys, status):
    assert cli.main(["--db", db_path, "list", "--status", status]) == 0
    assert f"no {status} messages" in capsys.readouterr().out


def test_set_changes_the_status(db_path, conn, capsys):
    message_id = db.add_message(conn, "Ada", "hello")

    code = cli.main(["--db", db_path, "set", "--id", str(message_id), "--status", "approved"])

    assert code == 0
    assert f"message {message_id} is now approved" in capsys.readouterr().out
    assert db.get_message(conn, message_id)["status"] == "approved" # type: ignore


def test_set_unknown_id_fails_loudly(db_path, capsys):
    code = cli.main(["--db", db_path, "set", "--id", "999", "--status", "approved"])

    captured = capsys.readouterr()
    assert code == 1
    assert "no message with id 999" in captured.err
    assert captured.out == ""

def test_set_rejects_unknown_status(db_path, conn):
    message_id = db.add_message(conn, "Ada", "hello")

    with pytest.raises(SystemExit):
        cli.main(["--db", db_path, "set", "--id", str(message_id), "--status", "nonsense"])

    assert db.get_message(conn, message_id)["status"] == "pending" # type: ignore


def test_missing_db_argument_is_refused(monkeypatch, capsys):
    monkeypatch.delenv("CREWLOG_DB", raising=False)

    assert cli.main(["list"]) == 1
    assert "CREWLOG_DB" in capsys.readouterr().err


def test_db_path_can_come_from_the_environment(db_path, monkeypatch, capsys):
    monkeypatch.setenv("CREWLOG_DB", db_path)

    assert cli.main(["list"]) == 0
    assert "no pending messages" in capsys.readouterr().out


def test_nonexistent_database_is_refused_and_not_created(tmp_path, capsys):
    missing = tmp_path / "nope.db"

    assert cli.main(["--db", str(missing), "list"]) == 1
    assert "not found" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []      # nothing was created, not even side files


HOSTILE = "hi\x1b[2J\n=== DB entry #99"      # 23 chars, fits the 40-char name limit
@pytest.mark.parametrize("name, message", [
    (HOSTILE, "ok"),
    ("Ada", HOSTILE),
])
def test_list_neutralises_hostile_text(db_path, conn, capsys, name, message):
    db.add_message(conn, name, message)

    assert cli.main(["--db", db_path, "list"]) == 0
    out = capsys.readouterr().out

    assert "\x1b" not in out                                              # no raw escape byte
    assert len([l for l in out.splitlines() if l.startswith("=")]) == 1   # only the real header


@pytest.mark.parametrize("raw, expected", [
    ("plain", "plain"),
    ("café ✓", "café ✓"),            # normal Unicode passes through
    ("a\nb", "a\\nb"),
    ("a\tb", "a\\tb"),
    ("\x1b[2J", "\\x1b[2J"),
])
def test_sanitize(raw, expected):
    assert cli.sanitize(raw) == expected