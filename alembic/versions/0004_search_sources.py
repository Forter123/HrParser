"""add sources column to search_queries (per-search source selection)

Revision ID: 0004_search_sources
Revises: 0003_source_seen_entries
Create Date: 2026-09-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_search_sources"
down_revision: Union[str, None] = "0003_source_seen_entries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("search_queries") as batch_op:
        batch_op.add_column(
            sa.Column("sources", sa.Text(), nullable=False, server_default="")
        )


def downgrade() -> None:
    with op.batch_alter_table("search_queries") as batch_op:
        batch_op.drop_column("sources")
