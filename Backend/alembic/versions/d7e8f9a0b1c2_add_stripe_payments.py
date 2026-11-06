"""Add Stripe-backed payment records.

Revision ID: d7e8f9a0b1c2
Revises: c4d5e6f7a8b9
Create Date: 2026-11-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ride_request_id", sa.Integer(), nullable=False),
        sa.Column("passenger_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "REQUIRES_ACTION",
                "PROCESSING",
                "SUCCEEDED",
                "FAILED",
                "CANCELLED",
                "REFUNDED",
                name="payment_status",
            ),
            nullable=False,
        ),
        sa.Column("stripe_payment_intent_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_charge_id", sa.String(length=255), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount >= 0", name="ck_payments_amount_non_negative"),
        sa.CheckConstraint("char_length(currency) = 3", name="ck_payments_currency_length"),
        sa.ForeignKeyConstraint(["passenger_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["ride_request_id"], ["ride_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ride_request_id"),
        sa.UniqueConstraint("stripe_charge_id"),
        sa.UniqueConstraint("stripe_payment_intent_id"),
    )
    op.create_index("ix_payments_ride_request_id", "payments", ["ride_request_id"])
    op.create_index("ix_payments_passenger_id", "payments", ["passenger_id"])
    op.create_index("ix_payments_status", "payments", ["status"])
    op.create_index("ix_payments_stripe_payment_intent_id", "payments", ["stripe_payment_intent_id"])


def downgrade() -> None:
    op.drop_index("ix_payments_stripe_payment_intent_id", table_name="payments")
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index("ix_payments_passenger_id", table_name="payments")
    op.drop_index("ix_payments_ride_request_id", table_name="payments")
    op.drop_table("payments")
