# Audyt manualny UI 13–15.09.2026 — raport naprawczy

Wejście: zbiorczy handoff audytu (77 usterek B01–B77 i ustalenia OP01–OP02).
Materiał dowodowy audytu zawiera dane produkcyjne i zostaje lokalnie, poza
repozytorium. Tu wyłącznie identyfikatory B/OP, przyczyna i stan.

Weryfikacja kodu: `ea38dbcf` (15.09 rano), potem na każdym świeżym `origin/main`
przed zmianą — równolegle działała druga sesja z własną listą B01–B53.

Legenda statusu:

- **Naprawione w tym PR** — defekt odtworzony w kodzie i poprawiony.
- **Już naprawione** — defekt nie występuje na `main`; retest audytu albo kod.
- **Poza kodem** — wymaga decyzji albo operacji na danych/sekretach.
- **Retest** — kod poprawny, potrzebny retest na wdrożeniu w aktywnej karcie.

## Naprawione w tym PR

| ID | Przyczyna | Zmiana |
|---|---|---|
| B08 | Równe dzielenie szerokości dnia na wszystkie nachodzące wydarzenia — przy 3+ pasy wąskie jak ikona | Najwyżej 2 pasy, reszta w chipie „+N” z listą (`limitVisibleLanes`) |
| B12 | Odczyt CV w tle kończy się po cichu; brak następnego kroku | `POST /api/candidates/{id}/cv/reparse` + „Odczytaj CV ponownie” w komunikacie profilu |
| B14 | Podgląd zostawiał surowe `{{…}}` (przykładowe dane usunięte celowo w M11-B06) | Zmienne jako opisane etykiety; nieznana zmienna oznaczona |
| B22 | Przywracanie fokusu szukało tylko wiersza tabeli, nie kafelka | Atrybut fokusu na przycisku kafelka |
| B23 | Zakładka Timeline renderowała błąd/ładowanie jako „Brak wpisów” | Osobne stany ładowania i błędu; na produkcji historia ładuje się poprawnie |
| B24 | Lista rekrutacji nie była filtrowana po kliencie | Lista i reset wyboru zależne od klienta |
| B54 | Instrukcja odsyłała do nieistniejącej zakładki i surowego typu | Aktualna ścieżka „Dane handlowe → Dodaj konflikt → Obecne zatrudnienie” |
| B55 | Stara ścieżka „Zespół → Kontakty”, gwiazdka vs serce | „Kontakty klienta → ikona serca → Kluczowa relacja” |
| B56 | `html.dark[data-soft]` nie nadpisywał jasnego `--background` | Ciemne tło w tym bloku + test kontraktu CSS |
| B57 | Rozwinięcie pod kursorem zmieniało wysokości nagłówków i odstępy | Stałe pionowe wymiary, rozwinięcie jako nakładka |
| B58 | Kolumna „Stawka” czytała stawkę etapu, filtr — stawkę profilu | Stawka z profilu; stawka z procesu jako druga linia |
| B59 | Prompt uzasadnienia nie dostawał lokalizacji, trybu pracy ani dostępności | Fakty kandydata i oferty w prompcie (v3, cache odświeża się leniwie) |
| B60 | `tags.join` na obiektach importu; zapis gubił źródło pozyskania | Pole edytuje tylko napisy, obiekty zachowane, niezmienione tagi poza PATCH |
| B61 | Karta pokazywała `repr` wyjątku Graph | `last_error_code` i polska wskazówka; surowy tekst w szczegółach |
| B62 | Pasek AI Matching czytał wymagania i budżet tylko ze strony wyników przeglądu; akceptacja szkicu Championa nie synchronizowała kolumn | Zapisany kontrakt wymagań + `effective_budget_hourly`; synchronizacja kolumn przy akceptacji |
| B66 | Czas modyfikacji rekordu obok „Brak aktywności” | Czas podpisany „Aktualizacja:” |
| B67 | Szkielet w kolorze tła; dłuższe budowanie planu | Widoczny komunikat i dłuższy timeout (patrz „Retest”) |
| B69 | Następca z dnia wykrycia klasyfikowany jako opóźnienie „0 dni” | Na czas (decyzja 15.09.2026); instrukcja DL zaktualizowana |
| B70 | Stack i luki z całej wiedzy o kliencie; pytania bez filtra po wymaganiach | Stack z wymagań roli; pytania o obce technologie odpadają |
| B71 | Licznik liczył każdego z wierszem etapu, także odrzuconych | `countInProcess` z kanbana |
| B72 | Dok oferty czytał miesięczną migawkę `salary_max` | Ten sam budżet PLN/h co nagłówek; migawka podpisana |
| B73 | Rekrutacje ukrytego klienta technicznego w rejestrze i dashboardach | `job_client_listed_clause` (hidden / deleted) |
| B74 | `Button asChild` wkładał do `Slot` dwa dzieci | Sam `Slot` z jednym dzieckiem; test mutacyjny |
| B75 | Nagłówek z wynikiem ostatniego biegu podpisany „dla całej skrzynki” | „W ostatnim sprawdzeniu: …” + odesłanie do zakładek |
| B76 | „po {n} dniach” na sztywno | „po 1 dniu” / „po N dniach” |
| B77 | Wierszowe powody modelu po angielsku | Prompt v7 + zamiana angielskich powodów przy odczycie i wyświetleniu |

## Już naprawione przed tym PR

B01, B02, B03, B04, B05, B06, B07, B09, B10, B11, B13, B15, B16, B17, B18,
B19, B20, B21, B25, B26, B27, B28, B29, B30, B31, B32, B33, B34, B35, B36,
B37, B38, B39, B40, B41, B42, B43, B44, B45, B46, B47, B48, B49, B50, B51,
B52, B53, B64, B65, OP01 (monitor Sentry kończy się błędem bez tokenu),
OP02 (odzyskiwanie synchronizacji M365 — #1530–#1533).

Wyrywkowo potwierdzone w kodzie: B01, B02, B16, B30. B04 i B64 były naprawione
po ostatnim retescie audytu (#1510, #1529) — do retestu.

## Poza kodem

| ID | Stan | Następny krok |
|---|---|---|
| B63 | Przerwy 503 w trakcie wdrożenia (jeden kontener, odtwarzanie w miejscu, migracje przy starcie) | Decyzja architektoniczna F03; do tego czasu merge poza godzinami pracy |
| B68 | Techniczna wiadomość testowa w czacie kandydata (dane) | Usunięcie istniejącym endpointem po zgodzie właściciela |
| UAT-01/02 | Backup drill i E2E bez sekretów | Uzupełnienie sekretów przez administratora |

## Retest

- **B67** — przy nawigacji w aplikacji podgląd portfela ładuje się w ~3 s.
  Obserwacja „pusta strona” przy pełnym ładowaniu pochodziła z karty
  przeglądarki w tle (zamrożony renderer: brak żadnych żądań, także na innych
  podstronach Ustawień). Retest w aktywnej karcie.
- Wszystkie pozycje z tabeli „Naprawione w tym PR” — kroki z handoffu na
  wdrożeniu, tylko odczyt.

## Weryfikacja lokalna

- Backend: `ruff check app/` i `ruff format --check app/` zielone; testy
  w CI (lokalnie brak Pythona 3.12).
- Frontend: `tsc --noEmit` zielony; testy dotkniętych obszarów (vitest) zielone;
  eslint bez błędów.
