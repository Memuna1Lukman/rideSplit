"""Enforce unique driver plate numbers.

Revision ID: ab7c1d2e3f4a
Revises: 3fd022df716a
Create Date: 2026-11-02
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "ab7c1d2e3f4a"
down_revision: Union[str, Sequence[str], None] = "3fd022df716a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_driver_profiles_plate_number", "driver_profiles", ["plate_number"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_driver_profiles_plate_number", "driver_profiles", type_="unique"
    )
