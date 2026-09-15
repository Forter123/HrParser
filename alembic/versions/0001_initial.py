"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    search_status = sa.Enum("active", "paused", "closed", name="search_status")
    candidate_status = sa.Enum(
        "интересно", "мимо", "на связи", "в работе", name="candidate_status"
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, index=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "search_queries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("keywords", sa.Text(), nullable=False),
        sa.Column("status", search_status, nullable=False, server_default="active"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "telegram_channels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("search_query_id", sa.Integer(), sa.ForeignKey("search_queries.id"), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("last_message_id", sa.BigInteger(), nullable=True),
        sa.Column("added_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="telegram"),
        sa.Column("external_sender_id", sa.String(255), nullable=True, index=True),
        sa.Column("sender_name", sa.String(255), nullable=True),
        sa.Column("dedup_key", sa.String(64), nullable=True, index=True),
        sa.Column("current_status", candidate_status, nullable=False, server_default="интересно"),
        sa.Column("status_updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "candidate_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("candidates.id"), nullable=False),
        sa.Column("search_query_id", sa.Integer(), sa.ForeignKey("search_queries.id"), nullable=True),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("message_link", sa.String(500), nullable=True),
        sa.Column("source_channel", sa.String(255), nullable=True),
        sa.Column("is_update", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("candidates.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("comments")
    op.drop_table("candidate_entries")
    op.drop_table("candidates")
    op.drop_table("telegram_channels")
    op.drop_table("search_queries")
    op.drop_table("users")
    sa.Enum(name="candidate_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="search_status").drop(op.get_bind(), checkfirst=True)
