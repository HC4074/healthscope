"""Add completion metadata for CMS hospital snapshots.

Revision ID: 20260724_02
Revises: 20260719_01
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260724_02"
down_revision: str | None = "20260719_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create verified completion markers for daily hospital snapshots."""

    op.create_table(
        "hospital_snapshot_completions",
        sa.Column("source_dataset_id", sa.String(length=32), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "record_count >= 0",
            name=op.f("ck_hospital_snapshot_completions_record_count_nonnegative"),
        ),
        sa.PrimaryKeyConstraint(
            "source_dataset_id",
            "snapshot_date",
            name=op.f("pk_hospital_snapshot_completions"),
        ),
    )
    op.create_index(
        "ix_hospital_snapshot_completions_retrieved_at",
        "hospital_snapshot_completions",
        ["retrieved_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove hospital snapshot completion metadata."""

    op.drop_index(
        "ix_hospital_snapshot_completions_retrieved_at",
        table_name="hospital_snapshot_completions",
    )
    op.drop_table("hospital_snapshot_completions")
