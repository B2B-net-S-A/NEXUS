"""„Ludzie w NEXUSIE” — Opieka nad konsultantami i technologie: SQL migracji ``0462_contract_care`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0462_contract_care.py`` i ``entrypoint.sh``
(przez ``app/services/hr_schema_bundle.py``). Zakres: opiekun kontraktu, plan kontaktów, rozmowy, karty technologiczne, kolejka „Do przepięcia”.

Kontrakt modułu (czyta go agregator i test łańcucha):

* ``TABLE_DDL`` — ``CREATE TABLE IF NOT EXISTS`` nowych tabel (VARCHAR + CHECK,
  bez nowych typów enum),
* ``COLUMN_DDL`` — ``ALTER TABLE … ADD COLUMN IF NOT EXISTS`` w istniejących tabelach,
* ``INDEX_DDL`` — ``CREATE [UNIQUE] INDEX IF NOT EXISTS``,
* ``CONSTRAINT_DDL`` — ograniczenia dokładane do ISTNIEJĄCYCH tabel (idempotentne bloki ``DO``),
* ``DATA_DDL`` — zasiewy i znaczniki jednorazowe (idempotentne),
* ``TABLES`` — nowe tabele w kolejności tworzenia (downgrade kasuje odwrotnie),
* ``DOWNGRADE_DDL`` — sprzątanie kolumn/ograniczeń w istniejących tabelach.

Każda instrukcja musi być idempotentna: entrypoint wykonuje je przy każdym starcie.

Model (decyzja Artura D7, 16.10.2026): konsultant to kandydat z kontraktem,
więc opieka i karta technologiczna żyją na kontrakcie i kliencie NEXUSA.
Technologie karty to wiersze słownika ``skills`` (ten sam, z którego korzystają
wymagania rekrutacji i profile); nazwa spoza słownika czeka w
``skill_review_queue``. Rejestr kontraktorów, wejścia, zejścia i ławka
Compassa nie przechodzą — NEXUS ma je w kontraktach i zamówieniach.

Opinie klienta (etap 2, D8–D11, 17.10.2026): rozmowa z menedżerem u klienta
(kontakt klienta z ``contracts.client_pm_contact_id``) zapisana po telefonie
albo spotkaniu — ``client_feedback_sessions`` — z ocenami 1–5 per konsultant
(kontrakt) w ``client_feedback_scores``. Formularza wysyłanego do klienta nie
ma (D10). Konsultant opinii nie widzi (D11).

Struktura u klienta (etap 2, 17.10.2026): kontakt klienta podlega pod inny
kontakt TEGO klienta (``contacts.reports_to_contact_id``, bez cykli — pilnuje
``care/client_people``) i należy do działu z ``client_areas`` („Działy
i obszary”, ten sam słownik co mapa technologii). Tekst ``contacts.department``
zostaje — ekran podpowiada dział, nic nie przypisuje się samo.

Rytm kontaktu (etap 3, O7–O8, 17.10.2026): ``care_cadence_periods`` — zmiana
rytmu konsultanta (kontraktu) od dnia zmiany, z powodem z listy, notatką
i opcjonalną datą „do kiedy” (po niej wraca poprzedni rytm,
``services/care/cadence_rules.py``). Bez wiersza obowiązuje program: 90 dni
co 2 tygodnie, potem co miesiąc. Plan dostał rodzaj ``cadence`` (rozmowa
z rytmu, ``seq`` = dzień terminu) obok kamieni ``day_7`` i ``pre_end``;
dawne ``day_30``/``day_90``/``quarterly`` zostają w historii. „Pomiń” punkt
planu zapisuje powód (``skip_reason``) i notatkę.
"""

from __future__ import annotations

