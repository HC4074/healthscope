"""Add durable CMS hospital ingestion run observability.

Revision ID: 20260724_03
Revises: 20260724_02
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260724_03"
down_revision: str | None = "20260724_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create durable lifecycle records for hospital ingestion runs."""

    op.create_table(
        "hospital_ingestion_runs",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("source_dataset_id", sa.String(length=32), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expected_count", sa.Integer(), nullable=True),
        sa.Column("fetched_count", sa.Integer(), nullable=False),
        sa.Column("upserted_count", sa.Integer(), nullable=False),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("request_attempts", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.CheckConstraint(
            "status IN ('started', 'succeeded', 'failed')",
            name=op.f("ck_hospital_ingestion_runs_status_valid"),
        ),
        sa.CheckConstraint(
            "expected_count IS NULL OR expected_count >= 0",
            name=op.f("ck_hospital_ingestion_runs_expected_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "fetched_count >= 0",
            name=op.f("ck_hospital_ingestion_runs_fetched_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "upserted_count >= 0",
            name=op.f("ck_hospital_ingestion_runs_upserted_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "pages >= 0",
            name=op.f("ck_hospital_ingestion_runs_pages_nonnegative"),
        ),
        sa.CheckConstraint(
            "request_attempts >= 0",
            name=op.f("ck_hospital_ingestion_runs_request_attempts_nonnegative"),
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_hospital_ingestion_runs")),
    )
    op.create_index(
        "ix_hospital_ingestion_runs_dataset_started_at",
        "hospital_ingestion_runs",
        ["source_dataset_id", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove hospital ingestion run observability."""

    op.drop_index(
        "ix_hospital_ingestion_runs_dataset_started_at",
        table_name="hospital_ingestion_runs",
    )
    op.drop_table("hospital_ingestion_runs")
