# Scenariusz: „Zostań trenerem” i „Poleć inżyniera” ze strony (0806)

Reguły: `docs/claude/integracje/strona-www-trener-i-polecenie.md`,
`docs/claude/ludzie/szkolenia-i-trenerzy.md`.

Backend gałęzi z `WEBSITE_APPLICATIONS_TOKEN` (dowolna wartość testowa, `-e` przy
`docker compose … run`); strona to `curl` z tym tokenem. Same fikcyjne osoby
(Anna Przykładowa, Jan Testowy) i adresy `@example.com`.

Kto → co robi → co widzi następny:

1. **Strona WWW** (`curl`): `POST /api/public/website-trainer-applications` (pola
   z tabeli w regule) → 201. Drugie wysłanie z tym samym adresem → 201, ten sam wiersz.
   Zły token → 401.
2. **TCM** — Szkolenia → „Zgłoszenia trenerów”: licznik nowych na zakładce, karta
   w „Nowe” (tematy, pierwsze szkolenie, próbka jako link). „Umów rozmowę” z notatką →
   karta w „Rozmowa”; „Do bazy trenerów” → „W bazie trenerów”.
3. **Rekruter** nie ma zakładki „Zgłoszenia trenerów”, a `GET /api/trainings/market-applications`
   jego tokenem → 403.
4. **Strona WWW** (`curl`): `POST /api/public/website-referrals` dla nowej osoby (e-mail)
   i dla osoby z samym LinkedIn → 201. Mailpit (`http://localhost:8125`) bez maila na
   adres polecanej osoby.
5. **Rekruter** — Zgłoszenia: wpis z opisem „Polecenie ze strony WWW od…”, „pasuje do
   kandydata #…”; profil kandydata ma źródło „polecenie”. Zakładka „Polecenia”: „Rozmowa”,
   potem „Zaczął projekt” z kwotą 999 (odmowa) i 2500 (zapis). Nie ma „Wypłacona”, a
   `POST /api/candidate-referrals/{id}/paid` jego tokenem → 403.
6. **Finanse** — Zgłoszenia → „Polecenia” → „Zaczął projekt”: „Wypłacona” → potwierdzenie →
   karta w „Premia wypłacona”.

Uwagi: pętle w tle stoją na stagingu, więc „brak maila” sprawdza też test
`tests/test_website_referrals.py` (każde wyjście na zewnątrz przerywa).
