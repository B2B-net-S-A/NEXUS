# Naprawy po przeglądzie Codexa — P0 i P1 (10–11.09.2026)

W dniach 8–10.09 Codex zmergował 46 PR-ów bez bramek. Po przeniesieniu repo do
`B2B-net-S-A` `main` nie miał ochrony. Przegląd z 10.09 wykazał, że produkcja
jest zdrowa, ale część zmian psuła dane albo mogła je popsuć:
- automat zamówień z maila nadpisał PFRON 507–509;
- pełny przegląd bazy rósł bez retencji;
- must-have nikogo nie ukrywał;
- części CV nie dało się zatwierdzić.

Plan P0/P1 zatwierdził Artur. Jego decyzje są w tabeli poniżej.

## Co weszło

| PR | Zakres |
|---|---|
| ruleset `main-baseline` | PR wymagany (0 aprobat). Wymagane: gitleaks, lint + migracje, typy frontu, pytest, build frontu. `strict`, historia liniowa, bez obejść. PR #1480 zamknięty. |
| #1489 — P0 | **Zamówienia z maila:** żywy wyłącznik automatu; powrót po przerwie = nowe zamówienie; wypowiedzenie liczone per okres zamówienia; jedyny imiennik wymaga człowieka. **Pełny przegląd bazy:** retencja 7 dni z ochroną ostatniego przeglądu, stan `failed`, RODO przy usunięciu kandydata, must-have ukrywa tylko znane braki technologii. **Generator CV:** generuje każdy; zatwierdzanie CV sprzed #1444; zgodność zadań w kolejce. **Pozostałe:** digest Sentry bez tytułów w logu, obejście `section_access` dla TCM, migracja 0305. |
| #1491 — P1 | **Wyszukiwanie:** cosinus liczony w Qdrancie; pula bez rerankera dla kanonicznego fitu; `GET/POST /api/admin/index-cleanup`; kolumna wyniku i pierścień „Dopasowanie” na kanonicznym ficie; telemetria; eval `--scorer`. **Zamówienia:** korekta PFRON 507–509 (0306) z krokiem harmonogramu przychodu; dedup alertów wygasania z datą; aktor „Przelicz plan”; backstop alertu. **CV / Champion / infra:** normalizacja tylko zmienionych pól, zasada stawki, retencja wejść CV, 3 ponowienia, Traffit doradczy, `/api/health/live`, `lock_timeout` przy starcie. **Przegląd kodu spoza Codexa:** 10 poprawek. |
| #1492 | A/B matchingu jedną krótką komendą. Coolify trzyma komendę zadania w VARCHAR(255), więc poprzednie komendy dostawały HTTP 500. |
| #1490 (inna sesja) | Generator CV przypina DOCX Championa przed podglądem AI. |

Decyzje Artura (10.09):

| Temat | Decyzja |
|---|---|
| Przedłużenie zamówienia po przerwie | nowy wiersz + naprawa 507–509 z historii w aplikacji |
| Must-have | bramkuje tylko technologia; brak danych przepuszcza |
| Ranking #1428 | zostaje, A/B w tym tygodniu (wynik niżej) |
| TCM | cała organizacja; naprawione tylko obejście sekcji |
| Generowanie CV | wszyscy mogą |
| Retencja wyników wyszukiwania | 7 dni + ostatni wynik |
| Limity AI | bez zmian |

## Migracje

- `0305_candidate_search_retention_indexes` — dwa indeksy `CONCURRENTLY`, lustro w `_INDEX_STATEMENTS`.
- `0306_pfron_renewal_split_repair` — jednorazowa naprawa danych (znacznik + advisory lock + `lock_timeout`), lustro w `entrypoint.sh`. Tuż po niej krok `pfron_revenue_resync`, który synchronizuje harmonogram przychodu umów kodem zwykłego zapisu zamówienia.

## Nowe i zmienione powierzchnie API

- `GET /api/health/live` — sonda Dockera (bez bazy). `/api/health` zostaje sondą smoke testu.
- `GET/POST /api/admin/index-cleanup` (admin) — plan z odciskiem, potem zatwierdzenie dokładnie tego planu.
- `/api/search/candidates/scores`:
  - kanoniczny fit, najwyżej 20 ID;
  - dostęp jak do pełnego przeglądu C2;
  - limit 60/min per użytkownik.
- `GET` werdyktu HM zwraca `{can_record, items}`.
- Dodanie do pipeline'u (`proposals/bulk`) przyjmuje opcjonalne `run_id` i `source`.

## Konfiguracja

