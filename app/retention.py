"""Conservative retention defaults. No automatic deletion is enabled."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RetentionPolicy:
    raw_days: int = 90
    summary_days: int = 180
    deletion_mode: str = "review"
    preserve_active_strategy_evidence: bool = True
    # Until verified archival, source links, exports and approval exist, nothing is purged.
    deletion_enabled: bool = False


RETENTION = RetentionPolicy()
