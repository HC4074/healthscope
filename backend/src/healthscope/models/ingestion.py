"""Persistence model for healthcare data ingestion run observability."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from healthscope.database import Base


class HospitalIngestionRun(Base):
    """Durable lifecycle and progress for one CMS hospital ingestion run."""

    __tablename__ = "hospital_ingestion_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('started', 'succeeded', 'failed')",
            name="status_valid",
        ),
        CheckConstraint(
            "expected_count IS NULL OR expected_count >= 0",
            name="expected_count_nonnegative",
        ),
        CheckConstraint("fetched_count >= 0", name="fetched_count_nonnegative"),
        CheckConstraint("upserted_count >= 0", name="upserted_count_nonnegative"),
        CheckConstraint("pages >= 0", name="pages_nonnegative"),
        CheckConstraint("request_attempts >= 0", name="request_attempts_nonnegative"),
        Index(
            "ix_hospital_ingestion_runs_dataset_started_at",
            "source_dataset_id",
            "started_at",
        ),
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_dataset_id: Mapped[str] = mapped_column(String(32), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    expected_count: Mapped[int | None] = mapped_column(Integer)
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    upserted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    request_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_type: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(String(1000))
