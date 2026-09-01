"""Tests for Traffit-style advanced search on GET /api/candidates.

Three buckets: q_all (AND), q_any (OR), q_none (NOT). Each phrase matches
case-insensitive ILIKE across searchable fields (see
app.services.advanced_candidate_search._SEARCHABLE_COLUMNS).
"""

from __future__ import annotations

import uuid
from typing import Optional

import pytest
from httpx import AsyncClient


async def _seed_candidate(*, raw_cv: str, tags: Optional[list[str]] = None) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Adv",
            lastname=f"Search-{uuid.uuid4().hex[:6]}",
            email=f"adv-{uuid.uuid4().hex[:8]}@example.com",
            raw_cv_text=raw_cv,
            tags=tags or [],
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _cleanup(candidate_ids: list[int]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        for cid in candidate_ids:
            await db.execute(delete(Candidate).where(Candidate.id == cid))
        await db.commit()


async def _seed_four() -> dict[str, int]:
    a = await _seed_candidate(raw_cv="python react developer senior")
    b = await _seed_candidate(raw_cv="python django backend engineer")
    c = await _seed_candidate(raw_cv="java spring senior architect")
    d = await _seed_candidate(raw_cv="react native mobile junior intern")
    return {"A": a, "B": b, "C": c, "D": d}


@pytest.mark.asyncio
async def test_q_all_and(app_client: AsyncClient, app_auth_headers: dict):
    ids = await _seed_four()
    try:
        r = await app_client.get(
            "/api/candidates?q_all=python&q_all=react&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert ids["A"] in result_ids
        assert ids["B"] not in result_ids
        assert ids["C"] not in result_ids
        assert ids["D"] not in result_ids
    finally:
        await _cleanup(list(ids.values()))


@pytest.mark.asyncio
async def test_q_any_or(app_client: AsyncClient, app_auth_headers: dict):
    ids = await _seed_four()
    try:
        r = await app_client.get(
            "/api/candidates?q_any=django&q_any=spring&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert ids["B"] in result_ids
        assert ids["C"] in result_ids
        assert ids["A"] not in result_ids
        assert ids["D"] not in result_ids
    finally:
        await _cleanup(list(ids.values()))


@pytest.mark.asyncio
async def test_q_any_groups_and_of_ors(app_client: AsyncClient, app_auth_headers: dict):
    """Multiple ANY OR-groups AND together: (python OR java) AND (react OR spring).

    Seed bodies:
      A "python react developer senior"  → python ✓, react ✓     → MATCH
      B "python django backend engineer" → python ✓, (react/spring) ✗ → excluded
      C "java spring senior architect"   → java ✓,   spring ✓    → MATCH
      D "react native mobile junior"     → (python/java) ✗        → excluded
    """
    ids = await _seed_four()
    try:
        r = await app_client.get(
            "/api/candidates?q_any_group=python|java"
            "&q_any_group=react|spring&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert ids["A"] in result_ids
        assert ids["C"] in result_ids
        assert ids["B"] not in result_ids
        assert ids["D"] not in result_ids
    finally:
        await _cleanup(list(ids.values()))


@pytest.mark.asyncio
async def test_legacy_q_any_ands_with_extra_group(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Legacy flat `q_any` (group 0) AND-s with a `q_any_group`.

    (python OR java) [legacy q_any] AND (react OR spring) [q_any_group]
    → same result set as test_q_any_groups_and_of_ors (A, C).
    """
    ids = await _seed_four()
    try:
        r = await app_client.get(
            "/api/candidates?q_any=python&q_any=java"
            "&q_any_group=react|spring&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert ids["A"] in result_ids
        assert ids["C"] in result_ids
        assert ids["B"] not in result_ids
        assert ids["D"] not in result_ids
    finally:
        await _cleanup(list(ids.values()))


@pytest.mark.asyncio
async def test_q_none_not(app_client: AsyncClient, app_auth_headers: dict):
    ids = await _seed_four()
    try:
        r = await app_client.get(
            "/api/candidates?q_none=junior&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert ids["A"] in result_ids
        assert ids["B"] in result_ids
        assert ids["C"] in result_ids
        assert ids["D"] not in result_ids
    finally:
        await _cleanup(list(ids.values()))


@pytest.mark.asyncio
async def test_combination_all_and_none(
    app_client: AsyncClient, app_auth_headers: dict
):
    ids = await _seed_four()
    try:
        r = await app_client.get(
            "/api/candidates?q_all=python&q_none=django&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert ids["A"] in result_ids
        assert ids["B"] not in result_ids
        assert ids["C"] not in result_ids
        assert ids["D"] not in result_ids
    finally:
        await _cleanup(list(ids.values()))


@pytest.mark.asyncio
async def test_multi_word_phrase(app_client: AsyncClient, app_auth_headers: dict):
    ids = await _seed_four()
    try:
        r = await app_client.get(
            "/api/candidates?q_all=react+native&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert ids["D"] in result_ids
        assert (
            ids["A"] not in result_ids
        )  # "python react developer" — no "react native"
    finally:
        await _cleanup(list(ids.values()))


@pytest.mark.asyncio
async def test_simple_q_conjoined_with_q_all(
    app_client: AsyncClient, app_auth_headers: dict
):
    ids = await _seed_four()
    try:
        # simple q=python narrows to {A,B}, q_all=react further narrows to {A}
        r = await app_client.get(
            "/api/candidates?q=python&q_all=react&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert ids["A"] in result_ids
        assert ids["B"] not in result_ids
        assert ids["D"] not in result_ids
    finally:
        await _cleanup(list(ids.values()))


@pytest.mark.asyncio
async def test_no_advanced_params_is_backward_compat(
    app_client: AsyncClient, app_auth_headers: dict
):
    ids = await _seed_four()
    try:
        r = await app_client.get(
            "/api/candidates?page_size=100", headers=app_auth_headers
        )
        assert r.status_code == 200, r.text
        # Seeded candidates are included (we don't assert total — other fixtures
        # may exist in the DB).
        result_ids = {item["id"] for item in r.json()["items"]}
        assert ids["A"] in result_ids
        assert ids["B"] in result_ids
        assert ids["C"] in result_ids
        assert ids["D"] in result_ids
    finally:
        await _cleanup(list(ids.values()))


@pytest.mark.asyncio
async def test_like_metacharacters_are_escaped(
    app_client: AsyncClient, app_auth_headers: dict
):
    # A literal "50%" phrase must not be treated as LIKE wildcard.
    a = await _seed_candidate(raw_cv="python react developer 50% remote")
    b = await _seed_candidate(raw_cv="python django backend engineer")
    try:
        r = await app_client.get(
            "/api/candidates?q_all=50%25&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert a in result_ids
        assert b not in result_ids  # doesn't contain literal "50%"
    finally:
        await _cleanup([a, b])


@pytest.mark.asyncio
async def test_dedupe_case_insensitive(app_client: AsyncClient, app_auth_headers: dict):
    # Supplying the same phrase with different casing should not over-constrain.
    ids = await _seed_four()
    try:
        r = await app_client.get(
            "/api/candidates?q_all=python&q_all=PYTHON&q_all=Python&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert ids["A"] in result_ids
        assert ids["B"] in result_ids
    finally:
        await _cleanup(list(ids.values()))


@pytest.mark.asyncio
async def test_tags_field_is_searched(app_client: AsyncClient, app_auth_headers: dict):
    a = await _seed_candidate(raw_cv="generic cv body", tags=["kubernetes", "aws"])
    b = await _seed_candidate(raw_cv="generic cv body", tags=["gcp"])
    try:
        r = await app_client.get(
            "/api/candidates?q_all=kubernetes&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert a in result_ids
        assert b not in result_ids
    finally:
        await _cleanup([a, b])


@pytest.mark.asyncio
async def test_education_jsonb_is_searched(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Phrase appearing only in education JSONB matches the candidate."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        a = Candidate(
            name="Edu",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"edu-{uuid.uuid4().hex[:8]}@example.com",
            raw_cv_text="unrelated cv body",
            education=[{"school": "MIT", "degree": "PhD Bioinformatics"}],
        )
        b = Candidate(
            name="Edu2",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"edu-{uuid.uuid4().hex[:8]}@example.com",
            raw_cv_text="unrelated cv body",
            education=[{"school": "Harvard", "degree": "MBA"}],
        )
        db.add_all([a, b])
        await db.commit()
        await db.refresh(a)
        await db.refresh(b)
        a_id, b_id = a.id, b.id

    try:
        r = await app_client.get(
            "/api/candidates?q_all=Bioinformatics&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert a_id in result_ids
        assert b_id not in result_ids
    finally:
        async with AsyncSessionLocal() as db:
            for cid in (a_id, b_id):
                await db.execute(delete(Candidate).where(Candidate.id == cid))
            await db.commit()


@pytest.mark.asyncio
async def test_notes_content_is_searched(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Phrase appearing only in a `notes` row links back to the candidate via EXISTS."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.note import Note
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        a = Candidate(
            name="Note",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"note-{uuid.uuid4().hex[:8]}@example.com",
            raw_cv_text="cv has no mention of the magic word",
        )
        b = Candidate(
            name="Note2",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"note-{uuid.uuid4().hex[:8]}@example.com",
            raw_cv_text="cv has no mention either",
        )
        db.add_all([a, b])
        await db.commit()
        await db.refresh(a)
        await db.refresh(b)
        a_id, b_id = a.id, b.id

        # Only `a` has a note mentioning "Quasar".
        note = Note(
            candidate_id=a_id,
            content="recruiter said Quasar framework was promising",
        )
        db.add(note)
        await db.commit()
        note_id = note.id

    try:
        r = await app_client.get(
            "/api/candidates?q_all=Quasar&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert a_id in result_ids
        assert b_id not in result_ids
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Note).where(Note.id == note_id))
            for cid in (a_id, b_id):
                await db.execute(delete(Candidate).where(Candidate.id == cid))
            await db.commit()


@pytest.mark.asyncio
async def test_simple_q_matches_same_scope_as_q_all(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Regression: ?q=Python and ?q_all=Python must return overlapping sets.

    Pre-unification, simple `q` searched only name/lastname/email + raw_cv_text,
    while `q_all` covered tags/skills/experience too. This caused recruiters
    to see different counts depending on which mode they used. After the
    follow-up unification both should hit every searchable field — including
    tags, the field we use as the canary here.
    """
    a = await _seed_candidate(
        raw_cv="unrelated cv text", tags=["polyglot-language-AlphaTagX"]
    )
    try:
        r_simple = await app_client.get(
            "/api/candidates?q=AlphaTagX&page_size=100",
            headers=app_auth_headers,
        )
        r_advanced = await app_client.get(
            "/api/candidates?q_all=AlphaTagX&page_size=100",
            headers=app_auth_headers,
        )
        assert r_simple.status_code == 200, r_simple.text
        assert r_advanced.status_code == 200, r_advanced.text
        ids_simple = {it["id"] for it in r_simple.json()["items"]}
        ids_advanced = {it["id"] for it in r_advanced.json()["items"]}
        # Before unification only `q_all` would find this row; now both must.
        assert a in ids_simple, "simple q should match tag content"
        assert a in ids_advanced
    finally:
        await _cleanup([a])


@pytest.mark.asyncio
async def test_sort_relevance_ranks_close_match_first(
    app_client: AsyncClient, app_auth_headers: dict
):
    """sort=relevance with `?q=` should put closer name matches first.

    We seed two candidates: one whose lastname is exactly the query phrase
    (high trigram similarity) and one whose CV mentions the phrase but
    whose name is unrelated (low trigram similarity on identity haystack).
    The exact-name match must appear first.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from sqlalchemy import delete

    suffix = uuid.uuid4().hex[:8]
    unique_token = f"RelevanceTokenXyz{suffix}"
    async with AsyncSessionLocal() as db:
        # `close_match` — name contains the token (high trigram identity score)
        close_match = Candidate(
            name=unique_token,
            lastname="Smith",
            email=f"close-{suffix}@example.com",
            raw_cv_text="generic cv body unrelated to the token",
        )
        # `cv_only` — name is plain, only CV mentions token (low identity score)
        cv_only = Candidate(
            name="Adam",
            lastname="Nowak",
            email=f"farmatch-{suffix}@example.com",
            raw_cv_text=f"developer with experience in {unique_token} framework",
        )
        db.add_all([close_match, cv_only])
        await db.commit()
        await db.refresh(close_match)
        await db.refresh(cv_only)
        close_id, far_id = close_match.id, cv_only.id

    try:
        r = await app_client.get(
            f"/api/candidates?q={unique_token}&sort=relevance&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        positions = {it["id"]: idx for idx, it in enumerate(items)}
        assert close_id in positions, "close-match candidate missing from results"
        assert far_id in positions, "cv-only candidate missing from results"
        assert positions[close_id] < positions[far_id], (
            "name-match candidate should rank above cv-only on sort=relevance"
        )
    finally:
        async with AsyncSessionLocal() as db:
            for cid in (close_id, far_id):
                await db.execute(delete(Candidate).where(Candidate.id == cid))
            await db.commit()


@pytest.mark.asyncio
async def test_full_name_query_matches_only_exact_pair(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Regression: ?q="First Last" must match (name=First, lastname=Last) and
    NOT every candidate that shares only the first name.

    Pre-fix, the phrase ILIKE was applied to each column independently — so
    "Piotr Banulski" never matched (name="Piotr" doesn't contain the full
    phrase, lastname="Banulski" doesn't either). The trigram fallback at 0.2
    threshold then fired for every "Piotr X" candidate via shared "Piotr"
    trigrams. Recruiters saw the full first-name list instead of the one
    person they typed.

    Fix: phrase scope now includes concat(name, ' ', lastname), and the
    trigram threshold is 0.5 for multi-word queries (was 0.2 unconditionally).
    """
    suffix = uuid.uuid4().hex[:8]
    target_lastname = f"Banulski-{suffix}"
    noise_lastname_1 = f"Bartkowski-{suffix}"
    noise_lastname_2 = f"Slowikowski-{suffix}"

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        target = Candidate(
            name="Piotr",
            lastname=target_lastname,
            email=f"piotr-target-{suffix}@example.com",
            raw_cv_text="unrelated cv body",
        )
        noise_1 = Candidate(
            name="Piotr",
            lastname=noise_lastname_1,
            email=f"piotr-noise1-{suffix}@example.com",
            raw_cv_text="unrelated cv body",
        )
        noise_2 = Candidate(
            name="Piotr",
            lastname=noise_lastname_2,
            email=f"piotr-noise2-{suffix}@example.com",
            raw_cv_text="unrelated cv body",
        )
        db.add_all([target, noise_1, noise_2])
        await db.commit()
        for c in (target, noise_1, noise_2):
            await db.refresh(c)
        target_id, noise_1_id, noise_2_id = target.id, noise_1.id, noise_2.id

    try:
        r = await app_client.get(
            f"/api/candidates?q=Piotr {target_lastname}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert target_id in result_ids, "exact name+lastname match must be returned"
        assert noise_1_id not in result_ids, (
            "shared-first-name candidates must NOT match a full-name query"
        )
        assert noise_2_id not in result_ids, (
            "shared-first-name candidates must NOT match a full-name query"
        )
    finally:
        async with AsyncSessionLocal() as db:
            for cid in (target_id, noise_1_id, noise_2_id):
                await db.execute(delete(Candidate).where(Candidate.id == cid))
            await db.commit()


def test_fold_polish_helper():
    """The Python fold must mirror the SQL `lower(translate(...))` of
    `search_doc_unaccented` (migration 0159), including NFD → NFC handling."""
    import unicodedata

    from app.services.advanced_candidate_search import fold_polish

    assert fold_polish("Łukasz Grądzki") == "lukasz gradzki"
    assert fold_polish("Kraków") == "krakow"
    assert fold_polish("Gdańsk") == "gdansk"
    assert fold_polish("Źródło Ćma Żółw Świnoujście") == "zrodlo cma zolw swinoujscie"
    # NFD (decomposed) input must fold identically to NFC — paste / IME / the
    # computer-use `type` action emit NFD.
    assert fold_polish(unicodedata.normalize("NFD", "Grądzki")) == "gradzki"
    # Already-folded ASCII is unchanged (idempotent).
    assert fold_polish("lukasz gradzki") == "lukasz gradzki"


@pytest.mark.asyncio
async def test_diacritic_insensitive_name_search(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Regression: a Polish name typed WITHOUT diacritics must match.

    „Łukasz Grądzki" was unreachable via `?q=lukasz gradzki` — both search paths
    are diacritic-sensitive (FTS `to_tsquery('simple','lukasz:*')` never reaches
    the token `łukasz`; `search_doc ILIKE '%lukasz%'` never matches `ł`). The
    folded `search_doc_unaccented` branch (migration 0159) closes the gap.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from sqlalchemy import delete

    suffix = uuid.uuid4().hex[:8]
    target_last = f"Grądzki{suffix}"
    async with AsyncSessionLocal() as db:
        target = Candidate(
            name="Łukasz",
            lastname=target_last,
            email=f"lukasz-{suffix}@example.com",
            raw_cv_text="unrelated cv body",
        )
        noise = Candidate(
            name="Anna",
            lastname=f"Nowak{suffix}",
            email=f"anna-{suffix}@example.com",
            raw_cv_text="unrelated cv body",
        )
        db.add_all([target, noise])
        await db.commit()
        await db.refresh(target)
        await db.refresh(noise)
        target_id, noise_id = target.id, noise.id

    try:
        # Full ascii pair, single ascii lastname token, and — no regression —
        # the same lastname typed WITH its diacritic must all reach the target.
        for query in (
            f"lukasz gradzki{suffix}",
            f"gradzki{suffix}",
            f"Grądzki{suffix}",
        ):
            r = await app_client.get(
                "/api/candidates",
                params={"q": query, "page_size": 100},
                headers=app_auth_headers,
            )
            assert r.status_code == 200, r.text
            ids = {it["id"] for it in r.json()["items"]}
            assert target_id in ids, f"query {query!r} must match „Łukasz Grądzki"

        # The un-accented query must not sweep in the unrelated candidate.
        r = await app_client.get(
            "/api/candidates",
            params={"q": f"lukasz gradzki{suffix}", "page_size": 100},
            headers=app_auth_headers,
        )
        assert noise_id not in {it["id"] for it in r.json()["items"]}
    finally:
        async with AsyncSessionLocal() as db:
            for cid in (target_id, noise_id):
                await db.execute(delete(Candidate).where(Candidate.id == cid))
            await db.commit()


@pytest.mark.asyncio
async def test_diacritic_insensitive_city_search(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A city typed without diacritics (`krakow`) matches a stored „Kraków".

    Exercises the folded branch on a non-identity field (`city` is part of
    search_doc / search_doc_unaccented) via the advanced `q_all` bucket.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from sqlalchemy import delete

    suffix = uuid.uuid4().hex[:8]
    token = f"Kraków{suffix}"  # unique so we can assert exact membership
    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="City",
            lastname=f"Test-{suffix}",
            email=f"city-{suffix}@example.com",
            city=token,
            raw_cv_text="unrelated cv body",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        c_id = c.id

    try:
        r = await app_client.get(
            "/api/candidates",
            params={"q_all": f"krakow{suffix}", "page_size": 100},
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        assert c_id in {it["id"] for it in r.json()["items"]}
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Candidate).where(Candidate.id == c_id))
            await db.commit()