CARE_CHANNELS: tuple[str, ...] = ("phone", "meeting", "chat")
PLAN_KINDS: tuple[str, ...] = (
    "day_7",
    "day_30",
    "day_90",
    "quarterly",
    "pre_end",
    "cadence",
)
PLAN_STATUSES: tuple[str, ...] = ("open", "done", "skipped")
CARD_STATUSES: tuple[str, ...] = ("ok", "odmowa", "brak_czasu", "niechetny")
HIRING_SOURCES: tuple[str, ...] = ("widzial", "slyszal", "plotka")
SALES_STATUSES: tuple[str, ...] = ("converted", "archived")
REVIEW_STATUSES: tuple[str, ...] = ("open", "mapped", "created", "dismissed")
REDEPLOY_REASONS: tuple[str, ...] = ("project_end", "wants_change", "attrition_risk")
REDEPLOY_STATUSES: tuple[str, ...] = ("open", "in_progress", "done", "dismissed")
REDEPLOY_ACTIVE_STATUSES: tuple[str, ...] = ("open", "in_progress")
REDEPLOY_SOURCES: tuple[str, ...] = ("tech_card", "conversation", "manual")

#: Rytm kontaktu: co 2 tygodnie, co miesiąc, co kwartał, tylko kamienie, wstrzymany.
CADENCE_LEVELS: tuple[str, ...] = (
    "biweekly",
    "monthly",
    "quarterly",
    "milestones",
    "paused",
)
#: Powód zmiany rytmu; ``imported`` ustawia tylko import z Compassa.
CADENCE_REASONS: tuple[str, ...] = (
    "new_at_client",
    "weak_feedback",
    "order_end",
    "wants_change",
    "stable",
    "person_request",
    "long_absence",
    "other",
    "imported",
)
#: Powód „Pomiń” przy punkcie planu.
SKIP_REASONS: tuple[str, ...] = (
    "recent_contact",
    "unreachable",
    "absence",
    "person_request",
    "ending",
    "other",
)

FEEDBACK_CHANNELS: tuple[str, ...] = ("phone", "meeting", "email", "teams")
EXTENSION_OUTLOOKS: tuple[str, ...] = ("yes", "likely", "unsure", "no")
FEEDBACK_SCORE_FIELDS: tuple[str, ...] = ("quality", "communication", "autonomy")

#: Limity tekstów — te same w CHECK-ach i w walidacji API.
NOTE_MAX = 4000
FEEDBACK_NOTE_MAX = 2000
SHORT_TEXT_MAX = 500
NAME_MAX = 120


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_CONV_CHANNEL = f"channel IN ({quoted(CARE_CHANNELS)})"
CK_CONV_SATISFACTION = "satisfaction IS NULL OR satisfaction BETWEEN 1 AND 5"
CK_CONV_NOTE = f"note IS NULL OR char_length(note) <= {NOTE_MAX}"
CK_CONV_FOLLOW_UP = "follow_up_on IS NULL OR follow_up_on >= occurred_on"
CK_PLAN_KIND = f"kind IN ({quoted(PLAN_KINDS)})"
CK_PLAN_STATUS = f"status IN ({quoted(PLAN_STATUSES)})"
CK_PLAN_RESOLUTION = "(status = 'open') = (resolved_at IS NULL)"
CK_PLAN_SKIP_REASON = f"skip_reason IS NULL OR skip_reason IN ({quoted(SKIP_REASONS)})"
#: Powód „Pomiń” tylko przy pominiętym punkcie (przywrócenie go zdejmuje).
CK_PLAN_SKIP = "skip_reason IS NULL OR status = 'skipped'"
CK_CADENCE_LEVEL = f"level IN ({quoted(CADENCE_LEVELS)})"
CK_CADENCE_REASON = f"reason IN ({quoted(CADENCE_REASONS)})"
CK_CADENCE_UNTIL = "until_on IS NULL OR until_on >= starts_on"
CK_CARD_STATUS = f"status IS NULL OR status IN ({quoted(CARD_STATUSES)})"
CK_CARD_FINAL = "is_draft OR status IS NOT NULL"
CK_CARD_HIRING_SOURCE = f"hiring_source IS NULL OR (hiring IS TRUE AND hiring_source IN ({quoted(HIRING_SOURCES)}))"
CK_CARD_SATISFACTION = "satisfaction IS NULL OR satisfaction BETWEEN 1 AND 5"
CK_CARD_EXTERNALS = "team_externals IS NULL OR team_externals BETWEEN 0 AND 10000"
CK_CARD_SALES_STATUS = (
    f"sales_status IS NULL OR sales_status IN ({quoted(SALES_STATUSES)})"
)
CK_REVIEW_STATUS = f"status IN ({quoted(REVIEW_STATUSES)})"
CK_REVIEW_SKILL = "skill_id IS NULL OR status IN ('mapped', 'created')"
CK_REVIEW_OCCURRENCES = "occurrences >= 1"
CK_REDEPLOY_REASON = f"reason IN ({quoted(REDEPLOY_REASONS)})"
CK_REDEPLOY_STATUS = f"status IN ({quoted(REDEPLOY_STATUSES)})"
CK_REDEPLOY_SOURCE = f"source IN ({quoted(REDEPLOY_SOURCES)})"
CK_REDEPLOY_NOTE = f"note IS NULL OR char_length(note) <= {NOTE_MAX}"
REDEPLOY_ACTIVE_WHERE = f"status IN ({quoted(REDEPLOY_ACTIVE_STATUSES)})"
CK_FEEDBACK_CHANNEL = f"channel IN ({quoted(FEEDBACK_CHANNELS)})"
CK_FEEDBACK_EXTENSION = (
    f"extension_outlook IS NULL OR extension_outlook IN ({quoted(EXTENSION_OUTLOOKS)})"
)
CK_FEEDBACK_NOTE = f"note IS NULL OR char_length(note) <= {FEEDBACK_NOTE_MAX}"
CK_SCORE_QUALITY = "quality IS NULL OR quality BETWEEN 1 AND 5"
CK_SCORE_COMMUNICATION = "communication IS NULL OR communication BETWEEN 1 AND 5"
CK_SCORE_AUTONOMY = "autonomy IS NULL OR autonomy BETWEEN 1 AND 5"
#: Wiersz oceny bez żadnej oceny to „pomiń” — nie zapisujemy go wcale.
CK_SCORE_ANY = (
    "quality IS NOT NULL OR communication IS NOT NULL OR autonomy IS NOT NULL"
)

