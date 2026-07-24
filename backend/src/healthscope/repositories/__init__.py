"""Persistence boundaries for healthcare data."""

from healthscope.repositories.hospitals import (
    get_latest_complete_hospital_snapshot,
    mark_hospital_snapshot_complete,
    upsert_hospital_snapshots,
)

__all__ = [
    "get_latest_complete_hospital_snapshot",
    "mark_hospital_snapshot_complete",
    "upsert_hospital_snapshots",
]
