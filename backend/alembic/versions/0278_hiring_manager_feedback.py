"""Werdykt hiring managera bez wpisu w kalendarzu (krok 07 „Rozmowy i decyzja").

Revision ID: 0278_hiring_manager_feedback
Revises: 0277_recruitment_allocation

``InterviewFeedback`` powstał jako notatka PRZYPIĘTA DO SPOTKANIA: ``UNIQUE
(calendar_event_id, feedback_source)`` i ``calendar_event_id NOT NULL``. Feedback
klienta po rozmowie ma jednak dokładnie ten kształt danych (kto, jaka decyzja,
co powiedział) także wtedy, gdy rozmowy NIE zaplanowano w NEXUSIE — a tak jest
w większości: „Zaplanuj interview (M365)" to jedna z wielu ścieżek, a klient
często umawia się z kandydatem sam i odzywa się dopiero z werdyktem. Bez tej
migracji karta rozmowy musiałaby albo zakładać sztuczny ``CalendarEvent`` (kłamstwo
w kalendarzu zespołu), albo trzymać werdykt w wolnym tekście notatki (nie da się
z tego zrobić ani lejka, ani sygnału o wecie).

Dwie zmiany, obie addytywne:

1. ``calendar_event_id`` przestaje być ``NOT NULL``. UNIQUE zostaje bez zmian —
   Postgres traktuje NULL-e jako różne, więc ograniczenie dalej pilnuje dokładnie
   tego, co pilnowało (max jeden feedback danej strony na SPOTKANIE), a wiersze
   bez spotkania go nie dotyczą. Unikalności „jeden werdykt na parę (kandydat,
   rekrutacja)" świadomie NIE dokładamy ograniczeniem: to samo API robi upsert,
   a częściowy indeks unikalny wywróciłby historyczne wiersze bez ``job_id``.

2. ``rejection_reason_id`` — powód ze SŁOWNIKA szablonu, ten sam, po którym
   ``services/hiring_manager_verdicts`` rozpoznaje weto (``RejectionReason.
   disqualifies_person``). Trzymanie samej nazwy powodu w tekście podsumowania
   byłoby stratne: „czy ten werdykt blokuje ponowne propozycje" trzeba MÓC
   policzyć, a nie zgadywać z prozy. ``ON DELETE SET NULL``, bo skasowanie
   pozycji słownika nie może kasować tego, co manager powiedział.

Zdublowane w safety-net ``entrypoint.sh`` — prod alembic bywa orphaned.
"""

from alembic import op

revision = "0278_hiring_manager_feedback"
down_revision = "0277_recruitment_allocation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Surowy SQL, bit w bit ten sam co lustro w ``entrypoint.sh``.
    op.execute(
        "ALTER TABLE interview_feedback ALTER COLUMN calendar_event_id DROP NOT NULL"
    )
    op.execute(
        "ALTER TABLE interview_feedback "
        "ADD COLUMN IF NOT EXISTS rejection_reason_id INTEGER NULL "
        "REFERENCES rejection_reasons(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    # Powrotu do ``NOT NULL`` NIE ma: po tej migracji w tabeli mogą stać wiersze
    # bez spotkania, a przywrócenie ograniczenia skasowałoby werdykty managerów
    # albo wywróciło downgrade w połowie. Zdejmujemy tylko dołożoną kolumnę.
    op.execute(
        "ALTER TABLE interview_feedback DROP COLUMN IF EXISTS rejection_reason_id"
    )