TABLE_DDL: tuple[str, ...] = (
    # Obszar u klienta (Płatności, Kredyty, Data…) — słownik per klient.
    f"""CREATE TABLE IF NOT EXISTS client_areas (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name VARCHAR({NAME_MAX}) NOT NULL,
    name_key VARCHAR({NAME_MAX}) NOT NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_client_areas_client_name UNIQUE (client_id, name_key)
)""",
    # Dostawcy u klienta (firmy zewnętrzne w zespołach) — jeden słownik.
    f"""CREATE TABLE IF NOT EXISTS tech_vendors (
    id SERIAL PRIMARY KEY,
    name VARCHAR({NAME_MAX}) NOT NULL,
    name_key VARCHAR({NAME_MAX}) NOT NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_tech_vendors_name UNIQUE (name_key)
)""",
    f"""CREATE TABLE IF NOT EXISTS care_conversations (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    author_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    occurred_on DATE NOT NULL,
    channel VARCHAR(16) NOT NULL DEFAULT 'phone',
    satisfaction SMALLINT NULL,
    note TEXT NULL,
    attrition_risk BOOLEAN NOT NULL DEFAULT FALSE,
    wants_change BOOLEAN NOT NULL DEFAULT FALSE,
    project_end_on DATE NULL,
    client_hiring BOOLEAN NOT NULL DEFAULT FALSE,
    client_hiring_note VARCHAR({SHORT_TEXT_MAX}) NULL,
    follow_up_on DATE NULL,
    compass_source_id VARCHAR(64) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_care_conversations_compass UNIQUE (compass_source_id),
    CONSTRAINT ck_care_conversations_channel CHECK ({CK_CONV_CHANNEL}),
    CONSTRAINT ck_care_conversations_satisfaction CHECK ({CK_CONV_SATISFACTION}),
    CONSTRAINT ck_care_conversations_note CHECK ({CK_CONV_NOTE}),
    CONSTRAINT ck_care_conversations_follow_up CHECK ({CK_CONV_FOLLOW_UP})
)""",
    # Plan kontaktów: kamienie (dzień 7 od startu i 30 dni przed końcem
    # zamówienia/umowy — ``seq`` = dzień końca, więc nowa data końca daje nowy
    # punkt) i rozmowy z rytmu (``cadence``, ``seq`` = dzień terminu). Wiersze
    # powstają z wyprzedzeniem (``services/care/plan.py``), a status zapisuje
    # opiekun; „Pomiń” z powodem z listy.
    f"""CREATE TABLE IF NOT EXISTS contract_care_plan_items (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    kind VARCHAR(16) NOT NULL,
    seq INTEGER NOT NULL DEFAULT 0,
    due_on DATE NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'open',
    done_conversation_id INTEGER NULL REFERENCES care_conversations(id) ON DELETE SET NULL,
    resolved_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    resolved_at TIMESTAMPTZ NULL,
    skip_reason VARCHAR(24) NULL,
    skip_note VARCHAR({SHORT_TEXT_MAX}) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_contract_care_plan_items_slot UNIQUE (contract_id, kind, seq),
    CONSTRAINT ck_contract_care_plan_items_kind CHECK ({CK_PLAN_KIND}),
    CONSTRAINT ck_contract_care_plan_items_status CHECK ({CK_PLAN_STATUS}),
    CONSTRAINT ck_contract_care_plan_items_resolution CHECK ({CK_PLAN_RESOLUTION}),
    CONSTRAINT ck_contract_care_plan_items_skip_reason CHECK ({CK_PLAN_SKIP_REASON}),
    CONSTRAINT ck_contract_care_plan_items_skip CHECK ({CK_PLAN_SKIP})
)""",
    # Karta technologiczna (pola z Compassa). ``contract_id`` może być pusty
    # tylko dla karty z importu, której konsultanta nie dało się jeszcze
    # połączyć z kontraktem — klient jest zawsze.
    f"""CREATE TABLE IF NOT EXISTS tech_cards (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE CASCADE,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    client_area_id INTEGER NULL REFERENCES client_areas(id) ON DELETE SET NULL,
    author_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    interview_on DATE NOT NULL,
    status VARCHAR(16) NULL,
    is_draft BOOLEAN NOT NULL DEFAULT TRUE,
    finalized_at TIMESTAMPTZ NULL,
    satisfaction SMALLINT NULL,
    hiring BOOLEAN NULL,
    hiring_source VARCHAR(16) NULL,
    hiring_roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    project_end_on DATE NULL,
    project_end_unknown BOOLEAN NOT NULL DEFAULT FALSE,
    team_size VARCHAR(80) NULL,
    team_externals INTEGER NULL,
    initiatives JSONB NOT NULL DEFAULT '[]'::jsonb,
    memorable_quote VARCHAR({SHORT_TEXT_MAX}) NULL,
    note TEXT NULL,
    unrecognized_skills JSONB NOT NULL DEFAULT '[]'::jsonb,
    sales_status VARCHAR(16) NULL,
    sales_deal_title VARCHAR({SHORT_TEXT_MAX}) NULL,
    sales_reason TEXT NULL,
    sales_handled_by VARCHAR(200) NULL,
    sales_handled_at TIMESTAMPTZ NULL,
    compass_card_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_tech_cards_compass UNIQUE (compass_card_id),
    CONSTRAINT ck_tech_cards_status CHECK ({CK_CARD_STATUS}),
    CONSTRAINT ck_tech_cards_final CHECK ({CK_CARD_FINAL}),
    CONSTRAINT ck_tech_cards_hiring_source CHECK ({CK_CARD_HIRING_SOURCE}),
    CONSTRAINT ck_tech_cards_satisfaction CHECK ({CK_CARD_SATISFACTION}),
    CONSTRAINT ck_tech_cards_externals CHECK ({CK_CARD_EXTERNALS}),
    CONSTRAINT ck_tech_cards_sales_status CHECK ({CK_CARD_SALES_STATUS})
)""",
    """CREATE TABLE IF NOT EXISTS tech_card_skills (
    card_id INTEGER NOT NULL REFERENCES tech_cards(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    PRIMARY KEY (card_id, skill_id)
)""",
    """CREATE TABLE IF NOT EXISTS tech_card_vendors (
    card_id INTEGER NOT NULL REFERENCES tech_cards(id) ON DELETE CASCADE,
    vendor_id INTEGER NOT NULL REFERENCES tech_vendors(id) ON DELETE CASCADE,
    PRIMARY KEY (card_id, vendor_id)
)""",
    # Technologia wpisana tekstem, której nie ma w ``skills`` ani w aliasach.
    # Jeden wiersz na nazwę (``name_key``); karty z tą nazwą trzymają ją
    # w ``tech_cards.unrecognized_skills`` do czasu decyzji.
    f"""CREATE TABLE IF NOT EXISTS skill_review_queue (
    id SERIAL PRIMARY KEY,
    name VARCHAR({NAME_MAX}) NOT NULL,
    name_key VARCHAR({NAME_MAX}) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'open',
    skill_id INTEGER NULL REFERENCES skills(id) ON DELETE SET NULL,
    occurrences INTEGER NOT NULL DEFAULT 1,
    reported_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    resolved_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    resolved_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_skill_review_queue_name UNIQUE (name_key),
    CONSTRAINT ck_skill_review_queue_status CHECK ({CK_REVIEW_STATUS}),
    CONSTRAINT ck_skill_review_queue_skill CHECK ({CK_REVIEW_SKILL}),
    CONSTRAINT ck_skill_review_queue_occurrences CHECK ({CK_REVIEW_OCCURRENCES})
)""",
    # „Do przepięcia”: konsultant (kontrakt → kandydat) z powodem. Aktywny
    # wpis jest jeden na kontrakt i powód (indeks częściowy niżej).
    f"""CREATE TABLE IF NOT EXISTS redeploy_queue_items (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    reason VARCHAR(24) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'open',
    due_on DATE NULL,
    source VARCHAR(16) NOT NULL DEFAULT 'manual',
    source_id INTEGER NULL,
    note TEXT NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    resolved_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_redeploy_queue_items_reason CHECK ({CK_REDEPLOY_REASON}),
    CONSTRAINT ck_redeploy_queue_items_status CHECK ({CK_REDEPLOY_STATUS}),
    CONSTRAINT ck_redeploy_queue_items_source CHECK ({CK_REDEPLOY_SOURCE}),
    CONSTRAINT ck_redeploy_queue_items_note CHECK ({CK_REDEPLOY_NOTE})
)""",
    # Rozmowa z menedżerem u klienta o pracy konsultantów (D9–D11). Kontakt
    # SET NULL: usunięty kontakt nie kasuje opinii, które o konsultantach już
    # zapisano. Bez stawek i danych o zdrowiu (zdanie w oknie zapisu).
    f"""CREATE TABLE IF NOT EXISTS client_feedback_sessions (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    contact_id INTEGER NULL REFERENCES contacts(id) ON DELETE SET NULL,
    held_on DATE NOT NULL,
    channel VARCHAR(16) NOT NULL DEFAULT 'phone',
    extension_outlook VARCHAR(16) NULL,
    note TEXT NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_client_feedback_sessions_channel CHECK ({CK_FEEDBACK_CHANNEL}),
    CONSTRAINT ck_client_feedback_sessions_extension CHECK ({CK_FEEDBACK_EXTENSION}),
    CONSTRAINT ck_client_feedback_sessions_note CHECK ({CK_FEEDBACK_NOTE})
)""",
    # Ocena konsultanta (kontraktu) w jednej rozmowie: jakość pracy,
    # komunikacja, samodzielność. Jeden wiersz na rozmowę i kontrakt; scalenie
    # duplikatu kontraktu rozstrzyga kolizję w ``contract_merge``.
    f"""CREATE TABLE IF NOT EXISTS client_feedback_scores (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES client_feedback_sessions(id) ON DELETE CASCADE,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    quality SMALLINT NULL,
    communication SMALLINT NULL,
    autonomy SMALLINT NULL,
    CONSTRAINT uq_client_feedback_scores_session_contract UNIQUE (session_id, contract_id),
    CONSTRAINT ck_client_feedback_scores_quality CHECK ({CK_SCORE_QUALITY}),
    CONSTRAINT ck_client_feedback_scores_communication CHECK ({CK_SCORE_COMMUNICATION}),
    CONSTRAINT ck_client_feedback_scores_autonomy CHECK ({CK_SCORE_AUTONOMY}),
    CONSTRAINT ck_client_feedback_scores_any CHECK ({CK_SCORE_ANY})
)""",
    # Zmiana rytmu kontaktu (O7–O8): od ``starts_on``, opcjonalnie do
    # ``until_on`` (potem wraca poprzedni). Kto i dlaczego — powód z listy
    # i notatka; zdarzenie ``care.cadence_set`` w śladzie HR.
    f"""CREATE TABLE IF NOT EXISTS care_cadence_periods (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    level VARCHAR(16) NOT NULL,
    starts_on DATE NOT NULL,
    until_on DATE NULL,
    reason VARCHAR(24) NOT NULL,
    note VARCHAR({SHORT_TEXT_MAX}) NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_care_cadence_periods_level CHECK ({CK_CADENCE_LEVEL}),
    CONSTRAINT ck_care_cadence_periods_reason CHECK ({CK_CADENCE_REASON}),
    CONSTRAINT ck_care_cadence_periods_until CHECK ({CK_CADENCE_UNTIL})
)""",
)

