"""Blacklista z imienia kandydata → pole `status`, marker zdjęty z nazwiska.

Revision ID: 0232_strip_traffit_blacklist_marker
Revises: 0231_match_digest_notification_type
Create Date: 2026-08-18

Traffit nie miał pola „nie proponować klientom", więc rekruterzy wkleili tę
informację w imię: „[BLACKLIST] Marek", „(Blacklist) Karolina",
„[BLACK LIST]Jaromir" — dziewięć wariantów zapisu. Skutki wykryte na
produkcji 18.08.2026:

  * blacklista nie istniała w ŻADNYM polu strukturalnym. 29 osób miało
    `status = active`, więc matching, Talent Radar i picker obsady zamówień
    podawały je jak każdą inną; jedenaście dodatkowo jako „aktywnie szuka",
  * marker normalizuje się do „blacklist"/„active" i przy sortowaniu po
    imieniu wypychał te osoby na szczyt każdej listy.

Ta migracja jest bliźniakiem 0165 (`[zatrudniony]`) i robi to samo w tej samej
kolejności — z jedną różnicą, która jest tu sednem: 0165 parkowało sygnał
w `tags`, bo nie miało dla niego pola. Tutaj pole ISTNIEJE
(`CandidateStatus.blacklisted`), więc znaczenie idzie tam, gdzie patrzą filtry.

  1. Przenieś znaczenie: `status = blacklisted` dla wszystkich, którzy niosą
     marker blacklisty. MUSI być przed krokiem 2 — po zdjęciu markera nie ma
     już z czego wnosić, kogo dotyczył.
  2. Zdejmij marker (blacklisty ORAZ „[ACTIVE]", który jest tylko powtórzeniem
     pola statusu) z `name` i `lastname`.

Marker „[akcept]" jest CELOWO nietknięty: nie wiadomo, co znaczy, i nie ma
pola, do którego dałoby się to znaczenie przenieść. Skasowanie go byłoby utratą
jedynego zapisu.

Idempotentna: powtórny bieg nie znajduje już markerów. Dane, nie schemat —
downgrade jest pusty (oryginalnego tekstu nie da się odtworzyć), więc nie ma
też czego dokładać do lustra DDL w `entrypoint.sh`.
"""

from alembic import op


revision = "0232_strip_traffit_blacklist_marker"
down_revision = "0231_match_digest_notification_type"
branch_labels = None
depends_on = None


# Lustro `app/services/traffit/mappers.py::_STATUS_MARKER_RE`. Jednorazowy
# backfill i bieżący import MUSZĄ zdejmować dokładnie to samo — inaczej sync
# przywróci to, co migracja wyczyściła (upsert kandydata robi
# `name = EXCLUDED.name` bezwarunkowo).
#
# UWAGA: grupy ZWYKŁE `(...)`, nie `(?:...)` — `op.execute()` opakowuje SQL
# w SQLAlchemy `text()`, które czyta `:` w `(?:` jako parametr bindowany
# i wywala się na „A value is required for bind parameter".
_WORD = r"(black\s*-?\s*list|active)"
_MARKER = r"[[(/]\s*" + _WORD + r"\s*[])/]?" + r"|" + r"[[(/]?\s*" + _WORD + r"\s*[])/]"

# Wykrywanie blacklisty — bez „active", bo decyduje o statusie. Ogranicznik
# WYMAGANY tak samo jak przy zdejmowaniu: bez niego nazwisko zawierające ciąg
# „blacklist" (np. „Blacklista") dostawało status blacklisted, czyli ciche
# wykluczenie realnego konsultanta z propozycji.
_BL_WORD = r"(black\s*-?\s*list)"
_BLACKLIST = (
    r"[[(/]\s*" + _BL_WORD + r"\s*[])/]?" + r"|" + r"[[(/]?\s*" + _BL_WORD + r"\s*[])/]"
)


def upgrade() -> None:
    # 1. Znaczenie PRZED czyszczeniem. `status` to pole, które czytają filtry;
    #    marker w imieniu nie był widoczny dla żadnego z nich.
    op.execute(
        f"""
        UPDATE candidates
        SET status = CAST('blacklisted' AS candidatestatus)
        WHERE (name ~* '{_BLACKLIST}' OR lastname ~* '{_BLACKLIST}')
          AND status <> CAST('blacklisted' AS candidatestatus)
        """
    )

    # 2. Marker znika z imienia i nazwiska. Zwijamy zostawione spacje, obcinamy
    #    wiszące separatory i wracamy do '?', gdy pole było samym markerem
    #    (lustro fallbacku z mappera).
    op.execute(
        rf"""
        UPDATE candidates
        SET name = COALESCE(NULLIF(btrim(regexp_replace(
                       regexp_replace(name, '{_MARKER}', ' ', 'gi'),
                       '\s+', ' ', 'g'), ' -–,;/'), ''), '?'),
            lastname = COALESCE(NULLIF(btrim(regexp_replace(
                       regexp_replace(lastname, '{_MARKER}', ' ', 'gi'),
                       '\s+', ' ', 'g'), ' -–,;/'), ''), '?')
        WHERE name ~* '{_MARKER}' OR lastname ~* '{_MARKER}'
        """
    )


def downgrade() -> None:
    # Porządkowanie danych: oryginalnego tekstu markera nie da się odtworzyć.
    pass
