"""Zgłoszenia trenera i polecenia ze strony B2B Network (0806) — JEDNO źródło
dla migracji i siatki w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

Decyzje Artura z 28.11.2026: na /dla-specjalistow trenerem może zgłosić się
każdy z rynku, a polecić inżyniera może każdy. Obie osoby zwykle nie mają
kontraktu w NEXUSIE, więc nie pasują do ``cp_trainer_applications`` (wymaga
``contract_id``) ani do dodatku „Polecenie” na fakturze konsultanta.

* ``market_trainer_applications`` — „Kandydaci na trenerów”: jedno zgłoszenie na
  adres e-mail (ponowne wysłanie poprawia to samo), status ustawia TCM:
  nowe → rozmowa → w bazie trenerów / odrzucone. Trener z bazy dostaje
  zamówienia obiegiem szkoleń (``trainings``); wejście do panelu bez kontraktu
  to osobny krok (decyzja Artura 28.11.2026: osobne wejście trenera).
* ``candidate_referrals`` — polecenie: polecający (imię, e-mail, opcjonalnie
  jego kontrakt albo profil w bazie), polecany (kandydat ze źródłem
  „Polecenie”), dosłowne oświadczenie „ta osoba wie, że ją polecam” i zgoda
  polecającego. Premia 1–5 tys. zł zależnie od profilu (Artur 28.11.2026), stąd
  kwota przy każdym poleceniu; zakres pilnuje API, baza tylko „> 0”, żeby
  zmiana widełek nie wymagała migracji.

Zgody leżą tu, nie w ``candidate_consents``: trener nie jest kandydatem,
a zgoda polecającego dotyczy jego danych, nie danych polecanej osoby.
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

#: Tematy z panelu konsultanta (``TRAINER_TOPICS`` w ``PanelScreens.tsx``) i ze
#: strony (``src/lib/engineerForms.ts``) — trzy listy muszą być takie same
#: (``tests/test_website_trainer_applications.py``).
TRAINER_TOPICS: tuple[str, ...] = (
    "AWS",
    "Azure",
    "Kubernetes",
    "Java",
    "Python",
    "Testy",
    "Bezpieczeństwo",
    "Scrum",
    "AI w pracy",
    "DORA / NIS2",
)

TRAINER_STATUSES: tuple[str, ...] = ("new", "interview", "accepted", "rejected")
REFERRAL_STATUSES: tuple[str, ...] = (
    "new",
    "contacted",
    "started",
    "paid",
    "rejected",
)

# Limity jak w ``src/lib/forms/parse.ts`` strony (``LIMITS``).
NAME_MAX = 120
EMAIL_MAX = 254
LINKEDIN_MAX = 300
TOPIC_MAX = 120
FIRST_TRAINING_MAX = 200
EXPERIENCE_MAX = 5_000
URL_MAX = 500
ROLE_MAX = 200
CONSENT_MAX = 2_000
NOTE_MAX = 1_000

TRAINERS = "market_trainer_applications"
REFERRALS = "candidate_referrals"

CK_TRAINER_STATUS = f"status IN ({quoted(TRAINER_STATUSES)})"
CK_TRAINER_JSON = "jsonb_typeof(topics) = 'array' AND jsonb_typeof(consents) = 'array'"
CK_REFERRAL_STATUS = f"status IN ({quoted(REFERRAL_STATUSES)})"
CK_REFERRAL_CONTACT = "referred_email IS NOT NULL OR referred_linkedin IS NOT NULL"
CK_REFERRAL_BONUS = "bonus_amount IS NULL OR bonus_amount > 0"
CK_REFERRAL_JSON = "jsonb_typeof(consents) = 'array'"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS {TRAINERS} (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR({NAME_MAX}) NOT NULL,
    email VARCHAR({EMAIL_MAX}) NOT NULL,
    linkedin VARCHAR({LINKEDIN_MAX}) NULL,
    topics JSONB NOT NULL DEFAULT '[]'::jsonb,
    other_topic VARCHAR({TOPIC_MAX}) NULL,
    first_training VARCHAR({FIRST_TRAINING_MAX}) NOT NULL,
    experience VARCHAR({EXPERIENCE_MAX}) NOT NULL,
    sample_url VARCHAR({URL_MAX}) NULL,
    consents JSONB NOT NULL DEFAULT '[]'::jsonb,
    consented_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE SET NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'new',
    status_note VARCHAR({NOTE_MAX}) NOT NULL DEFAULT '',
    status_changed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    status_changed_at TIMESTAMPTZ NULL,
    submissions INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_{TRAINERS}_status CHECK ({CK_TRAINER_STATUS}),
    CONSTRAINT ck_{TRAINERS}_json CHECK ({CK_TRAINER_JSON})
)""",
    f"""CREATE TABLE IF NOT EXISTS {REFERRALS} (
    id SERIAL PRIMARY KEY,
    referrer_name VARCHAR({NAME_MAX}) NOT NULL,
    referrer_email VARCHAR({EMAIL_MAX}) NOT NULL,
    referrer_candidate_id INTEGER NULL REFERENCES candidates(id) ON DELETE SET NULL,
    referrer_contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE SET NULL,
    referred_name VARCHAR({NAME_MAX}) NOT NULL,
    referred_email VARCHAR({EMAIL_MAX}) NULL,
    referred_linkedin VARCHAR({LINKEDIN_MAX}) NULL,
    referred_role VARCHAR({ROLE_MAX}) NULL,
    candidate_id INTEGER NULL REFERENCES candidates(id) ON DELETE SET NULL,
    submission_id INTEGER NULL REFERENCES application_submissions(id) ON DELETE SET NULL,
    was_in_database BOOLEAN NOT NULL DEFAULT FALSE,
    statement_text VARCHAR({CONSENT_MAX}) NOT NULL,
    consents JSONB NOT NULL DEFAULT '[]'::jsonb,
    consented_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status VARCHAR(16) NOT NULL DEFAULT 'new',
    bonus_amount NUMERIC(10, 2) NULL,
    status_note VARCHAR({NOTE_MAX}) NOT NULL DEFAULT '',
    status_changed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    status_changed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_{REFERRALS}_status CHECK ({CK_REFERRAL_STATUS}),
    CONSTRAINT ck_{REFERRALS}_contact CHECK ({CK_REFERRAL_CONTACT}),
    CONSTRAINT ck_{REFERRALS}_bonus CHECK ({CK_REFERRAL_BONUS}),
    CONSTRAINT ck_{REFERRALS}_json CHECK ({CK_REFERRAL_JSON})
)""",
)

INDEX_DDL: tuple[str, ...] = (
    f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{TRAINERS}_email "
    f"ON {TRAINERS} (lower(email))",
    f"CREATE INDEX IF NOT EXISTS ix_{TRAINERS}_status "
    f"ON {TRAINERS} (status, updated_at)",
    f"CREATE INDEX IF NOT EXISTS ix_{REFERRALS}_status "
    f"ON {REFERRALS} (status, created_at)",
    f"CREATE INDEX IF NOT EXISTS ix_{REFERRALS}_candidate "
    f"ON {REFERRALS} (candidate_id) WHERE candidate_id IS NOT NULL",
    f"CREATE INDEX IF NOT EXISTS ix_{REFERRALS}_referrer_email "
    f"ON {REFERRALS} (lower(referrer_email))",
)

TABLES: tuple[str, ...] = (TRAINERS, REFERRALS)

ALL_DDL: tuple[str, ...] = (*TABLE_DDL, *INDEX_DDL)

DOWNGRADE_DDL: tuple[str, ...] = tuple(
    f"DROP TABLE IF EXISTS {table}" for table in reversed(TABLES)
)
