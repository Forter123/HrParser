from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import SearchQuery, SearchStatus, User
from app.sources.base import SOURCE_CHOICES, SOURCE_KEYS

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/searches", response_class=HTMLResponse)
def list_searches(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    searches = db.execute(select(SearchQuery).order_by(SearchQuery.created_at.desc())).scalars().all()
    source_labels = dict(SOURCE_CHOICES)
    search_source_display = {
        s.id: ", ".join(source_labels.get(key, key) for key in s.source_keys()) or "все"
        for s in searches
    }
    return templates.TemplateResponse(
        request,
        "searches.html",
        {
            "searches": searches,
            "user": user,
            "source_choices": SOURCE_CHOICES,
            "search_source_display": search_source_display,
        },
    )


@router.post("/searches")
def create_search(
    request: Request,
    title: str = Form(...),
    keywords: str = Form(...),
    sources: list[str] = Form([]),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    selected = [s for s in sources if s in SOURCE_KEYS]
    search = SearchQuery(
        title=title,
        keywords=keywords,
        sources=",".join(selected),
        status=SearchStatus.active,
        created_by=user.id,
    )
    db.add(search)
    db.commit()
    return RedirectResponse(url="/searches", status_code=303)


@router.post("/searches/{search_id}/status")
def update_search_status(
    search_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    search = db.get(SearchQuery, search_id)
    if search and status in SearchStatus.__members__:
        search.status = SearchStatus[status]
        db.commit()
    return RedirectResponse(url="/searches", status_code=303)
