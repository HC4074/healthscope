"""Persistence boundaries for healthcare data."""

from healthscope.repositories.hospitals import (
    get_latest_complete_hospital_snapshot,
    mark_hospital_snapshot_complete,
    upsert_hospital_snapshots,
)
from healthscope.repositories.ingestion_runs import (
    finish_hospital_ingestion_run,
    get_latest_hospital_ingestion_status,
    start_hospital_ingestion_run,
    update_hospital_ingestion_run,
)

__all__ = [
    "finish_hospital_ingestion_run",
    "get_latest_complete_hospital_snapshot",
    "get_latest_hospital_ingestion_status",
    "mark_hospital_snapshot_complete",
    "start_hospital_ingestion_run",
    "update_hospital_ingestion_run",
    "upsert_hospital_snapshots",
]
