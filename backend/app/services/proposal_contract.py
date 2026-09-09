"""Version proposal snapshots independently of mutable data invalidation flags."""

import hashlib

PROPOSAL_INPUT_VERSION = "proposal-canonical-fit-v2"


def proposal_fingerprint(query_text: str) -> str:
    return f"{PROPOSAL_INPUT_VERSION}:{hashlib.sha256(query_text.encode()).hexdigest()}"


def snapshot_is_stale(snapshot) -> bool:
    if snapshot.status != "ready":
        return bool(snapshot.stale)
    return bool(snapshot.stale) or not (snapshot.input_fingerprint or "").startswith(
        f"{PROPOSAL_INPUT_VERSION}:"
    )
