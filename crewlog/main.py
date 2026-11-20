import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel, StringConstraints

from crewlog import db

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=db.NAME_MAX)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=db.MESSAGE_MAX)]

class NewMessage(BaseModel):
    name: Name
    message: Text

class PublicMessage(BaseModel):
    id: int
    name: str
    message: str
    created_at: str

def create_app(db_path: str | None = None) -> FastAPI:
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

    @app.get("/api/guestbook", response_model=list[PublicMessage])
    def read_messages(
        conn = Depends(get_conn),
        limit: int = Query(20, ge=1, le=50),
        offset: int = Query(0, ge=0)
    ):
        return db.list_approved(conn, limit, offset)

    @app.post("/api/guestbook", status_code=202)
    def create_message(payload: NewMessage, conn=Depends(get_conn)):
        db.add_message(conn, payload.name, payload.message)
        return {"status": "pending"}

    return app