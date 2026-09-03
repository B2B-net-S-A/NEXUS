"""Kto pisze do której kolumny `jobs` — jedno miejsce, czytane przez test.

Tabela `jobs` ma DWÓCH piszących: nocny sync Traffita (`_UPSERT_JOB`
w `services/traffit/importer.py`) i sam NEXUS (formularz, Champion, handoff,
`PATCH /api/jobs/{id}`). Do 09.2026 nie było między nimi granicy i obaj pisali
do tych samych kolumn — więc `status` ustawiony ręcznie w NEXUSIE był cicho
cofany przy najbliższym dotknięciu wiersza przez sync, a `title` poprawiony
w NEXUSIE wracał do brzmienia z Traffita.

Podział jest DEKLARACJĄ, nie mechanizmem: nic nie blokuje zapisu w runtime.
Egzekwuje go `tests/test_job_column_ownership.py`, który czyta `_UPSERT_JOB`
AST-em i porównuje jego listę `DO UPDATE SET` z `SYNC_WRITABLE` poniżej.
Dlatego dopisanie kolumny do UPSERT-u bez dopisania jej tutaj kończy się
czerwonym CI, a nie cichym nadpisywaniem cudzej pracy na produkcji.

Test pilnuje też WYCZERPANIA: każda kolumna modelu `Job` musi należeć
do dokładnie jednego zbioru. Nowa kolumna bez decyzji „czyja jest" nie
przejdzie — i o to chodzi, bo ta decyzja jest tańsza teraz niż po incydencie.
"""

from __future__ import annotations

# Kolumny, których treść pochodzi z Traffita. Sync nadpisuje je bezwarunkowo;
# NEXUS może je co najwyżej wyświetlać.
#
# `title` jest tu świadomie: rekrutacje nazywa się w Traffitcie, a nie u nas.
# Konsekwencja jest znana i nieprzyjemna — edycja tytułu zaimportowanej
# rekrutacji w NEXUSIE nadal przejdzie i nadal zostanie po cichu cofnięta.
# Zablokowanie tego pola w UI jest osobną zmianą.
TRAFFIT_OWNED: frozenset[str] = frozenset(
    {
        "title",
        "status",
        "reference_number",
        "deadline",
        "opened_at",
        "closed_at",
        "custom_fields",
    }
)

# Klucz konfliktu `ON CONFLICT (external_source, external_id)` — nie pojawia się
# w `DO UPDATE SET`, bo to tożsamość wiersza, a nie jego treść.
SYNC_IDENTITY: frozenset[str] = frozenset({"external_id", "external_source"})

# Pisane przez sync z `COALESCE(EXCLUDED.x, jobs.x)`, czyli „uzupełnij, jeśli
# puste, ale nigdy nie kasuj". W praktyce NEXUS wygrywa, bo odpowiedź listy
# `/recruitments/` nie zawiera `workflow_id` ani `responsible_person`, a klient
# bywa nierozwiązywalny — patrz komentarz o sierocie w `import_jobs`.
SHARED_NEXUS_WINS: frozenset[str] = frozenset(
    {"client_id", "pipeline_template_id", "recruiter_id"}
)

# Księgowość wiersza — kiedy NEXUS go widział, nie kiedy cokolwiek się wydarzyło
# u klienta. `created_at` celowo NIE jest przez sync aktualizowane.
SYNC_BOOKKEEPING: frozenset[str] = frozenset({"updated_at"})

# Wszystko, czego sync NIE MOŻE tknąć. Praca NEXUSA: właściciele, Champion,
# kryteria matchingu, wynik klasyfikacji, budżety, powód zamknięcia,
# i „otwartość" w naszym rozumieniu (`is_open`).
NEXUS_OWNED: frozenset[str] = frozenset(
    {
        "id",
        # `created_at` z `TimestampMixin` — kiedy wiersz trafił do NEXUSA.
        # Sync go NIE aktualizuje; datę otwarcia u klienta niesie `opened_at`.
        "created_at",
        "is_open",
        "needs_sourcing",
        "description",
        "requirements",
        "location",
        "salary_min",
        "salary_max",
        "rate_budget_hourly",
        "remote_policy",
        "priority",
        "recruitment_type",
        "portals",
        "must_skills",
        "nice_skills",
        "seniority",
        "work_mode",
        "headcount",
        "industry",
        "subcategory",
        "train_name",
        "champion_profile",
        "embedding_id",
        "criteria_generated_at",
        "close_reason",
        "close_notes",
        "competence_category_id",
        "tac_id",
        "delivery_lead_id",
        "favorite_candidate_id",
        "hiring_manager_contact_id",
        "created_by",
    }
)

# Dokładnie to, co wolno wymienić w `DO UPDATE SET` w `_UPSERT_JOB`.
SYNC_WRITABLE: frozenset[str] = TRAFFIT_OWNED | SHARED_NEXUS_WINS | SYNC_BOOKKEEPING

# Suma wszystkich kubełków — test porównuje ją z kolumnami modelu `Job`.
ALL_CLASSIFIED: frozenset[str] = (
    TRAFFIT_OWNED | SYNC_IDENTITY | SHARED_NEXUS_WINS | SYNC_BOOKKEEPING | NEXUS_OWNED
)
