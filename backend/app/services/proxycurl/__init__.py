"""Proxycurl LinkedIn profile integration.

- `client`: thin async HTTP wrapper over Proxycurl API (retry, rate-limit).
- `diff`: pure, unit-testable change-detection between snapshots.
- `sync`: orchestrates one-candidate-at-a-time fetch + diff + persist.
"""

from app.services.proxycurl.client import (
    ProfileNotFound,
    ProxycurlClient,
    ProxycurlError,
    ProxycurlProfile,
    normalize_linkedin_url,
)
from app.services.proxycurl.diff import ChangeResult, compute_change
from app.services.proxycurl.sync import (
    SyncResult,
    prune_old_snapshots,
    sync_candidate_linkedin,
)

__all__ = [
    "ChangeResult",
    "ProfileNotFound",
    "ProxycurlClient",
    "ProxycurlError",
    "ProxycurlProfile",
    "SyncResult",
    "compute_change",
    "normalize_linkedin_url",
    "prune_old_snapshots",
    "sync_candidate_linkedin",
]
