"""DDL „Ogłoszeń” na pulpicie (0613) — jedno źródło dla migracji, modelu i entrypointu.

Propozycja Olafa z 28.10.2026, decyzja Artura: panel „Ogłoszenia” nad
kafelkami pulpitu każdej osoby. Publikują Head of Recruitment i admin; własnego
komunikatora nie budujemy (Teams zostaje). To nie są „Komunikaty” z Ludzi
(``care_announcements`` — maile do konsultantów bez konta).

* ``announcements`` — tytuł, treść (zwykły tekst), „widoczne do” (data
  w kalendarzu firmy, włącznie), odbiorcy (pusta lista = wszyscy, inaczej
  role), przypięcie, „ważne” (dzwonek + mail obowiązkowy), zdjęcie przed
  terminem (``withdrawn_at``);
* ``announcement_reads`` — „przeczytane” per osoba.

Lustro 1:1 w ``entrypoint.sh`` — pilnuje ``test_announcements_migration.py``.
"""

TITLE_MAX = 160
BODY_MAX = 4000

ENUM_DDL = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'announcement_important'"
)

CK_AUDIENCE = "ck_announcements_audience_roles_array"
CK_AUDIENCE_SQL = "jsonb_typeof(audience_roles) = 'array'"
CK_TITLE = "ck_announcements_title_not_blank"
CK_TITLE_SQL = "length(btrim(title)) > 0"

TABLE_DDL = (
    f"""CREATE TABLE IF NOT EXISTS announcements (
    id SERIAL PRIMARY KEY,
    title VARCHAR({TITLE_MAX}) NOT NULL,
    body TEXT NOT NULL,
    visible_until DATE NOT NULL,
    audience_roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    pinned BOOLEAN NOT NULL DEFAULT false,
    important BOOLEAN NOT NULL DEFAULT false,
    author_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    notified_at TIMESTAMPTZ NULL,
    withdrawn_at TIMESTAMPTZ NULL,
    withdrawn_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT {CK_AUDIENCE} CHECK ({CK_AUDIENCE_SQL}),
    CONSTRAINT {CK_TITLE} CHECK ({CK_TITLE_SQL})
)""",
    """CREATE TABLE IF NOT EXISTS announcement_reads (
    announcement_id INTEGER NOT NULL REFERENCES announcements(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    read_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (announcement_id, user_id)
)""",
)

INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_announcements_live "
    "ON announcements (visible_until) WHERE withdrawn_at IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_announcement_reads_user "
    "ON announcement_reads (user_id)",
)