Żadna nowa zmienna nie jest wymagana. Nowe przełączniki mają bezpieczne wartości domyślne:
- `ORDER_MAIL_AUTOAPPLY_ENABLED` — teraz żywy wyłącznik automatu;
- `CANDIDATE_SEARCH_RETENTION_ENABLED` / `_DAYS` (7) / `_PROTECT_MAX_DAYS` (90) / `_CHECK_INTERVAL_SECONDS`;
- `CV_JOB_INPUT_RETENTION_ENABLED` / `_DAYS` (7);
- `CV_B2B_MAX_RETRIES` — domyślnie 3.

## Weryfikacja na produkcji (11.09)

- **Wersja:** `/api/health` → `5e5b0480`, healthy; `/api/health/deep` 72/72; `/api/health/live` 200.
- **Korekta PFRON** (paragon `0306_pfron_renewal_split_repair`, odczyt przez `coolify-ops migration-receipts`): `split: 3, skipped: 0`.

  | Oryginał (przywrócony) | Okres oryginału | Nowe zamówienie | Okres |
  |---|---|---|---|
  | 507 | 01.07–31.08 | 626 | 01.09–30.11 |
  | 508 | 01.07–31.08 | 627 | 01.09–30.11 |
  | 509 | 01.08–31.08 | 628 | 01.09–30.11 |

  Oryginały mają przywrócony poprzedni PDF i notatki. Dokumenty z maila 18–20 wskazują nowe wiersze.
- **Harmonogram przychodu** (paragon `0306_pfron_revenue_resync`): `done`, umowy 397, 398 i 399 mają po 2 kroki (przywrócony i nowy okres).
- **A/B scorera:** [matching-ab-scorer-2026-09-11.md](matching-ab-scorer-2026-09-11.md).
  - Zbiór A: kanoniczny lepiej ustawia górę listy (P@5 +0.016, MRR +0.023).
  - Holdout B: remis z lekkim spadkiem recall (R@20n −0.006).
  - Ranking kanoniczny zostaje, pod obserwacją `weekly_eval`.

## Jak to sprawdzano

Każda z pięciu gałęzi P1 przeszła niezależny przegląd adwersarialny. Była też osobna runda przeglądu samych poprawek. Znalezione blokady i usterki poprawiono w trzech rundach, a testy każdej poprawki sprawdzono mutacją: padają po przywróceniu starego kodu. Dwie blokady:
- stawka Championa w złej jednostce trafiała do budżetu rekrutacji;
- później budżet starych profili znikał przy uzgadnianiu, imporcie i kopiowaniu rekrutacji.

Lokalnie, jak w CI:
- pełny zestaw backendu: 11 162 testy;
- vitest powiązanych plików: 1192 testy;
- `tsc`, lint, `next build`.

W CI wszystkie wymagane checki #1491 i #1492 są zielone.

## Znane ograniczenia i dalsze kroki

**Po stronie Artura**

- Sekret `SENTRY_AUTH_TOKEN` — od P0 bezpieczny (digest nie drukuje tytułów).
- Sekret `CLAUDE_CODE_OAUTH_TOKEN` — przegląd PR przez Claude pada po 1 s. To objaw nieważnego tokena albo limitu, a check jest doradczy.
- Połączenie Claude in Chrome, potrzebne do trzech rzeczy:
  - sprzątania indeksu (`/api/admin/index-cleanup`: ~1,9 tys. osieroconych punktów i oferty bez wektora);
  - kontroli w panelu admina;
  - obejrzenia nowych oznaczeń kolumny wyniku.
- Delivery Lead PFRON przegląda zamówienia 507–509 i 626–628.
- Decyzja: kto akceptuje weryfikacje kandydatów. Przyciski widzą DL i HoR, ale endpointy są tylko dla admina (stary błąd).

**Dług techniczny odnotowany świadomie**

- Tabele telemetrii (`match_impressions`, `match_outcomes`) nie mają retencji ani czyszczenia RODO.
- Wkład stawki w wynik (warstwa salary) da się odtworzyć jako „total minus widoczne warstwy”. To stan sprzed P1, na kilku endpointach.
- `_worked_at_client_predicate` liczy szkice i unieważnione kontrakty.
- Edycja samej rekrutacji (tytuł, klient, rubryki) nie odświeża gotowości.
- NIT-y korekty 0306: ścisłość ponownego podpinania PDF, konsumpcje z 2026-09 zapisane przed incydentem, restart okna powtórek alertu DL.
- Traffit pokazuje `degraded` do najbliższego nocnego przebiegu. Nowa zasada (błędy wierszy są doradcze) odmrozi `__daily__`.
- Limit pozycji stacku Championa 120 → 500 znaków działa w jedną stronę. Przy wycofaniu deployu profil z dłuższą pozycją zwróci 500.

**Odłożone decyzją z 10.09**

- widoczność repo i rotacja sekretów z historii;
- webhook Slacka;
- kopia bazy poza serwerem;
- limity AI;
- zasady pracy Codexa;
- ograniczenie sekretów Coolify i kontrola forków w `deploy.yml`.
