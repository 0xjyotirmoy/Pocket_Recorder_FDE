from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.search import user_search

router = APIRouter(tags=["search"])


@router.get("/search")
def search(q: str = "", date_from: str | None = None, date_to: str | None = None, db: Session = Depends(get_db)):
    """Returns {date_from, date_to, text, recordings: [...matching sessions], hits: [...transcript lines]}."""
    if not q.strip() and not date_from:
        return {"query": q, "text": "", "date_from": None, "date_to": None, "recordings": [], "hits": []}
    return user_search(db, q, date_from, date_to)
