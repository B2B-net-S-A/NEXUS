# Audyt NEXUS 26.09.2026 — runda 7

> **Baza:** `4e92bbc82` (main `d76afa514` + gałąź rundy 6) · **Status:** naprawione w PR „fix: naprawa pozycji z rundy 7 audytu (26.09.2026)”; dwie regresje rundy 6 naprawione jeszcze w PR rundy 6 (#1860) przed jego scaleniem.
> Decyzje Artura (26.09.2026): zakres „Moje” na liście rekrutacji = tylko moje OTWARTE; „Interview” w KPI/Insights = wyłącznie rozmowy u klienta; druk i PDF CV bez zrzutu zgody RODO blokowane jak pobranie; arkusz „Bez działalności” oznacza aneks do zrobienia także na umowie z NEXUSA; publicznego logu z paragonem 0304 nie kasujemy (repo zostanie przestawione na prywatne), klucz z logu „Coolify set env” rotuje Artur, nazwiska w CLAUDE.md/docs zostają.
> Poprzednie rundy: [README](README.md). Reguły po naprawach: `CLAUDE.md`, sekcja „Audyt 25.09.2026 — reguły po naprawie”, podsekcja „Runda 7”.

## Zakres i metoda

20 agentów audytu (tylko odczyt); koordynator potwierdził najważniejsze znaleziska w kodzie (np. ReDoS zmierzony: URL 8 KB = 2 s blokady procesu). Potem 15 agentów naprawczych w osobnych worktree i rozłącznych obszarach, scalenie, 4 przeglądy kodu po scaleniu i dwa pełne biegi CI (pierwszy złapał 8 testów, które lokalnie przechodziły tylko dlatego, że szły z `--noconftest`).

| Agent | Obszar |
|---|---|
| V1–V5 | weryfikacja poprawek rundy 6 (M365, Traffit i nagrobek, automaty/Insights/DL/IC-1, pieniądze, logi/front/wydajność) |
| N1 | scalanie duplikatów kontraktów (`contract_merge.py`) |
| N2 | skutki uboczne importu etapów Traffita, przepięcia, replay Polkomtela |
| N3 | import rejestru umów B2B z Excela (0363) |
| N4 | widoki MD, polityki PDF mLeasing/Alior, prompt odczytu |
| N5 | M365 poboczne (nagrania, raporty KPI mailem, czat, monitor, AAD) |
| N6 | trwałe zadania CV, dzierżawy, auto-CV |
| N7 | pula talentów, automatyczny ruch karty, auto-DL |
| N8 | lista `/jobs`, usuwanie rekrutacji |
| N9 | źródła pulpitu v2, macierz kompetencji, KPI |
| N10 | wydajność jedynego procesu uvicorna |
| X1 | przekrój po wzorcach z README |
| X2 | logi i workflowy publicznego repo |
| X3 | #1852–#1856 (korpus składany, słowa kluczowe) |
| X4 | generator CV v3 i bramka zgody |
| X5 | klienci: scalanie i usuwanie |

## Wynik

| Waga | Liczba |
|---|---|
| krytyczne | 3 (V2-1 i V1-2 — regresje r6, naprawione w #1860; V5-1 ReDoS) + 1 już opublikowane (X2-1, log Actions) |
| wysokie | 14 |
| średnie | ~45 |
| niskie | ~30 |

Trend błędów w kodzie poprawionym w poprzedniej rundzie: 61 → 19 → 2 → 10 → 1 → 2 → **4** (V2-1, V1-2, V5-1 i A6). Reszta z obszarów dotąd nieaudytowanych.

## Najważniejsze

- **V2-1 (krytyczne, regresja r6, potwierdzone):** biała lista `_summarize` przepuszczała licznik `error` z `BackfillStats` (0), a bramka znacznika `__daily__` patrzyła na obecność klucza — dzienny znacznik Traffita nie przesuwał się nigdy. Naprawione w #1860 przed scaleniem.
- **V1-2 (krytyczne, regresja r6, potwierdzone):** „Odpowiedz” w wątku brało ostatnią przychodzącą wiadomość niezależnie od nadawcy — odpowiedź dla kandydata szła do HM-a klienta. Naprawione w #1860 (tylko mail od kandydata).
- **V5-1 (krytyczne, potwierdzone):** ReDoS w centralnej redakcji logów (`_ICAL_URL_RE` z lookaheadem, `_EMAIL_RE`, `_LABELED_SECRET_RE`, redakcja 2× na rekord) — jedno anonimowe żądanie z długim URL-em blokowało cały proces API na sekundy (access log idzie synchronicznie).
- **X2-1 (krytyczne, już opublikowane):** paragon migracji 0304 z nazwiskami ok. 557 konsultantów i stawkami trafił do publicznego logu workflowu `migration-receipts` (run 35245948500). Kod naprawiony (paragon = liczby i ID, szczegóły pod `repair_details_0304_…`, skrypt drukuje przez białą listę typów); logu nie kasujemy — repo idzie na prywatne.
- **X5-1 (wysokie):** rejestr NIP poczty zamówień nie pomijał usuniętych klientów — mail mógł zapisać zamówienie (i wskrzesić kontrakt) u usuniętego klienta.
- **N4-1 / N4-2 (wysokie):** mLeasing przypisywał wszystkim osobom pierwszą cenę i okres jako pewne; „Importy MD” pokazywały wiersze (kwoty faktur) innego klienta po dowolnej liczbie w „Uwagach”.
- **N1-1 / N1-2 (wysokie):** scalanie kontraktów przenosiło zakończenie przegranego na żywy kontrakt (cron go zamykał) i przykrywało kroki stawek z zamówień krokami rozstrzygnięcia.
- **X4-1 / X4-2 (wysokie):** usunięcie wygenerowanego CV zdejmowało bramkę zgody z kopii etapu; przegląd DL i kolejka Cpro pobierały surowy DOCX generatora zamiast CV po QC.
- **N9-1, N10-1..3 (wysokie):** kafel „Aktywność” liczył tylko aktywne konta trzech ról; `/kpis/me/today`, `/competitions/my-position`, `/api/board-tasks` liczyły pełne CTE / N+1 na każde otwarcie pulpitu.

## Znaleziska i status

Legenda: ✅ naprawione · ⛔ fałszywe po przeczytaniu kodu · 🟡 zostawione (powód) · ◐ częściowo.

| ID | Waga | Znalezisko | Status |
|---|---|---|---|
| V2-1 | krytyczne | Znacznik `__daily__` Traffita nie przesuwa się (r6) | ✅ w #1860 |
| V1-2 | krytyczne | „Odpowiedz” do HM-a zamiast kandydata (r6) | ✅ w #1860 |
| V5-1 | krytyczne | ReDoS w redakcji logów | ✅ wzorce bez cofania, limit 32 KB, redakcja idempotentna, test liniowości |
| X2-1 | krytyczne | Paragon 0304 z nazwiskami w publicznym logu | ✅ kod; 🟡 istniejący log zostaje (repo → prywatne) |
| X2-2 | wysokie | „Coolify set env” drukuje wartość w nagłówku `env:` | ✅ wartość z pliku zdarzenia, maska przed użyciem, sekretne klucze tylko z `value_from_secret`; 🟡 rotacja klucza z runu 34143764096 — Artur |
| X2-3..9 | średnie/niskie | Nazwy plików zamówień w logach, błędy restore w backup-drill, UPN nadawcy, artefakt order-mail-cleanup, NIP w client-lookup, reporter e2e, `str(exc)` | ✅ |
| X2-10 | niskie | Nazwiska obok stawek w CLAUDE.md/docs/testach | 🟡 decyzja Artura: zostają |
| V5-2 | średnie | Ścieżki z nazwiskami w logach `storage_service` i bliźniakach; strażnik nie widział f-stringów | ✅ `safe_storage_key`, strażnik rozszerzony (30 miejsc) |
| V5-3 | niskie | `search=` / `nip=` w access logu | ✅ |
| X5-1 | wysokie | Rejestr NIP poczty z usuniętym klientem | ✅ rejestr, rozpoznanie i writer odrzucają `deleted_at` |
| X5-2 | średnio-wysokie | `merge-into` klientów nic nie blokuje | ✅ 409 z listą blokad |
| X5-3 | średnie | Usunięty klient zostawia opublikowaną pustą rekrutację (zombie w automatach) | ✅ zamknięcie przy usunięciu (bez `closed_at`) |
| X5-4 | średnie | Zapisy przyjmują usuniętego/scalonego klienta | ✅ `assert_client_assignable` (422) w rekrutacjach, kontraktach, kontaktach, odczycie maila, stawkach, konfliktach, generatorze CV |
| N4-1 | wysokie | mLeasing: pierwsza cena/okres dla wszystkich | ✅ tylko gdy wspólne; inaczej niepewne |
| N4-2 | wysokie | „Importy MD” z cudzymi wierszami | ✅ numer wiąże regułą importu + osoba z linią u klienta |
| V4-3 | średnie | PFRON „(netto)”, „zł/h netto”, „+23% VAT” dzielone ÷1,23 | ✅ netto rozpoznane; nieczytelne → weryfikacja |
| V4-4 | średnie | Instrukcja zamówień sprzeczna z kodem | ✅ |
| V4-5 | niskie | Reguła „≥ 7 cyfr” wiąże BNP przez Polkomtel | ✅ klient kosztowy wiąże tylko znanym numerem |
| N2-1 | średnio-wysokie | Replay Polkomtela gubi wiersze po nazwisku | ✅ |
| N2-2..5 | średnie/niskie | Przepięcia zatrudnionych, replay bez haka, `finished` dostaje przepięcia, skutki dla `rows` | ✅ |
| N1-1..6 | wysokie/średnie | Scalanie kontraktów (zakończenie przegranego, kroki stawek, migawki, `order_gaps`, para „powrót po przerwie”, `client_order_*`) | ✅ |
| V4-1 | wysokie | DOC-1 tylko dla „Zakończony” — „Kończący się” nadal nadpisywany | ✅ |
| V4-2 | średnie | Aneks stawki sprzed startu przy istniejącym harmonogramie | ✅ |
| V4-6 | średnie | Cofnięcie przywraca umowę B2B mimo podpisanego rozwiązania | ✅ |
| V4-7 | niskie | `confirm-fully-signed` — odwrotna kolejność blokad | ✅ |
| X1-1 | średnio-wysokie | `termination_restore` JSON `null` vs `IS NULL` | ✅ `none_as_null` + `jsonb_typeof` |
| N8-1 | wysokie | „Moje” obejmuje archiwum zamkniętych | ✅ decyzja: tylko otwarte |
| N8-2..5 | średnie/niskie | „Kto pracuje” bez prowadzącego; DL usuwa zamkniętą (Liga DL); DELETE rekrutacji z Traffita wraca; DELETE ze spotkaniem = 500 | ✅ 409 `job_is_closed`/`job_from_traffit`/`job_has_calendar_events`, wpis w Historii zdarzeń |
| X1-5 | niskie | HM zdejmowany po kluczu `client_id` | ✅ po zmianie wartości |
| N7-1..5 | średnie | Auto-DL bez roli DL; auto-DL zostaje; auto-ruch omija ostrzeżenie i efekty `/move`; backfill pul z rollbackiem sesji | ✅ |
| X1-3, X1-4 | niskie | Matcher strict `limit(1)`; dzwonek terminu do nieaktywnego | ✅ |
| N3-1..10 | średnie/niskie | Import z Excela: flaga aneksu (decyzja), klucze bez numeru, legenda vs nazwisko, numer „1517/2026”, arkusz, pusty klient, aneks bez daty, zgadywany rekruter, data, blokady | ✅ |
| X4-1..5 | wysokie/średnie | Bramka zgody po usunięciu CV; surowy DOCX w DL/Cpro; druk (decyzja: blokowany); bramka na złym wierszu; notatki follow-up w prompcie | ✅ |
| N6-1, N6-2 | średnie | Auto-CV po recovery nie podpina; wyjątek przy odnowieniu dzierżawy traci opłaconą generację | ✅ hak `after_job_finished`, `lease_renewal` |
| N9-1..6 | wysokie/średnie | Kafel Aktywność; „Interview” (decyzja: `client_interview`); cache; liczniki ≠ kolumny Tablicy; `finished` jako otwarte; placementy DL tylko od TAC | ✅ (N9-3 ◐ — szczegóły po kliknięciu bez cache) |
| N10-1..6 | wysokie/średnie | `/kpis/me/today`, `/my-position`, `/board-tasks` N+1, `sort=match` w pętli, wycinki ze wszystkich notatek, rok-do-roku | ✅ |
| V3-1 | średnie | Popyt praktykanta i kontekst Luny po `created_at` (data importu) | ✅ `opened_at or created_at` |
| V3-2 | średnie | = N10-3 | ✅ |
| V3-3 | niskie | IC-1: fałszywe „odwołany” przy porażce Outlooka | ✅ `superseded_outlook`, toast mówi prawdę |
| X3-1..4 | średnie/niskie (za flagą OFF) | Zakres cv/title/skills, wznawianie po rollbacku, downgrade 0386, podświetlenia | ✅ (X3-3: część o 0387 ⛔ — naprawione w r6; 0386 ✅) |
| V2-2..5 | średnie/niskie | Nagrobek tylko po id; wyścig; Talent Radar; okno cv_fields | ✅ nagrobek też po HMAC maila (bez migracji), strażnik w SQL; żywa osoba z tym mailem wygrywa |
| V1-1, V1-3..7 | średnie/niskie | Podpis „--”, PATCH gubi cytat, stopka mobilna, `cid:`, odwołanie Teams bez ponowień, prywatne spotkanie z kandydatem | ✅ |
| N5-1..8 | średnie/niskie | Nagrania po czasie; raporty KPI przy otwartym bezpieczniku; czat 2 maile; monitor `uncertain`; martwy publiczny POST; typy Teams; AAD `nextLink`; 502/504 jako odmowa | ✅ (N5-7 ◐ — reaktywacja konta przy logowaniu AAD zostaje, funkcja uśpiona) |
| A6 (r6) | niskie | Niezmieniony odcisk wisi 14 dni w kolejce przeglądu | ✅ |

## Przegląd po scaleniu

4 przeglądy (pieniądze, rekrutacja, logi/CV/M365, wyszukiwanie + styki gałęzi) — zero blokujących. Poprawione od razu: nowsza zwykła wiadomość czatu wstrzymywała mail admina o wzmiance; nagrobek maila blokował adopcję do osoby, która wróciła; `IN :sources` w surowym SQL (reguła PREPARE). Pierwszy pełny bieg CI złapał 8 testów, które lokalnie przechodziły tylko z `--noconftest` (conftest odpina ID Polkomtela, wyłącza cache rankingów; atrapy wierszy bez `opened_at`; rekrutacja bez klienta w teście).

Pułapka scalania: main ma rundę 6 jako squash, gałąź rundy 7 — jako historię; scalenie maina dało konflikty w ~50 plikach. Rozwiązanie bez ryzyka: potwierdzić, że `git diff <końcówka r6> origin/main` to dokładnie pliki PR-a, który wszedł po niej (#1862), i wtedy wziąć wersję gałęzi dla wszystkich konfliktów.

## Zostawione / do decyzji

- Zamkniętej rekrutacji nie usuwa nikt, także admin (najpierw ponowne otwarcie) — jeśli admin ma móc, zawęzić warunek w `delete_job`.
- Historyczne liczby „Rozmowy” w Mój miesiąc/Zespół spadną: import z Traffita przed 03.09 zapisywał rozmowy u klienta jako `interview`.
- `recruitment_trend._STAGE_FIELDS` i `funnel_coverage.recommendation_to_interview_pct` nadal liczą `interview` (bez konsumenta w UI).
- `_assert_client` w zamówieniach nie odrzuca scalonego klienta (profil scalonego i tak przekierowuje).
- Kolumny `JSON().with_variant(JSONB())` bez `none_as_null` w innych modelach — brak odczytu `is_(None)` w obszarze rundy; kandydat na osobny przegląd.
- N5-7: logowanie przez AAD reaktywuje konto wyłączone ręcznie (funkcja uśpiona).
- Bliźniaki N2-5 w `api/pipeline.py:1595,3339` (`on_candidate_stage_change` w savepoincie) i N7-1 w `board_tasks.py:292`, `competitions._resolve_dl_id`, `insights_dl_scope` (DL bez sprawdzenia roli).
- `delete_job`: odmowa `job_referenced` po `IntegrityError` nie trafia do Historii zdarzeń (`rollback` wygasza `current_user`); odpowiedź 409 poprawna.
- Wycinki trafień pokazują 20 najnowszych notatek na osobę; przy wyłączonej fladze składania wycinek „lodz” → „Łódź” z notatki nie powstaje (tylko wyświetlanie, wynik listy bez zmian).
- Nagrobek identyfikatora Traffita nadal blokuje adopcję do żywej osoby z tym samym mailem (test r6) — nagrobek maila już nie.

## Sprawdzone i czyste

- Poprawki rundy 6: A6, L1–L7, J1–J5, DL-01..05, IC-1/IC-3, X1–X4, W1–W6, PERF-1..4, G1/G2 (raporty V3, V5).
- `VERIFIER_ANCHORED_CTE` i płacące konkursy nietknięte przez rundę 7.
