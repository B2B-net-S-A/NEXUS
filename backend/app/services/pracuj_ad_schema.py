"""Ogłoszenia ze strefy Pracuj.pl i aplikacje na nie — SQL migracji 0754 i lustra.

JEDNO źródło instrukcji dla ``alembic/versions/0754_pracuj_ads.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony); test
``test_pracuj_ads.py`` sprawdza, że entrypoint je importuje.

Zgłoszenie DL-a z 20.11.2026: aplikacje z ogłoszeń na Pracuj.pl nie trafiały
do rekrutacji ogłoszenia. Kopia produkcji z 22.11: 8 292 zdarzeń źródła
„Pracuj.pl” z 30 dni, żadne z rekrutacją. Strefa pracodawcy zna tylko swój
numer ogłoszenia (np. 8819139), a link wklejany przy „Oznacz jako
opublikowane” ma inny numer albo GUID — z niego numeru ze strefy nie wyliczymy,
a tytuły się powtarzają (trzy aktywne „Tester Manualny (k/m/x)”).
Decyzja Artura z 23.11.2026 (wariant A): scraper oddaje listę ogłoszeń ze
strefy, a Delivery Lead wybiera, które ogłoszenie należy do rekrutacji.

* ``pracuj_ads`` — ogłoszenie ze strefy: numer, tytuł, kiedy import je
  widział, liczba aplikacji z listy strefy, rekrutacja (``job_id``, wybór
  człowieka) albo „rekrutacja wewnętrzna” (``internal_at``: nie dotyczy NEXUSA).
* ``pracuj_ad_applications`` — kto aplikował na które ogłoszenie, zapisywane
  przy każdej aplikacji, także zanim ogłoszenie ma rekrutację. Z tego
  dociągamy zaległe aplikacje do „Nowi” w chwili połączenia.
"""

from __future__ import annotations

ADS_DDL = (
    "CREATE TABLE IF NOT EXISTS pracuj_ads ("
    "strefa_id VARCHAR(32) PRIMARY KEY, "
    "title VARCHAR(255) NOT NULL, "
    "applications INTEGER NOT NULL DEFAULT 0, "
    "first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "job_id INTEGER NULL REFERENCES jobs(id) ON DELETE SET NULL, "
    "paired_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "paired_at TIMESTAMPTZ NULL, "
    "internal_at TIMESTAMPTZ NULL, "
    "internal_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL)"
)
ADS_JOB_INDEX = "CREATE INDEX IF NOT EXISTS ix_pracuj_ads_job_id ON pracuj_ads (job_id)"

APPLICATIONS_DDL = (
    "CREATE TABLE IF NOT EXISTS pracuj_ad_applications ("
    "id BIGSERIAL PRIMARY KEY, "
    "strefa_id VARCHAR(32) NOT NULL, "
    "candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE, "
    "applied_at TIMESTAMPTZ NULL, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "CONSTRAINT uq_pracuj_ad_applications UNIQUE (strefa_id, candidate_id))"
)

ALL_DDL = (ADS_DDL, ADS_JOB_INDEX, APPLICATIONS_DDL)

DOWNGRADE_DDL = (
    "DROP TABLE IF EXISTS pracuj_ad_applications",
    "DROP TABLE IF EXISTS pracuj_ads",
)