#: Imię i nazwisko konsultanta z karty Compassa (migracja 0474, 18.10.2026).
#: Compass nie wiąże kontraktora z kandydatem, więc import paruje kartę
#: z kontraktem po kliencie, nazwisku i dacie rozmowy; karta bez pewnej pary
#: czeka bez kontraktu, a Delivery Lead widzi przy niej, o kogo chodzi.
PERSON_NAME_MAX = 200
TECH_CARD_PERSON_DDL: tuple[str, ...] = (
    "ALTER TABLE tech_cards ADD COLUMN IF NOT EXISTS compass_person_name "
    f"VARCHAR({PERSON_NAME_MAX}) NULL",
)

COLUMN_DDL: tuple[str, ...] = (
    # Opiekun kontraktu; pusty = domyślny opiekun klienta, potem DL kontraktu.
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS care_owner_user_id INTEGER NULL "
    "REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE clients ADD COLUMN IF NOT EXISTS default_care_owner_user_id INTEGER NULL "
    "REFERENCES users(id) ON DELETE SET NULL",
    # Struktura u klienta: przełożony (kontakt tego samego klienta) i dział.
    "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS reports_to_contact_id INTEGER NULL "
    "REFERENCES contacts(id) ON DELETE SET NULL",
    "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS client_area_id INTEGER NULL "
    "REFERENCES client_areas(id) ON DELETE SET NULL",
    # „Pomiń” z powodem (etap 3) — baza sprzed zmiany dostaje kolumny tu.
    "ALTER TABLE contract_care_plan_items ADD COLUMN IF NOT EXISTS skip_reason "
    "VARCHAR(24) NULL",
    "ALTER TABLE contract_care_plan_items ADD COLUMN IF NOT EXISTS skip_note "
    f"VARCHAR({SHORT_TEXT_MAX}) NULL",
    *TECH_CARD_PERSON_DDL,
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_contracts_care_owner "
    "ON contracts (care_owner_user_id) WHERE care_owner_user_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_care_conversations_contract "
    "ON care_conversations (contract_id, occurred_on)",
    "CREATE INDEX IF NOT EXISTS ix_contract_care_plan_items_due "
    "ON contract_care_plan_items (status, due_on)",
    "CREATE INDEX IF NOT EXISTS ix_tech_cards_client "
    "ON tech_cards (client_id, interview_on)",
    "CREATE INDEX IF NOT EXISTS ix_tech_cards_contract ON tech_cards (contract_id)",
    "CREATE INDEX IF NOT EXISTS ix_tech_card_skills_skill ON tech_card_skills (skill_id)",
    "CREATE INDEX IF NOT EXISTS ix_tech_card_vendors_vendor ON tech_card_vendors (vendor_id)",
    "CREATE INDEX IF NOT EXISTS ix_client_areas_client ON client_areas (client_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_redeploy_queue_items_active "
    f"ON redeploy_queue_items (contract_id, reason) WHERE {REDEPLOY_ACTIVE_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_redeploy_queue_items_status "
    "ON redeploy_queue_items (status, due_on)",
    "CREATE INDEX IF NOT EXISTS ix_client_feedback_sessions_client "
    "ON client_feedback_sessions (client_id, held_on)",
    "CREATE INDEX IF NOT EXISTS ix_client_feedback_sessions_contact "
    "ON client_feedback_sessions (contact_id, held_on)",
    "CREATE INDEX IF NOT EXISTS ix_client_feedback_scores_contract "
    "ON client_feedback_scores (contract_id)",
    "CREATE INDEX IF NOT EXISTS ix_contacts_reports_to "
    "ON contacts (reports_to_contact_id) WHERE reports_to_contact_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_contacts_client_area "
    "ON contacts (client_area_id) WHERE client_area_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_care_cadence_periods_contract "
    "ON care_cadence_periods (contract_id, starts_on)",
)


