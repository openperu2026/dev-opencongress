"""Editions to step_id

Revision ID: d7f1722121a4
Revises: 595916aec37b
Create Date: 2026-08-04 17:19:16.051456

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d7f1722121a4"
down_revision: Union[str, Sequence[str], None] = "595916aec37b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BILL_DOC_PK = "pk_raw_bills_documents"
BILL_PAGE_PK = "pk_raw_bill_pages"
MOTION_DOC_PK = "pk_raw_motion_documents"
MOTION_PAGE_PK = "pk_raw_motion_pages"

BILL_PAGE_FK = "fk_raw_bill_pages_document"
MOTION_PAGE_FK = "fk_raw_motion_pages_document"


def _drop_constraints():
    # Foreign keys
    op.drop_constraint(
        BILL_PAGE_FK,
        "raw_bill_pages",
        type_="foreignkey",
    )

    op.drop_constraint(
        MOTION_PAGE_FK,
        "raw_motion_pages",
        type_="foreignkey",
    )

    # Primary keys
    op.drop_constraint(
        BILL_DOC_PK,
        "raw_bill_documents",
        type_="primary",
    )

    op.drop_constraint(
        BILL_PAGE_PK,
        "raw_bill_pages",
        type_="primary",
    )

    op.drop_constraint(
        MOTION_DOC_PK,
        "raw_motion_documents",
        type_="primary",
    )

    op.drop_constraint(
        MOTION_PAGE_PK,
        "raw_motion_pages",
        type_="primary",
    )


def _create_constraints():
    # Primary keys
    op.create_primary_key(
        BILL_DOC_PK,
        "raw_bill_documents",
        [
            "bill_id",
            "step_id",
            "file_id",
        ],
    )

    op.create_primary_key(
        BILL_PAGE_PK,
        "raw_bill_pages",
        [
            "bill_id",
            "step_id",
            "file_id",
            "page_num",
            "ocr_model",
        ],
    )

    op.create_primary_key(
        MOTION_DOC_PK,
        "raw_motion_documents",
        [
            "motion_id",
            "step_id",
            "file_id",
        ],
    )

    op.create_primary_key(
        MOTION_PAGE_PK,
        "raw_motion_pages",
        [
            "motion_id",
            "step_id",
            "file_id",
            "page_num",
            "ocr_model",
        ],
    )

    # Foreign keys
    op.create_foreign_key(
        BILL_PAGE_FK,
        "raw_bill_pages",
        "raw_bill_documents",
        [
            "bill_id",
            "step_id",
            "file_id",
        ],
        [
            "bill_id",
            "step_id",
            "file_id",
        ],
    )

    op.create_foreign_key(
        MOTION_PAGE_FK,
        "raw_motion_pages",
        "raw_motion_documents",
        [
            "motion_id",
            "step_id",
            "file_id",
        ],
        [
            "motion_id",
            "step_id",
            "file_id",
        ],
    )


def _alter_columns_to_integer():
    # Parent tables first
    for table in (
        "raw_bill_documents",
        "raw_motion_documents",
    ):
        op.alter_column(
            table,
            "step_id",
            existing_type=sa.String(),
            type_=sa.Integer(),
            postgresql_using="step_id::integer",
        )

        op.alter_column(
            table,
            "file_id",
            existing_type=sa.String(),
            type_=sa.Integer(),
            postgresql_using="file_id::integer",
        )

    # Child tables
    for table in (
        "raw_bill_pages",
        "raw_motion_pages",
    ):
        op.alter_column(
            table,
            "step_id",
            existing_type=sa.String(),
            type_=sa.Integer(),
            postgresql_using="step_id::integer",
        )

        op.alter_column(
            table,
            "file_id",
            existing_type=sa.String(),
            type_=sa.Integer(),
            postgresql_using="file_id::integer",
        )


def upgrade() -> None:
    """Convert step_id and file_id from varchar to integer."""

    _drop_constraints()

    _alter_columns_to_integer()

    _create_constraints()


def downgrade() -> None:
    """Convert step_id and file_id back to varchar."""

    _drop_constraints()

    for table in (
        "raw_bill_documents",
        "raw_bill_pages",
        "raw_motion_documents",
        "raw_motion_pages",
    ):
        op.alter_column(
            table,
            "step_id",
            existing_type=sa.Integer(),
            type_=sa.String(),
            postgresql_using="step_id::text",
        )

        op.alter_column(
            table,
            "file_id",
            existing_type=sa.Integer(),
            type_=sa.String(),
            postgresql_using="file_id::text",
        )

    _create_constraints()
