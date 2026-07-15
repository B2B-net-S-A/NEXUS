"""Cortex — dedup taksonomii jako SERWIS (safety-net dla zablokowanego alembica).

Wierny port logiki z migracji ``0167_cortex_trust_foundation`` do async, żeby
dało się go odpalić z entrypointu, gdy ``alembic upgrade heads`` na prodzie NIE
dobija do 0167 (prod bywa zaklinowany na starszej rewizji — schemat trzyma
safety-net, ale DANE/UPDATE trzeba domknąć osobno; patrz
``~/.claude/rules`` „entrypoint safety-net").

Bezpieczne z konstrukcji: scala WYŁĄCZNIE skille o identycznym
``lower(canonical_name)`` (czyli faktyczne duplikaty case) + 5 par semantycznych;
repin PRZED delete (zero utraty faktów/aliasów); wywoływane w transakcji
(rollback przy błędzie → worst case brak zmiany); idempotentne (po scaleniu
grupy są 1-elementowe → no-op). Na końcu zakłada funkcyjne unique guardy.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_EXPLICIT_MERGES = [
    ("kafka", "apache kafka"),
    ("express", "express.js"),
    ("node", "node.js"),
    ("rest", "rest api"),
    ("vue", "vue.js"),
]


async def _merge_pair(db: AsyncSession, loser_id: int, survivor_id: int) -> None:
    # 1. Przepnij fakty loser, które NIE kolidują z faktem survivora.
    await db.execute(
        text(
            """
            UPDATE cortex_skill_facts f
               SET skill_id = :sur
             WHERE f.skill_id = :los
               AND NOT EXISTS (
                   SELECT 1 FROM cortex_skill_facts f2
                    WHERE f2.candidate_id = f.candidate_id
                      AND f2.skill_id = :sur
                      AND f2.source = f.source)
            """
        ),
        {"sur": survivor_id, "los": loser_id},
    )
    # 2. Kolidujące resztki loser — odrzuć (survivor już ma taki fakt).
    await db.execute(
        text("DELETE FROM cortex_skill_facts WHERE skill_id = :los"),
        {"los": loser_id},
    )
    # 3. Przepnij aliasy (alias globalnie UNIQUE → brak kolizji na repin).
    await db.execute(
        text("UPDATE skill_aliases SET skill_id = :sur WHERE skill_id = :los"),
        {"sur": survivor_id, "los": loser_id},
    )
    # 4. Canonical loser zostaje aliasem survivora.
    await db.execute(
        text(
            """
            INSERT INTO skill_aliases (skill_id, alias)
            SELECT :sur, lower(canonical_name) FROM skills WHERE id = :los
            ON CONFLICT (alias) DO NOTHING
            """
        ),
        {"sur": survivor_id, "los": loser_id},
    )
    # 5. Usuń loser skill.
    await db.execute(text("DELETE FROM skills WHERE id = :los"), {"los": loser_id})


async def dedup_taxonomy(db: AsyncSession) -> dict:
    """Scal duplikaty taksonomii + załóż guard-indexy. Zwraca staty (idempotentne)."""
    rows = (await db.execute(text("SELECT id, canonical_name FROM skills"))).all()
    if not rows:
        return {"skills": 0, "merged": 0, "guards": False}

    alias_counts = dict(
        (
            await db.execute(
                text("SELECT skill_id, count(*) FROM skill_aliases GROUP BY skill_id")
            )
        ).all()
    )

    groups: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for sid, name in rows:
        groups[name.lower()].append((sid, name))

    def pick_survivor(members: list[tuple[int, str]]) -> int:
        # Preferuj Title-Case (name != lower → False sortuje pierwsze), potem
        # więcej aliasów, potem najniższe id — deterministycznie (parytet z 0167).
        return sorted(
            members,
            key=lambda m: (m[1] == m[1].lower(), -alias_counts.get(m[0], 0), m[0]),
        )[0][0]

    def group_survivor(lowername: str):
        members = groups.get(lowername)
        if not members:
            return None
        return members[0][0] if len(members) == 1 else pick_survivor(members)

    mapping: dict[int, int] = {}

    # Pass 1 — duplikaty case-insensitive.
    for members in groups.values():
        if len(members) > 1:
            survivor = pick_survivor(members)
            for sid, _name in members:
                if sid != survivor:
                    mapping[sid] = survivor

    # Pass 2 — pary semantyczne.
    for loser_name, sur_name in _EXPLICIT_MERGES:
        los = group_survivor(loser_name)
        sur = group_survivor(sur_name)
        if los and sur and los != sur:
            mapping[los] = sur

    def final(sid: int) -> int:
        seen: set[int] = set()
        while sid in mapping and sid not in seen:
            seen.add(sid)
            sid = mapping[sid]
        return sid

    merged = 0
    for loser_id in sorted(mapping):
        survivor_id = final(loser_id)
        if survivor_id != loser_id:
            await _merge_pair(db, loser_id, survivor_id)
            merged += 1

    # Dedup aliasów case-insensitive (zwykle no-op — aliasy są lowercase).
    await db.execute(
        text(
            """
            DELETE FROM skill_aliases a
             USING skill_aliases b
             WHERE a.id > b.id AND lower(a.alias) = lower(b.alias)
            """
        )
    )

    # Guard na przyszłość — funkcyjne unique po lower() (po scaleniu duplikatów).
    await db.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_skills_canonical_lower "
            "ON skills (lower(canonical_name))"
        )
    )
    await db.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_aliases_alias_lower "
            "ON skill_aliases (lower(alias))"
        )
    )

    return {"skills": len(rows), "merged": merged, "guards": True}
