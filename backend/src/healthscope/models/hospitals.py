"""Persistence model for historical CMS hospital snapshots."""

from datetime import UTC, date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from healthscope.database import Base
from healthscope.schemas.hospitals import Hospital


class HospitalSnapshot(Base):
    """One facility observation in a daily CMS dataset snapshot."""

    __tablename__ = "hospital_snapshots"
    __table_args__ = (
        CheckConstraint("overall_rating BETWEEN 1 AND 5", name="overall_rating_range"),
        CheckConstraint("length(state) = 2", name="state_length"),
        Index("ix_hospital_snapshots_snapshot_date_state", "snapshot_date", "state"),
    )

    source_dataset_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    facility_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    facility_name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    zip_code: Mapped[str] = mapped_column(String(10), nullable=False)
    county: Mapped[str] = mapped_column(String(128), nullable=False)
    telephone: Mapped[str] = mapped_column(String(32), nullable=False)
    hospital_type: Mapped[str] = mapped_column(String(128), nullable=False)
    ownership: Mapped[str] = mapped_column(String(128), nullable=False)
    emergency_services: Mapped[bool] = mapped_column(Boolean, nullable=False)
    birthing_friendly: Mapped[bool | None] = mapped_column(Boolean)
    overall_rating: Mapped[int | None] = mapped_column(Integer)

    @classmethod
    def from_hospital(
        cls,
        hospital: Hospital,
        *,
        source_dataset_id: str,
        retrieved_at: datetime,
    ) -> "HospitalSnapshot":
        """Map a validated public CMS hospital record to a dated snapshot."""

        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("Hospital snapshot retrieval timestamps must include a timezone")
        if not 1 <= len(source_dataset_id) <= 32:
            raise ValueError("Hospital snapshot dataset IDs must contain 1 to 32 characters")
        retrieved_at_utc = retrieved_at.astimezone(UTC)
        return cls(
            source_dataset_id=source_dataset_id,
            snapshot_date=retrieved_at_utc.date(),
            retrieved_at=retrieved_at_utc,
            **hospital.model_dump(),
        )


class HospitalSnapshotCompletion(Base):
    """Completion marker for one fully validated daily CMS snapshot."""

    __tablename__ = "hospital_snapshot_completions"
    __table_args__ = (
        CheckConstraint("record_count >= 0", name="record_count_nonnegative"),
        Index(
            "ix_hospital_snapshot_completions_retrieved_at",
            "retrieved_at",
        ),
    )

    source_dataset_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
