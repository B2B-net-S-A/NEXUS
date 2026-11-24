"""Postgres stagingu nie jest pierwszą ofiarą OOM-killera maszyny Dockera.

24.11.2026 jądro dwa razy zabiło proces Postgresa stagingu przy braku pamięci
w całej maszynie (`global_oom`), bo każdy proces liczy w RSS 2 GB shared_buffers.
→ docs/claude/podstawy/staging-na-laptopie.md, „Pamięć maszyny Dockera”.
"""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def test_staging_postgres_is_not_first_oom_victim() -> None:
    postgres = yaml.safe_load((REPO / "docker-compose.staging.yml").read_text())["services"]["postgres"]
    # -1000 wyłączyłoby zabijanie w ogóle: przy własnym limicie kontener by stanął.
    assert -1000 < postgres["oom_score_adj"] <= -100
    # Limit kontenera zostaje: łapie Postgresa, który urośnie sam.
    assert postgres["mem_limit"]
