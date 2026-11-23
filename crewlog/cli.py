import argparse
import os
import sys

from crewlog import db


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crewlog")
    parser.add_argument("--db", default=os.environ.get("CREWLOG_DB"))
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("set", help="Set the status of entry of given ID")
    status.add_argument("--id", type=int, required=True)
    status.add_argument("--status", choices=db.STATUSES, required=True)

    listing = sub.add_parser("list", help="show messages")
    listing.add_argument("--status", default="pending", choices=db.STATUSES)
    return parser

def sanitize(text: str) -> str:
    return "".join(
        ch if ch.isprintable() else ch.encode("unicode_escape").decode()
        for ch in text
    )

def build_entry(entry: dict):
    message_id = entry["id"]
    name =       entry["name"]
    message =    entry["message"]
    status =     entry["status"]
    created_at = entry["created_at"]
    print(f"=========== DB entry #{message_id} ==========================================================")
    print(f"-------------- STATUS {status} -------------------------------------")
    print(f"ID : {message_id}")
    print(f"From: {sanitize(name)}")
    print(f"Message: {sanitize(message)}")
    print(f"----------- TIMESTAMP: {created_at} -----------------------")

def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not args.db:
        print("error: no database given: pass --db or set CREWLOG_DB", file=sys.stderr)
        return 1
    if not os.path.isfile(args.db):
        print(f"error: database file not found: {args.db}", file=sys.stderr)
        return 1

    conn = db.connect(args.db)
    try:
        if args.command == "list":
            message_list = db.list_messages(conn, status=args.status)
            if not message_list:
                print(f"info: no {args.status} messages")
            for message in message_list:
                build_entry(message)

        if args.command == "set":
            if not db.set_status(conn, args.id, args.status):
                print(f"error: no message with id {args.id}", file=sys.stderr)
                return 1
            print(f"info: message {args.id} is now {args.status}")

    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())