# QC CV: tryb doradczy, role z odczytu CV, „Potwierdzone z kandydatem” (12.10.2026)

Trzy zgłoszenia zespołu z 12.10.2026 kończyły się tym samym: rekruter nie mógł
przesunąć karty. Reguły po tej zmianie:
`docs/claude/rekrutacja-tablica/qc-cv-tryb-doradczy-role-z-odczytu-potwierdzenie.md`.
Makiety: https://claude.ai/artifact/FCfDRHNjF4dg9jK9GBySvn (prywatne).

## Co było źle

| Zgłoszenie | Przyczyna |
|---|---|
| QC żąda „python lub java” w roli supportu | `dz_review.original_roles` doklejało do tekstu roli wycinek pliku od nazwy firmy do końca dokumentu — ostatnia rola wchłaniała sekcję umiejętności i kursy |
| „testing — jest w CV, a nie ma tego w oryginale”, kandydat potwierdził w rozmowie | QC czyta notatki jako źródło, ale w oknie nie było jak zapisać potwierdzenia |
| Rekruter nie ma jak przejść dalej | Obejście QC miał tylko Delivery Lead i admin; u Nordei do kolejki Cpro przekazuje rekruter |

Pomiar na produkcji przed zmianą (45 dni, tylko odczyt, same liczby): 47 par
z QC, 34 zablokowane; 17 przez „spoza oryginału”, 10 wyłącznie przez to;
13 braków „krytyczna × rola”, z czego 12 opartych wyłącznie na wycinku pliku;
26 z 41 kandydatów w QC bez opisów ról w historii profilu; 11 obejść.

## Co się zmieniło

| Obszar | Zmiana |
|---|---|
| Tryb doradczy | `CV_QC_ADVISORY` (domyślnie włączony). „Przesuń mimo uwag…” ma każdy, kto przesuwa karty, poza integracjami z tokenem OAuth. Delivery Lead dostaje dzwonek, w przeglądzie widzi baner z powodem. Obejście rekrutera działa do zwrotu karty; obejście DL i admina bez końca, jak dotąd |
| Role z oryginału | Tekst roli = stanowisko + opis + technologie z odczytu tej roli (`dz_review.role_entries`: `cv_extracted_data`, potem historia profilu). Bez opisów ról sprawdzenie ma status „sprawdź ręcznie”, nie blokuje |
| Dowód | Pozycja niesie fragment odczytu oryginału i jego rodzaj; sprawdzenie niesie stan „rola po roli” |
| Poprawki AI | Cytat nie może być listą technologii ani pochodzić z innej roli |
| Potwierdzenie | `POST …/qc/confirm` zapisuje notatkę pary („Potwierdzone z kandydatem: …”); okno pokazuje listę potwierdzeń |
| Po wdrożeniu | Zadanie startowe przelicza nieudane przebiegi QC starszej wersji reguł (plakietki na Tablicy) |

Bez migracji i bez nowych zmiennych wymaganych do działania.

## Jak wrócić do blokady

`CV_QC_ADVISORY=False` (wartość domyślna w `core/config.py` albo workflow
„Coolify set env”): obejście wraca wyłącznie do osoby z uprawnieniem
`recruitment_manage`. Podstawą decyzji ma być liczba obejść rekruterów
i cofnięć Delivery Leada po pierwszych tygodniach.

## Weryfikacja

| Co | Stan | Dowód |
|---|---|---|
| Odtworzenie zgłoszenia przed zmianą | potwierdzone | fikcyjne CV z sekcją umiejętności pod doświadczeniem → blokada w roli supportu; po zmianie test `test_skills_section_does_not_put_the_skill_into_a_role` |
| Testy backendu bez bazy | zielone lokalnie | 192 testy (QC, przegląd, rodzaje notatek, heartbeat, wzorzec dostępu, indeks reguł) |
| Testy backendu z bazą | w CI | pełny bieg na gałęzi; pierwszy bieg wskazał 4 testy naprawione w drugim commicie |
| Testy frontu | zielone lokalnie | 433 testy w 11 plikach, `tsc --noEmit`, `eslint` |
| Okno QC w przeglądarce | przeklikane lokalnie, 1280×720 | harness `/preview/cv-qc`: tryb doradczy, „Przesuń mimo uwag”, karta z dowodem, formularz potwierdzenia, lista potwierdzeń, „sprawdź ręcznie” |
| Przegląd kodu i bezpieczeństwa | zrobione | znaleziska naniesione: integracje odcięte od obejścia, obejście doradcze kończy zwrot karty, odmowa uprawnienia przed odczytem etapu, decyzja o heartbeat |
| Produkcja po wdrożeniu | niepotwierdzone w chwili pisania | do sprawdzenia: `/api/health` z SHA z maina, ponowny pomiar (oczekiwane: braki „krytyczna × rola” 13 → około 1), plakietki przeliczone |

## Poza zakresem

- Zmiana reguły na „jedna opisana rola wystarcza” — po tej zmianie dotyczyłaby 1 pary.
- Automatyczny ponowny odczyt CV dla kandydatów bez odczytu ról (26 z 41 w QC).
- Luźniejsze dopasowanie zapisu w „spoza oryginału” (7 z 31 pozycji wygląda na
  odmianę albo tłumaczenie) — ryzyko fałszywego potwierdzenia.
- Publiczny harness `/preview/cv-qc` na produkcji przekierowuje do logowania mimo
  wpisu na liście publicznych ścieżek.
