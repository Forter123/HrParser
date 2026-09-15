from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import TelegramChannel, User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/channels", response_class=HTMLResponse)
def list_channels(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    channels = db.execute(select(TelegramChannel).order_by(TelegramChannel.created_at.desc())).scalars().all()
    error = request.query_params.get("error")
    return templates.TemplateResponse(request, "channels.html", {"channels": channels, "user": user, "error": error})


@router.post("/channels")
def add_channel(
    request: Request,
    username: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    username = username.strip().lstrip("@")
    if username:
        exists = db.execute(
            select(TelegramChannel).where(TelegramChannel.username.ilike(username))
        ).scalar_one_or_none()
        if exists:
            return RedirectResponse(url="/channels?error=duplicate", status_code=303)
        db.add(TelegramChannel(username=username, added_by=user.id))
        db.commit()
    return RedirectResponse(url="/channels", status_code=303)


@router.post("/channels/{channel_id}/delete")
def delete_channel(
    channel_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    channel = db.get(TelegramChannel, channel_id)
    if channel:
        db.delete(channel)
        db.commit()
    return RedirectResponse(url="/channels", status_code=303)
