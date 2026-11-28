# Scenariusz: zgłoszenie kandydata z zewnątrz (strona kariery, `/apply/[token]`)

Reguły: `docs/claude/podstawy/skan-plikow-i-altcha.md`,
`docs/claude/rekrutacja-tworzenie/strona-kariery-dla-kandydatow.md`.

Kto → co robi → co widzi następny:

1. **Rekruter** ma rekrutację z zatwierdzonym opisem publicznym i link kariery
   (`/kariera/r/<slug>` na froncie gałęzi). Id rekrutacji i slug do paragonu.
2. **Kandydat** (bez logowania, osobna karta bez ciasteczek) otwiera ofertę, dołącza
   czyste CV (PDF), zaznacza zgodę, „Wyślij zgłoszenie”. W sieci: `GET
   /api/public/career/challenge` po pierwszym dotknięciu formularza, potem `POST
   /api/public/career/apply` z polem `altcha` → 201, ekran „CV jest u …”.
3. **Kandydat** wysyła drugi raz z plikiem EICAR w DOCX (`tests/_clamd_fake.py::eicar_docx`,
   zapisany do pliku) → komunikat przy polu CV „Nie udało się przyjąć pliku. Wyślij CV
   ponownie w PDF albo DOCX.”, w logu backendu gałęzi `event_kind=file_scan`,
   `scan_verdict=infected`. Nowej osoby w bazie nie ma.
4. **Kandydat** — powtórka tego samego rozwiązania ALTCHA (`curl` z payloadem z kroku 2)
   → 400. Bez pola `altcha` po `MISSING_ALLOWED_UNTIL` → 400 (przed tą datą przechodzi
   z `missing_allowed` w logu).
5. **Rekruter** widzi zgłoszenie z kroku 2 (Tablica rekrutacji, etap „Nowi”, albo dzwonek
   „Nowe zgłoszenie”); zgłoszenia z kroku 3 nie ma.
6. Zatrzymany clamd (`docker stop` kontenera clamav gałęzi) → kandydat dostaje „Nie możemy
   teraz sprawdzić pliku…”, `/api/health` → `checks.clamav = unhealthy`.

Uwagi: backend gałęzi potrzebuje `CLAMAV_HOST` wskazującego clamd stagingu (usługa
`clamav` w `docker-compose.staging.yml`); bez niego skan jest wyłączony i krok 3 przejdzie.
