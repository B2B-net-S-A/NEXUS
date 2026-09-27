# Audyt NEXUS — runda 10 (27.09.2026)

Baza: `724853ab6` (końcówka gałęzi rundy 9, scalonej jako PR #1871 → `b5463ca17`). Naprawa: PR rundy 10 (gałąź `claude/audit-r10-fixes`). To ostatnia runda serii.

## Przebieg

- **Audyt:** 20 agentów tylko do odczytu. Trzech sprawdzało poprawki rundy 9 (V1–V3), piętnastu obszary dotąd płytko audytowane (N1–N15: pulpit i metryki, Insights, poczta zamówień, Finanse → Braki, import MD, notatki i czat, Targ i propozycje, narzędzia admina, pieniądze Rady, powierzchnie publiczne, import Traffita, infrastruktura startu, import/eksport, dokumenty B2B, frontend), dwóch przekrojowo (X1 typy i daty, X2 reguły rekrutacji).
- **Znaleziska:** ~170, w tym 7 wysokich: `/preview/*` publiczne na produkcji z prawdziwymi nazwiskami, klientami i stawkami (N10-1); sandbox szablonów maili bez limitów operacji → OOM jedynego procesu (V3-1, luka R9-N10-7); import MD bez numeru wybierał jedyną aktywną linię innego klienta albo innej osoby (N5-1); „Pomiń” w propozycjach działało tylko w skrzynce (N7-1); metryki pulpitu per osoba liczyły CTE atrybucji dwa razy na kafel na osobę (N1-1); faktury bez groszy, a puste pole = 0 zł (X1-1); retencja CV brała szablon zamiast szkicu CV firmowego (V1-1 — przy wyłączonej retencji bez skutku, ale naprawione).
- **Testy manualne UI Codexa (26–27.09):** osobny raport z przeklikania aplikacji od A do Z — 27 ustaleń F01–F27, z czego większości audyt kodu nie znalazł. Naprawione w tej samej gałęzi, raport i lekcje: [manual-ui-codex-2026-09-26.md](manual-ui-codex-2026-09-26.md).
- **Naprawa:** 26 agentów (21 do audytu kodu, 5 do ustaleń Codexa), każdy we własnym worktree. Scalenie: pięć gałęzi dodało migrację o numerze 0391 — przenumerowane na 0391–0395 i spięte w jeden łańcuch; konflikty poza tym tylko w stemplach instrukcji zamówień i przewodników.
- **Po scaleniu:** 4 przeglądy kodu i dwa pełne biegi CI. Przegląd złapał 1 problem w samej poprawce (pominięcie niezmienionego rekordu Traffita odcinało ponowienie plików w delcie — dodane okno źródła). Pełne CI złapało 1 prawdziwy błąd (porównanie `pipelinestage = varchar` w metrykach pulpitu → 500 na `/api/dashboard/stats` i `/api/admin/snapshot`) oraz nieaktualne kontrakty testów po przenumerowaniu migracji i fikcyjnych danych harnessów.

## Decyzje Artura

| Temat | Decyzja |
|---|---|
| `/preview/*` na produkcji (N10-1) | Fikcyjne dane; na produkcji tylko po zalogowaniu; każdy harness blokuje zapisy |
| Kto potwierdza aneks zmiany stawki (N14) | Admin, Finanse i Delivery Lead u klienta z portfela |
| Stawka kandydata w propozycjach (N7) | Widoczna dla wszystkich ról; stawka do klienta bez zmian |
| Klauzula RODO strony kariery (F16) | rodo@b2bnetwork.pl, przechowywanie 3 lata od zgłoszenia |
| Klauzula zgody w CV (F20) | Zostaje stała klauzula; ekran tylko ją opisuje |

## Najważniejsze poprawki

- **Bezpieczeństwo:** sandbox Jinja z limitem wyniku operacji (`+ ~ % join replace` itd.) i przerwaniem przy przyroście pamięci; webhook M365 ≤ 1000 powiadomień w żądaniu; `/apply/{token}` wymaga zatwierdzonego opisu publicznego; stan OAuth JJIT z nonce. `/preview/*`: fikcyjne dane (strażnik testem), logowanie na produkcji, strażnik sieci blokujący zapisy.
- **Pieniądze i Finanse:** faktury NUMERIC(14,2), numer obowiązkowy, kwota > 0 (0394); `fold_money` liczy kontrakty bez nogi przychodowej (`without_revenue_leg`); ranking klientów regułą W1; Braki w epizodach — kolejny brak tego samego zamówienia po przedłużeniu powstaje (0392), odhaczenie po kluczu z epizodem.
- **Import MD:** wiersz bez numeru trafia wyłącznie na linię tej samej osoby u tego samego klienta; statusy `invoice_unreadable` i `order_exhausted` (0393); numer następcy cofa podział na poprzedniku.
- **Poczta zamówień:** odmowa zapisu u klienta scalonego; `ACTION_FUTURE` na linii MD → `ACTION_GROUP`; PDF Nordei bez tekstu = „Nieudane” zamiast odrzucenia; NUL i `DataError` nie zamrażają skrzynki; kwoty w powodach bramki maskowane dla ról bez finansów.
- **Rekrutacja:** zakres „moja praca” zna przypisania requestów; `/move` na świeżą parę zakłada blokadę 12 h i `entry_source`; zmiana/wyczyszczenie hiring managera przy aktywnym wecie = 409; przerwana generacja CV wraca do kolejki raz; `request_stage` „champion” nie przykrywa „Klient milczy”/„Zakończony”; Onboarding = „Zatrudniony”.
- **Targ i propozycje:** pominięci nie wracają z przeglądu, podobnych i rekomendacji; skan Targu przez te same bramki co pipeline (w procesie, weto, tylko UoP); stawka kandydata jawna.
- **Traffit:** poprawki z NEXUSA wygrywają z importem (znaczniki ręczne: e-mail, telefon, LinkedIn, status, kontakty, pule; nagrobki notatek 0395); rekord bez zmian (`traffit_payload_sha`) nie jest przepisywany; `safe_db_error` bez treści wiersza.
- **Infrastruktura:** alembic przy starcie z `lock_timeout` 10 s / `statement_timeout` 20 min; umowy ramowe z manifestu portfela nieedytowalne (koniec `deep` 503 na stałe); downgrade 0363/0368/0374 odmawia; ogon alembica do Sentry bez `DETAIL`; `checks.job_portals` bez fałszywej zieleni.
- **Admin i backfille:** single-flight przed startem korutyny, kursory w `app_settings`, znacznik „brak wyniku” w `cv_field_backfill`; ręczna zmiana głównej kategorii synchronizuje slug.
- **Metryki i Insights:** jedna migawka firmy (60 s) dla metryk per osoba; „Aktywność zespołu” z prawdziwych źródeł (rozmowy z `client_interview`, telefony, placementy); roczny udział top klienta liczony za rok; okresy 1000–9000.
- **Eksport:** `safe_cell` usuwa znaki niedozwolone w XLSX (wcześniej 500 każdego eksportu z takim znakiem).
- **Dokumenty B2B:** porozumienie o rozwiązaniu z `last_service_date`; wypowiedzenie Partnera podpina kontrakt; kwoty ≥ 1 mln słownie; cofnięcie wypowiedzenia czyści migawkę.
- **Ustalenia Codexa:** m.in. automat ruchu karty tylko od „CV wysłane” (F09), koniec współpracy przed startem = 422 (F27), nakładające się przedłużenia = 409 (F15), słowa kluczowe i porównanie czytają `verified_tech` (F17/F18), nazwisko z dwóch słów dosłownie (F06), generator CV trzyma się lat i stanowiska ze źródła (F19/F21), link z QC otwiera edytor (F22), angielskie słowa w szablonie EN (F25). Pełna tabela w raporcie Codexa.

## Znalezione, poza zakresem tej rundy

- `/bulk-move` nie zapisuje `entry_source`; `request_status_expr` (drugie lustro) ma starą regułę championa.
- `talent_pool_cc` / `job_cc` nie rozpoznają polskich nazw ról danych.
- `window.confirm` nadal w 6 plikach frontu (zamraża automatyzację przeglądarki).
- Callback M365 trzyma PKCE w stanie (bliźniak poprawionego JJIT); sandbox `contract_templates` bez limitów operacji (renderują tylko admin/DL).
- Umiejętności ze screeningu nie wchodzą do korpusu słów kluczowych.
- `EditOrderDialog` nie sprawdza nakładania okresów przed wysłaniem (serwer odmawia 409).
- F07 (prospekt bez umowy w zakładce „podpisana współpraca”) — poprawiony tylko opis, reguła zakładki czeka na decyzję. F23 — dokument nie przechodzi na nowy wiersz etapu, karta czyta parę.
- `preview-chromium` na stacku E2E z flagą `NEXT_PUBLIC_PREVIEW_PUBLIC` niezweryfikowany na żywym biegu nocnym.
- Po udanej zmianie hasła kandydat/pracownik prawdopodobnie zostaje wylogowany (niepotwierdzone).
- Komentarze w modelach wspominają „0391” przy migracjach przenumerowanych na 0392–0395.

## Sprawdzone i czyste

Kolejność blokad kontrakt → zamówienia w nowych ścieżkach MD; płacące konkursy (kolejność nagród, migawki progów i punktacji); redakcja kwot DL w nowych polach Insights; bramki sekcji na nowych trasach (kontrakt `test_section_ceiling_contract.py`); lustro DDL 0391–0395 w `entrypoint.sh`.
