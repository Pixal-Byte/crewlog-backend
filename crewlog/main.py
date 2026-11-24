# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nova Nightingale
import os
import time

from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Response, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StringConstraints, ConfigDict

from crewlog import db, security

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=db.NAME_MAX)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=db.MESSAGE_MAX)]

class NewMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name:    Name
    message: Text
    website: str   = ""
    token:   str   = ""

class PublicMessage(BaseModel):
    id: int
    name: str
    message: str
    created_at: str

def client_hash(request: Request, secret_key: str, header: str) -> str:
    ip = (request.headers.get(header) or "").strip()
    if not ip:
        ip = request.client.host if request.client else "unknown"
    return security.hash_ip(secret_key, ip)

def create_app(
        db_path: str | None = None,
        *,
        token_secret_key: str | None = None,
        ip_secret_key: str | None = None,
        ip_header: str | None = None,
        rate_per_hour: int | None = None,
        rate_per_day: int | None = None,
        min_age: float | None = None,
        max_age: float | None = None,
        dev_static: str | None = None,
        clock = time.time,

    ) -> FastAPI:

    token_secret_key = token_secret_key or os.environ.get("CREWLOG_TOKEN_KEY")
    if not token_secret_key or len(token_secret_key) < 32:
        raise RuntimeError("CREWLOG_TOKEN_KEY must be set to a random string of at least 32 characters.")

    ip_secret_key = ip_secret_key or os.environ.get("CREWLOG_IP_KEY")
    if not ip_secret_key or len(ip_secret_key) < 32:
        raise RuntimeError("CREWLOG_IP_KEY must be set to a random string of at least 32 characters.")


    ip_header = ip_header if ip_header is not None else os.environ.get("CREWLOG_IP_HEADER", "CF-Connecting-IP")
    rate_per_hour = rate_per_hour if rate_per_hour is not None else int(os.environ.get("CREWLOG_RATE_PER_HOUR", "3"))
    rate_per_day = rate_per_day if rate_per_day is not None else int(os.environ.get("CREWLOG_RATE_PER_DAY", "10"))
    min_age = min_age if min_age is not None else float(os.environ.get("CREWLOG_MIN_AGE", "3"))
    max_age = max_age if max_age is not None else float(os.environ.get("CREWLOG_MAX_AGE", "3600"))
    dev_static = dev_static or os.environ.get("CREWLOG_DEV_STATIC")
    docs = {} if dev_static else {
        "docs_url": None, 
        "redoc_url": None,
        "openapi_url": None
        }


    db_path = db_path or os.environ.get("CREWLOG_DB", "data/crewlog.db")
    app = FastAPI(title="A.R.I.E.S. Crewlog", **docs) # type: ignore

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    init_conn = db.connect(db_path)
    db.init_db(init_conn)
    init_conn.close()


    def get_conn():
        conn = db.connect(db_path)
        try:
            yield conn
        finally:
            conn.close()


# ============== GET routes ================

    @app.get("/api/guestbook", response_model=list[PublicMessage])
    def read_messages(
        conn = Depends(get_conn),
        limit: int = Query(20, ge=1, le=50),
        offset: int = Query(0, ge=0)
    ):
        return db.list_approved(conn, limit, offset)

    @app.get("/api/guestbook/token")
    def get_token(response: Response):
        response.headers["Cache-Control"] = "no-store"
        return {"token": security.make_token(token_secret_key, clock())}

# ============== POST routes ===============

    @app.post("/api/guestbook", status_code=202)
    def create_message(payload: NewMessage,request: Request, conn=Depends(get_conn)):
        if payload.website.strip():
            return {"status": "pending"}

        reason = security.check_token(token_secret_key, payload.token, clock(), min_age, max_age)
        if reason != "ok":
            raise HTTPException(status_code=400, detail="The form expired or was sent too quickly. Please reload and try again.")

        ip_hash = client_hash(request, ip_secret_key, ip_header)
        if db.count_recent(conn, ip_hash, 3600) >= rate_per_hour:
            raise HTTPException(status_code=429, detail="...", headers={"Retry-After": "3600"})
        if db.count_recent(conn, ip_hash, 86400) >= rate_per_day:
            raise HTTPException(status_code=429, detail="...", headers={"Retry-After": "86400"})

        db.add_message(conn, payload.name, payload.message, ip_hash)
        return {"status": "pending"}

# ============= Mount Confiuration ==================

    if dev_static:
        print("WARNING:  CREWLOG_DEV_STATIC is set. you may ignore this warning if this is a development environment")
        app.mount("/", StaticFiles(directory=dev_static, html=True), name="dev-static")

    return app