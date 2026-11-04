"""Add idempotency keys to ride requests.

Revision ID: c4d5e6f7a8b9
Revises: ab7c1d2e3f4a
Create Date: 2026-11-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "ab7c1d2e3f4a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ride_requests",
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
    )
    op.create_unique_constraint(
        "uq_ride_requests_passenger_idempotency_key",
        "ride_requests",
        ["passenger_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_ride_requests_passenger_idempotency_key",
        "ride_requests",
        type_="unique",
    )
    op.drop_column("ride_requests", "idempotency_key")
