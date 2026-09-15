"""make telegram_channels a global pool shared by all searches

Revision ID: 0002_global_channels
Revises: 0001_initial
Create Date: 2026-09-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_global_channels"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEED_CHANNELS = [
    "design_vacancy",
    "Koteyka_Freelancer",
    "fordev",
    "NUTRA_TOVARKA_CHAT",
    "arbitraj_hr_vakansii",
    "works_cpa",
    "workingincrypto",
    "hr_affiliate",
    "aff_job",
    "arbitraj_traffica_chat",
    "analysts_hunter",
    "javascript_vakansii_rabota_chat",
    "arbitrage_vacancy",
    "Arbitrazh_vakansii_rabota",
    "igaming_offer",
    "jtbl_vacancy",
    "reg2bet",
    "iGaming_work",
    "seohr",
    "cryptoheadhunter",
    "digital_jobster",
    "mediabuyers_lenkep",
    "payments_highrisk",
    "it_vakansii_jobs",
    "igaming_hunter",
]


def upgrade() -> None:
    with op.batch_alter_table("telegram_channels") as batch_op:
        batch_op.drop_column("search_query_id")
        batch_op.create_unique_constraint("uq_telegram_channels_username", ["username"])

    channels_table = sa.table(
        "telegram_channels",
        sa.column("username", sa.String),
    )
    op.bulk_insert(channels_table, [{"username": name} for name in SEED_CHANNELS])


def downgrade() -> None:
    with op.batch_alter_table("telegram_channels") as batch_op:
        batch_op.drop_constraint("uq_telegram_channels_username", type_="unique")
        batch_op.add_column(sa.Column("search_query_id", sa.Integer(), sa.ForeignKey("search_queries.id"), nullable=True))
