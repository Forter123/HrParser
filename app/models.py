import enum
from datetime import datetime

from sqlalchemy import (
    String, Text, Integer, BigInteger, Boolean, DateTime, ForeignKey, Enum, JSON, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class SearchStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    closed = "closed"


class CandidateStatus(str, enum.Enum):
    interesting = "интересно"
    not_fit = "мимо"
    in_touch = "на связи"
    in_progress = "в работе"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SearchQuery(Base):
    __tablename__ = "search_queries"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    keywords: Mapped[str] = mapped_column(Text)  # comma-separated
    # Comma-separated Source.SOURCE_KEY values this search runs on. Empty
    # string means "all sources" (the default — existing searches created
    # before this field existed keep working exactly as before).
    sources: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[SearchStatus] = mapped_column(Enum(SearchStatus, name="search_status"), default=SearchStatus.active)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def keyword_list(self) -> list[str]:
        return [k.strip().lower() for k in self.keywords.split(",") if k.strip()]

    def source_keys(self) -> list[str]:
        return [s.strip() for s in self.sources.split(",") if s.strip()]

    def runs_on_source(self, source_key: str) -> bool:
        selected = self.source_keys()
        return not selected or source_key in selected


class TelegramChannel(Base):
    """Global pool of Telegram channels. Every active search scans all of them."""

    __tablename__ = "telegram_channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True)
    last_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceSeenEntry(Base):
    """Tracks which items a search-based source (e.g. SuperJob) has already
    surfaced for a given search, so re-running the same keyword search on the
    next poll doesn't re-ingest unchanged results as if they were new."""

    __tablename__ = "source_seen_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50))
    search_query_id: Mapped[int] = mapped_column(ForeignKey("search_queries.id"))
    external_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50), default="telegram")
    external_sender_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    current_status: Mapped[CandidateStatus] = mapped_column(
        Enum(CandidateStatus, name="candidate_status"), default=CandidateStatus.interesting
    )
    status_updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    entries: Mapped[list["CandidateEntry"]] = relationship(back_populates="candidate", cascade="all, delete-orphan", order_by="CandidateEntry.created_at")
    comments: Mapped[list["Comment"]] = relationship(back_populates="candidate", cascade="all, delete-orphan", order_by="Comment.created_at")

    def latest_entry(self) -> "CandidateEntry | None":
        return self.entries[-1] if self.entries else None


class CandidateEntry(Base):
    __tablename__ = "candidate_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    search_query_id: Mapped[int | None] = mapped_column(ForeignKey("search_queries.id"), nullable=True)
    message_text: Mapped[str] = mapped_column(Text)
    message_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_channel: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_update: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    candidate: Mapped["Candidate"] = relationship(back_populates="entries")


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    candidate: Mapped["Candidate"] = relationship(back_populates="comments")
    user: Mapped["User"] = relationship()
