# Przegląd przed DZ + jedna osoba wysyłająca do Cpro (23.09.2026)

Zgłoszenie Artura po wdrożeniu kolejki „Czeka na Ciebie" (#1724):

> Dominik potrzebuje od razu do analizy CV wygenerowane dla klienta, oryginalne
> CV kandydata i zapytanie od klienta, żeby szybko porównać. Sprawdza boldy
> i czy wszystko z must-have jest w CV i ujęte w doświadczeniu tam, gdzie
> występuje. Dodaj Lunę do podpowiedzi. Do Cpro nie wysyła inna osoba per
> kandydat, tylko jedna osoba per cały proces — potrzeba przekierowań do
> rekrutacji, żeby wrzucać do Cpro z poziomu rekrutacji.

## Co zmienia się dla ludzi

**Dominik / Delivery Lead (kolejka DZ).** Przy każdej osobie jest „Sprawdź".
Okno pokazuje obok siebie CV dla klienta, oryginalne CV i zapytanie klienta,
z podświetlonymi must-have. Nad nimi tabela: czy must-have jest w CV, czy jest
pogrubiony i czy jest w każdej roli, w której występuje w oryginale (z nazwą
roli, w której go brakuje, albo roli pominiętej w CV). Obok podpowiedzi
GPT-6 Luny — co dopisać, gdzie, z cytatem z CV. „Zatwierdź DZ" jest w tym
samym oknie.

**Wysyłka do Cpro (Nordea).** Osobę ustawia się raz dla rekrutacji — paskiem
„Do Cpro wysyła" nad Tablicą albo w kolejce, gdzie „Do wysłania do Cpro" jest
pogrupowane po rekrutacji. „Wysyłaj z rekrutacji" prowadzi na Tablicę.
Przełącznik „Gotowy do Cpro" w karcie osoby nie pyta już, kto wyśle.

## Jak to działa

| Element | Miejsce |
|---|---|
| Sprawdzenia must-have (kod, deterministyczne) | `backend/app/services/dz_review.py` → `analyze` |
| Podpowiedzi Luny, pamięć wyników | `dz_review.generate_hints`, tabela `dz_review_hints` |
| Trasy | `GET/POST /api/board-tasks/dz/{stage_id}/review|hints`, `PUT /api/board-tasks/cpro/jobs/{job_id}/sender` |
| Osoba wysyłająca | `jobs.cpro_sender_id` (0353), snapshot kolejki: `cpro_sender_id or task_assignee_id` |
| UI | `DzReviewDialog.tsx`, `BoardTasksPanel.tsx`, `CproSenderBar.tsx`, harness `/preview/dz-review` |
| Klucz AI | `AIFeatureKey.dz_review` → GPT-6 Luna, zapas Sonnet 5 (F22) |

Zasady:

- **Luna jest doradcza.** Brak klucza, błąd dostawcy albo zła odpowiedź dają
  `status: "unavailable"` i komunikat w oknie — sprawdzenia kodu i „Zatwierdź
  DZ" działają dalej. Wynik jest pamiętany per (wiersz etapu, skrót wejścia),
  więc ponowne otwarcie tej samej osoby z tym samym CV nie płaci drugi raz.
  Cytat, którego nie ma w żadnym z dwóch tekstów, jest usuwany.
- **Pogrubienia szablonu się nie liczą** (nagłówek roli, etykiety „…:"), żeby
  stanowisko „Senior Java Developer" nie udawało pogrubionego must-have.
- **Role w CV dla klienta** rozpoznajemy po znacznikach generatora
  (`data-cv-section="role"/"employer"`); CV bez znaczników dzielimy po nazwach
  firm z odczytu oryginału (`candidate.experience`).
- **Treść CV idzie do przeglądarki jako bloki tekstu** z flagą pogrubienia,
  nigdy jako HTML.
- **Dostęp:** przegląd i podpowiedzi — tylko role z prawem DZ (admin, DL,
  Head of Recruitment) z dostępem do rekrutacji; osobę wysyłającą ustawia
  członek zespołu rekrutacji, a osobę spoza zespołu dopisać może tylko rola DZ.

## CV zrobione poza generatorem (poprawka po wdrożeniu)

Odczyt produkcji po wdrożeniu: żadna z 18 osób w „Czeka na DZ" nie miała CV
dla klienta w NEXUSIE — u Nordei CV powstaje poza generatorem i leży w plikach
kandydata z Traffita („…B2B…", DOCX; 16 z 18 osób ma taki plik). Przegląd
bierze więc: CV firmowe etapu → CV z generatora → **plik kandydata z „B2B"
w nazwie** (najpierw ten z nazwą klienta, potem najnowszy).

- DOCX czytamy python-docx: pogrubione runy, listy Worda (numeracja albo styl
  listy), nagłówki (styl albo krótka linia wersalikami), a w sekcji
  doświadczenia w pełni pogrubiony akapit spoza listy to nagłówek roli.
- PDF daje sam tekst: pogrubienia „nie do sprawdzenia (PDF)" (`bolded: null`),
  nie „brak".
- Gdy w CV dla klienta nie da się rozpoznać ról, tabela nie twierdzi, że rola
  jest pominięta — pokazuje role z oryginału z dopiskiem „sprawdź ręcznie"
  (`roles_checked: false`).

## Weryfikacja

- Backend: `test_dz_review.py` (12), `test_board_tasks.py`, kontrakty AI,
  pipeline i rekrutacje — 146 + 93 passed na świeżo zmigrowanej bazie.
- Frontend: vitest `--changed` 400 passed, tsc i ESLint czyste.
- Harness `/preview/dz-review` przeklikany: desktop 1440 px i telefon 375 px
  (strona bez przewijania w poziomie, tabela przewija się w swoim polu).

## Poza zakresem

- Oryginalna treść maila klienta nie jest zapisywana przy tworzeniu rekrutacji
  (`/jobs/new` tylko ją odczytuje) — „Zapytanie klienta" to must/nice, opis
  rekrutacji i „O projekcie" z Championa.
- `candidate_stages.task_assignee_id` (0348) zostaje jako zapas dla rekrutacji
  bez ustawionej osoby; nie jest już nigdzie wybierany w UI.
