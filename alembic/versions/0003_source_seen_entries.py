"""add source_seen_entries (dedup/progress tracking for search-based sources like SuperJob)

Revision ID: 0003_source_seen_entries
Revises: 0002_global_channels
Create Date: 2026-09-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_source_seen_entries"
down_revision: Union[str, None] = "0002_global_channels"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_seen_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("search_query_id", sa.Integer(), sa.ForeignKey("search_queries.id"), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    with op.batch_alter_table("source_seen_entries") as batch_op:
        batch_op.create_unique_constraint(
            "uq_source_seen_entries_source_search_external",
            ["source", "search_query_id", "external_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("source_seen_entries") as batch_op:
        batch_op.drop_constraint("uq_source_seen_entries_source_search_external", type_="unique")
    op.drop_table("source_seen_entries")
