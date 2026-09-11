"""add otros_poderes to proponents enum

Revision ID: 2f5a8c1d9b3e
Revises: 8b1c4d7a6e2f
Create Date: 2026-09-11 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "2f5a8c1d9b3e"
down_revision: Union[str, Sequence[str], None] = "8b1c4d7a6e2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# "Otros Poderes del Estado" (backend/core/enums.py Proponents.OTROS_PODERES)
# is Congreso's own generic catch-all desProponente label (confirmed live
# 2026-09-10, RawBill id=00089-2026-2031-CD), added to the Python enum but
# not yet to the Postgres native enum type, so any bill proposed under this
# label fails to insert with psycopg.errors.InvalidTextRepresentation (same
# class of gap as 7fa069b49163).
NEW_PROPONENT_VALUES = ("Otros Poderes del Estado",)


def upgrade() -> None:
    """Upgrade schema."""
    for value in NEW_PROPONENT_VALUES:
        op.execute(f"ALTER TYPE proponents ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError(
        "Postgres does not support removing enum values; rolling back the "
        "proponents value addition requires restoring from a pre-migration "
        "backup."
    )
