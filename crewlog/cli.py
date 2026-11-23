import argparse
import os
import sys

from crewlog import db


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crewlog")
    parser.add_argument("--db", default=os.environ.get("CREWLOG_DB"))
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("set", help="Set the status of entry of given ID")
    status.add_argument("--id", type=int)
    status.add_argument("--status", choices=db.STATUSES)

    listing = sub.add_parser("list", help="show messages")
    listing.add_argument("--status", default="pending", choices=db.STATUSES)
    return parser

def build_entry(entry: dict):
    id =            entry.get("id")
    name =          entry.get("name")
    message =       entry.get("message")
    status =        entry.get("status")
    created_at =    entry.get("created_at")
    print(f"=========== DB entry #{entry.get("id")} ==========================================================")
    print(f"-------------- STATUS {status} -------------------------------------")
    print(f"ID : {id}")
    print(f"From: {name}")
    print(f"Message: {message}")
    print(f"----------- TIMESTAMP: {created_at} -----------------------")

def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    conn = db.connect(args.db)

    if args.command == "list":
        for message in db.list_messages(conn, status=args.status):
            build_entry(message)

    if args.command == "set":
        db.set_status(conn, message_id=args.id, status=args.status)

    conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())