def _add_check(table: str, name: str, condition: str) -> str:
    return f"""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{name}') THEN
            ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({condition});
        END IF;
    END $$"""


#: Forma „Teams” rozmowy z menedżerem (0511, makieta R4 z 22.10.2026). Jedyna
#: definicja poszerzenia — ten sam blok wykonuje migracja i entrypoint
#: (przez ``hr_schema_bundle``), więc start kontenera nie zwęzi więzu z powrotem.
FEEDBACK_TEAMS_DDL: tuple[str, ...] = (
    f"""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM information_schema.tables
                   WHERE table_name = 'client_feedback_sessions')
           AND NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'ck_client_feedback_sessions_channel'
              AND pg_get_constraintdef(oid) LIKE '%teams%'
        ) THEN
            ALTER TABLE client_feedback_sessions
                DROP CONSTRAINT IF EXISTS ck_client_feedback_sessions_channel;
            ALTER TABLE client_feedback_sessions
                ADD CONSTRAINT ck_client_feedback_sessions_channel CHECK ({CK_FEEDBACK_CHANNEL});
        END IF;
    END $$""",
)


#: Baza sprzed etapu 3 (0462 nie jest wdrożona, ale bazy lokalne i testowe ją
#: mają): rodzaj ``cadence`` w CHECK-u planu i CHECK-i powodu „Pomiń”.
#: Bloki podmieniają/dokładają ograniczenie tylko przy starej definicji.
CONSTRAINT_DDL: tuple[str, ...] = (
    f"""DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'ck_contract_care_plan_items_kind'
              AND pg_get_constraintdef(oid) LIKE '%cadence%'
        ) THEN
            ALTER TABLE contract_care_plan_items
                DROP CONSTRAINT IF EXISTS ck_contract_care_plan_items_kind;
            ALTER TABLE contract_care_plan_items
                ADD CONSTRAINT ck_contract_care_plan_items_kind CHECK ({CK_PLAN_KIND});
        END IF;
    END $$""",
    _add_check(
        "contract_care_plan_items",
        "ck_contract_care_plan_items_skip_reason",
        CK_PLAN_SKIP_REASON,
    ),
    _add_check(
        "contract_care_plan_items", "ck_contract_care_plan_items_skip", CK_PLAN_SKIP
    ),
    *FEEDBACK_TEAMS_DDL,
)
DATA_DDL: tuple[str, ...] = ()

TABLES: tuple[str, ...] = (
    "client_areas",
    "tech_vendors",
    "care_conversations",
    "contract_care_plan_items",
    "tech_cards",
    "tech_card_skills",
    "tech_card_vendors",
    "skill_review_queue",
    "redeploy_queue_items",
    "client_feedback_sessions",
    "client_feedback_scores",
    "care_cadence_periods",
)

DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP INDEX IF EXISTS ix_contacts_reports_to",
    "DROP INDEX IF EXISTS ix_contacts_client_area",
    "ALTER TABLE contacts DROP COLUMN IF EXISTS reports_to_contact_id",
    "ALTER TABLE contacts DROP COLUMN IF EXISTS client_area_id",
    "DROP INDEX IF EXISTS ix_contracts_care_owner",
    "ALTER TABLE contracts DROP COLUMN IF EXISTS care_owner_user_id",
    "ALTER TABLE clients DROP COLUMN IF EXISTS default_care_owner_user_id",
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
