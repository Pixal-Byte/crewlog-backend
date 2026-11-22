import os
import time

from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Response, HTTPException
from pydantic import BaseModel, StringConstraints

from crewlog import db, security

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=db.NAME_MAX)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=db.MESSAGE_MAX)]

class NewMessage(BaseModel):
    name:    Name
    message: Text
    website: str   = ""
    token:   str   = ""

class PublicMessage(BaseModel):
    id: int
    name: str
    message: str
    created_at: str

def create_app(
        db_path: str | None = None,
        *,
        secret_key: str | None = None,
        min_age: float | None = None,
        max_age: float | None = None,
        clock = time.time
    ) -> FastAPI:

    secret_key = secret_key or os.environ.get("CREWLOG_SECRET")
    if not secret_key or len(secret_key) < 32:
        raise RuntimeError("CREWLOG_SECRET must be set to a random string of at least 32 characters.")

    min_age = min_age if min_age is not None else float(os.environ.get("CREWLOG_MIN_AGE", "3"))
    max_age = max_age if max_age is not None else float(os.environ.get("CREWLOG_MAX_AGE", "3600"))

    db_path = db_path or os.environ.get("CREWLOG_DB", "data/crewlog.db")
    app = FastAPI(title="A.R.I.E.S. Crewlog")

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
        return {"token": security.make_token(secret_key, clock())}

# ============== POST routes ===============

    @app.post("/api/guestbook", status_code=202)
    def create_message(payload: NewMessage, conn=Depends(get_conn)):
        if payload.website.strip():
            return {"status": "pending"}

        reason = security.check_token(secret_key, payload.token, clock(), min_age, max_age)
        if reason != "ok":
            raise HTTPException(status_code=400, detail="The form expired or was sent too quickly. Please reload and try again.")

        db.add_message(conn, payload.name, payload.message)
        return {"status": "pending"}

    return app