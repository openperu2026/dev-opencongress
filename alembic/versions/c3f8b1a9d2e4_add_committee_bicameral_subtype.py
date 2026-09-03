"""Widen ck_organization_subtype_matches_type for the new joint/bicameral
committee subtype (Comisión Bicameral)

Revision ID: c3f8b1a9d2e4
Revises: 9a6e0e2f4b7c
Create Date: 2026-09-02 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c3f8b1a9d2e4"
down_revision: Union[str, Sequence[str], None] = "9a6e0e2f4b7c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "ck_organization_subtype_matches_type"

OLD_COMMITTEE_SUBTYPES = (
    "'Comisiones Investigadoras', 'Grupo de Trabajo', "
    "'Subcomisión de Acusaciones Constitucionales', "
    "'Subcomisión de Control Político', "
    "'Comisión de Levantamiento de Inmunidad Parlamentaria', "
    "'Comisión Ordinaria', 'Comisión Ordinaria Legislativa', "
    "'Comisión Ordinaria No Legislativa', "
    "'Sub Comisión de Seguimiento del TLC', "
    "'Comisiones Especiales', 'Comisión de Ética Parlamentaria'"
)
NEW_COMMITTEE_SUBTYPES = (
    "'Comisiones Investigadoras', 'Grupo de Trabajo', "
    "'Subcomisión de Acusaciones Constitucionales', "
    "'Subcomisión de Control Político', "
    "'Comisión de Levantamiento de Inmunidad Parlamentaria', "
    "'Comisión Ordinaria', 'Comisión Ordinaria Legislativa', "
    "'Comisión Ordinaria No Legislativa', 'Comisión Bicameral', "
    "'Sub Comisión de Seguimiento del TLC', "
    "'Comisiones Especiales', 'Comisión de Ética Parlamentaria'"
)
ADMIN_SUBTYPES = (
    "'Junta de Portavoces', 'Mesa Directiva', 'Comisión Permanente', "
    "'Consejo Directivo'"
)


def _constraint_sql(committee_subtypes: str) -> str:
    return f"""
        (
            org_type = 'Comisión'
            AND org_subtype IN ({committee_subtypes})
        )
        OR
        (
            org_type = 'Administrativo'
            AND org_subtype IN ({ADMIN_SUBTYPES})
        )
        OR
        (
            org_type NOT IN ('Comisión', 'Administrativo')
            AND org_subtype IS NULL
        )
    """


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(CONSTRAINT_NAME, "organizations", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "organizations",
        _constraint_sql(NEW_COMMITTEE_SUBTYPES),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(CONSTRAINT_NAME, "organizations", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "organizations",
        _constraint_sql(OLD_COMMITTEE_SUBTYPES),
    )
