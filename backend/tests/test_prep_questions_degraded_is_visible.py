"""Awaria wyszukiwania nie może wyglądać jak kompletny prep-kit.

`search_similar_jobs_by_job_id` zwracało pustą listę ZARÓWNO gdy Qdrant nie
odpowiedział, JAK I gdy oferta po prostu nie ma podobnych. Oba tiery milkły
identycznie, a tier 4 (auto-gen) uruchamia się jako bezpiecznik — „prep-kit
musi mieć >= 1 pytanie". Skutek: podczas awarii rekruter dostawał wiarygodną,
NIEPUSTĄ listę pytań i nie miał ŻADNEGO sposobu, żeby zauważyć, że dwa
najlepsze źródła nie odpowiedziały.

To ta sama klasa co #403 — system nie wie, a zachowuje się tak, jakby wiedział
— tylko o warstwę wyżej i groźniejsza, bo tam objawem była pustka (widoczna),
a tu pełny wynik (niewidoczny).

Testy pilnują OBU kierunków. Fałszywy alarm jest tu równie szkodliwy co cisza:
flaga zapalana zawsze nauczyłaby ignorować ostrzeżenie.
"""

import pytest

from app.services import question_suggestions as qs

pytestmark = pytest.mark.asyncio


class _FakeDb:
    async def execute(self, *a, **k):
        class _R:
            @staticmethod
            def all():
                return []

            @staticmethod
            def scalars():
                class _S:
                    @staticmethod
                    def all():
                        return []

                return _S()

        return _R()


def _job(job_id: int = 1, cc: int | None = 5):
    class _J:
        id = job_id
        competence_category_id = cc
        client_id = 1
        title = "Python Developer"
        must_skills = ["python"]
        nice_skills = []
        description = None
        requirements = None
        champion_profile = None
        embedding_id = None

    return _J()


async def test_qdrant_silence_marks_the_result_as_incomplete(monkeypatch):
    """`None` z wyszukiwania => degraded=True, mimo że pytania SĄ."""

    async def _silent(job_id, **kw):
        return None  # Qdrant nie odpowiedział

    monkeypatch.setattr(qs, "search_similar_jobs_by_job_id", _silent)

    result = await qs.suggest_questions_for_prep(_FakeDb(), _job(), target_count=10)

    assert result.degraded is True, (
        "Qdrant milczał, a wynik przedstawia się jako kompletny — rekruter nie "
        "ma jak zauważyć, że dwa najlepsze źródła nie odpowiedziały"
    )
    assert result.reason, "degraded bez powodu nie mówi użytkownikowi niczego"
    assert result.questions, (
        "bezpiecznik tier 4 ma nadal dolewać pytania — degradacja nie może "
        "zamienić cichej niepełności w twardą awarię"
    )


async def test_answered_but_empty_is_not_degraded(monkeypatch):
    """`[]` to PRAWIDŁOWA odpowiedź „nie ma podobnych" — nie awaria.

    Bez tego rozróżnienia flaga zapalałaby się dla każdej oferty bez podobnych,
    czyli praktycznie zawsze — i nauczyłaby ignorować ostrzeżenie.
    """

    async def _answered_empty(job_id, **kw):
        return []

    monkeypatch.setattr(qs, "search_similar_jobs_by_job_id", _answered_empty)

    result = await qs.suggest_questions_for_prep(_FakeDb(), _job(), target_count=10)

    assert result.degraded is False, (
        "brak podobnych ofert to normalny wynik, nie awaria — fałszywy alarm "
        "uczy ignorować flagę"
    )
    assert result.reason is None
    assert result.questions


async def test_missing_cc_is_not_degraded(monkeypatch):
    """Brak kategorii kompetencji ucina tier 1 PRZED Qdrantem — to nie awaria."""
    calls: list[int] = []

    async def _spy(job_id, **kw):
        calls.append(job_id)
        return []

    monkeypatch.setattr(qs, "search_similar_jobs_by_job_id", _spy)

    result = await qs.suggest_questions_for_prep(
        _FakeDb(), _job(cc=None), target_count=10
    )
    assert result.degraded is False


async def test_tiers_report_degradation_independently(monkeypatch):
    """Wystarczy JEDEN milczący tier, żeby wynik był niepełny."""

    async def _silent(job_id, **kw):
        return None

    monkeypatch.setattr(qs, "search_similar_jobs_by_job_id", _silent)

    t1, t1_degraded = await qs._tier_same_cc_similar(_FakeDb(), _job())
    assert (t1, t1_degraded) == ([], True)

    t2, t2_degraded = await qs._tier_secondary_cc(_FakeDb(), _job())
    assert t2 == []
    # Tier 2 może uciąć wcześniej (pusty cc_pool) — wtedy Qdrant nie jest
    # pytany i degradacji nie ma. Sprawdzamy tylko, że flaga jest bool-em,
    # a nie że zawsze True: asercja "zawsze True" pinowałaby przypadkową
    # kolejność warunków zamiast własności.
    assert isinstance(t2_degraded, bool)


# ── Dowód przez PRAWDZIWĄ funkcję ───────────────────────────────────────────
# Testy wyżej mockują `search_similar_jobs_by_job_id`, więc dowodzą wyłącznie,
# że tiery poprawnie obsługują `None`. NIC w nich nie dowodzi, że ta funkcja
# w ogóle zwraca `None` przy awarii — sklejenie obu stanów z powrotem
# przechodziło je na zielono (sprawdzone). Poniższe testy wołają prawdziwą
# implementację z podmienionym KLIENTEM Qdranta, czyli na granicy systemu.


async def test_real_search_answers_unknown_when_qdrant_raises(monkeypatch):
    """Qdrant rzuca => `None` („nie wiem"), nigdy `[]`."""
    import qdrant_client

    from app.services import embedding_service as es

    class _Boom:
        def __init__(self, *a, **k):
            pass

        def retrieve(self, *a, **k):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(qdrant_client, "QdrantClient", _Boom)

    out = await es.search_similar_jobs_by_job_id(4242)
    assert out is None, (
        f"awaria Qdranta zwrocila {out!r} zamiast None. Pusta lista jest "
        "NIEODROZNIALNA od 'oferta nie ma podobnych', a to caly defekt #408"
    )


async def test_real_search_answers_absent_when_qdrant_says_no_vector(monkeypatch):
    """Qdrant odpowiada, wektora nie ma => `[]` („wiem, że nie ma")."""
    import qdrant_client

    from app.services import embedding_service as es

    class _Empty:
        def __init__(self, *a, **k):
            pass

        def retrieve(self, *a, **k):
            return []

    monkeypatch.setattr(qdrant_client, "QdrantClient", _Empty)

    out = await es.search_similar_jobs_by_job_id(4242)
    assert out == [], (
        f"Qdrant ODPOWIEDZIAŁ, że wektora nie ma — to {out!r} zamiast []; "
        "zwracanie `None` tutaj byłoby fałszywym alarmem"
    )
