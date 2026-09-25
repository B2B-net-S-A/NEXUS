"""Wspólny zakres zapytań Delivery Leada w /insights (body leasing).

Jedno źródło dla rankingu DL (``GET /api/insights/delivery-leads``) i portfela
DL (``GET /api/insights/delivery-leads/portfolio``). Portfel rozbija wiersz
rankingu na klientów, więc suma jego wierszy MUSI równać się nagłówkowi, a
nagłówek — wierszowi rankingu. To trzyma się tylko wtedy, gdy obie trasy
składają zapytania z TYCH SAMYCH fragmentów: rozwiązanie DL per oferta, typ
rekrutacji i definicja placementu (D2) nie mogą mieć dwóch kopii.
"""

from app.services.metric_definitions import DL_HIT_RATIO_TARGET_PCT

# Nazwa klienta i widocznosc — LUSTRO `app/services/client_identity.py`
# w surowym SQL-u (te zapytania sa tekstowe, wiec nie moga wolac helperow ORM).
#
# Bez tego ten sam klient wystepowalby na jednym ekranie pod DWIEMA nazwami:
# zakladka Klienci uzywa `client_display_name_expression()` (czyli recznej
# korekty nazwy z Traffita), a Delivery Lead pokazywalby surowe `clients.name`.
# Gorzej z `merged_into_client_id`: klient wchloniety w innego wciaz ma wlasne
# wiersze `jobs`, wiec renderowalby sie jako osobny kawalek donuta, podczas gdy
# Klienci juz go zwineli — dwoch sum nie dalo by sie uzgodnic wzrokiem.
CLIENT_DISPLAY_NAME_SQL = "COALESCE(NULLIF(BTRIM(c.display_name), ''), c.name)"
CLIENT_VISIBLE_SQL = (
    "c.hidden IS FALSE AND c.archived_at IS NULL AND c.merged_into_client_id IS NULL"
)


# Próg wejścia do „Ligi Mistrzów DL" (InfraReporter) — jedna stała w repo
# (`metric_definitions`, liść grafu importów, więc bez wciągania `reports`).
HIT_RATIO_TARGET_PCT = DL_HIT_RATIO_TARGET_PCT

# Rozwiązanie DL dla oferty: własny `delivery_lead_id`, a gdy pusty — główny
# opiekun klienta (`is_head`). Jedno źródło dla wszystkich trzech zapytań.
DL_HEAD_CTE = """
    dl_head AS (
        SELECT client_id, delivery_lead_user_id
        FROM delivery_lead_client_assignments
        WHERE is_head IS TRUE
    )
"""

# Bez typów rekrutacji (decyzja 25.09.2026): ranking DL liczy każdą rekrutację.
JOBS_SCOPED_CTE = """
    jobs_scoped AS (
        SELECT j.id,
               j.created_at,
               j.status,
               j.client_id,
               COALESCE(j.headcount, 1) AS headcount,
               COALESCE(j.delivery_lead_id, h.delivery_lead_user_id) AS dl_id
        FROM jobs j
        LEFT JOIN dl_head h ON h.client_id = j.client_id
    )
"""


def ratio_pct(numerator: int, denominator: int) -> float | None:
    """Udział procentowy albo ``None`` przy zerowym mianowniku.

    NIE zwraca 0.0 — konsument musi móc odróżnić „policzone, wyszło zero" od
    „nie było czego dzielić". Bez przycinania do 100%: wynik powyżej stu
    procent jest realnym sygnałem (placementy z zapytań spoza okna).
    """
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 1)
