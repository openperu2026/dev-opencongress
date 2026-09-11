"""add creacion_comision to type_motion enum

Revision ID: 8b1c4d7a6e2f
Revises: 7fa069b49163
Create Date: 2026-09-11 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "8b1c4d7a6e2f"
down_revision: Union[str, Sequence[str], None] = "7fa069b49163"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 2026-2031 Cámara de Diputados term (backend/core/enums.py
# TypeMotion.CREACION_COMISION) introduced a new motion-type category to
# cover the "Conformación de Comisiones de Investigación/Especiales" labels,
# which need their own Postgres native enum value or inserts fail with
# psycopg.errors.InvalidTextRepresentation (same class of gap as 7fa069b49163
# for Proponents).
NEW_TYPE_MOTION_VALUES = ("Creación de Comisión",)


def upgrade() -> None:
    """Upgrade schema."""
    for value in NEW_TYPE_MOTION_VALUES:
        op.execute(f"ALTER TYPE type_motion ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError(
        "Postgres does not support removing enum values; rolling back the "
        "type_motion value addition requires restoring from a pre-migration "
        "backup."
    )
