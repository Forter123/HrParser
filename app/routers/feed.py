from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Candidate, CandidateStatus, User
from app.realtime import manager

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

SOURCE_LABELS = {
    "telegram": "Telegram",
    "superjob": "SuperJob",
    "linkedin": "LinkedIn",
    "hh": "HH.ru",
}


def _card_context(db: Session, candidate: Candidate, last_seen_at: datetime | None) -> dict:
    latest = candidate.latest_entry()
    is_new_badge = None
    if last_seen_at is not None and latest is not None:
        created = latest.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        seen = last_seen_at if last_seen_at.tzinfo else last_seen_at.replace(tzinfo=timezone.utc)
        if created > seen:
            is_new_badge = "Обновлено" if latest.is_update else "Новая"
    return {
        "candidate": candidate,
        "latest": latest,
        "badge": is_new_badge,
        "statuses": list(CandidateStatus),
        "source_label": SOURCE_LABELS.get(candidate.source, candidate.source),
    }


@router.get("/", response_class=HTMLResponse)
def feed(
    request: Request,
    status: str | None = None,
    source: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    last_seen_at = user.last_seen_at

    query = select(Candidate)
    selected_status = None
    if status:
        try:
            selected_status = CandidateStatus(status)
            query = query.where(Candidate.current_status == selected_status)
        except ValueError:
            pass
    if source:
        query = query.where(Candidate.source == source)

    candidates = db.execute(query.order_by(Candidate.created_at.desc())).scalars().all()
    candidates.sort(
        key=lambda c: c.latest_entry().created_at if c.latest_entry() else c.created_at,
        reverse=True,
    )
    cards = [_card_context(db, c, last_seen_at) for c in candidates]

    available_sources = [
        row[0] for row in db.execute(select(Candidate.source).distinct().order_by(Candidate.source)).all()
    ]

    user.last_seen_at = datetime.now(timezone.utc)
    db.commit()

    return templates.TemplateResponse(
        request,
        "feed.html",
        {
            "cards": cards,
            "user": user,
            "statuses": list(CandidateStatus),
            "sources": available_sources,
            "source_labels": SOURCE_LABELS,
            "selected_status": selected_status.value if selected_status else "",
            "selected_source": source or "",
        },
    )


@router.get("/candidates/{candidate_id}/card", response_class=HTMLResponse)
def candidate_card(
    candidate_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    candidate = db.get(Candidate, candidate_id)
    if not candidate:
        return HTMLResponse("", status_code=404)
    ctx = _card_context(db, candidate, None)
    return templates.TemplateResponse(request, "_card.html", ctx)


@router.post("/candidates/{candidate_id}/status")
async def update_status(
    candidate_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    candidate = db.get(Candidate, candidate_id)
    if candidate:
        try:
            new_status = CandidateStatus(status)
        except ValueError:
            new_status = None
        if new_status:
            candidate.current_status = new_status
            candidate.status_updated_by = user.id
            candidate.status_updated_at = datetime.now(timezone.utc)
            db.commit()
            await manager.broadcast(
                "status_changed", {"candidate_id": candidate_id, "status": new_status.value}
            )
    return RedirectResponse(url="/", status_code=303)


@router.post("/candidates/{candidate_id}/delete")
async def delete_candidate(
    candidate_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    candidate = db.get(Candidate, candidate_id)
    if candidate:
        db.delete(candidate)
        db.commit()
        await manager.broadcast("candidate_deleted", {"candidate_id": candidate_id})
    return RedirectResponse(url="/", status_code=303)
