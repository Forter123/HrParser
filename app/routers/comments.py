from datetime import datetime

from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Comment, User
from app.realtime import manager

router = APIRouter()


@router.post("/candidates/{candidate_id}/comments")
async def add_comment(
    candidate_id: int,
    text: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    text = text.strip()
    if text:
        comment = Comment(candidate_id=candidate_id, user_id=user.id, text=text)
        db.add(comment)
        db.commit()
        db.refresh(comment)
        await manager.broadcast(
            "comment_added",
            {
                "candidate_id": candidate_id,
                "author": user.name,
                "text": comment.text,
                "created_at": comment.created_at.isoformat(),
            },
        )
    return RedirectResponse(url="/", status_code=303)
