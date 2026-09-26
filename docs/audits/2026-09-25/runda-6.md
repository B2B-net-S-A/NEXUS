# Audyt NEXUS 26.09.2026 — runda 6

> **Baza:** `e2585b51c` (main po #1853) · **Status:** naprawione w PR „fix: naprawa pozycji z rundy 6 audytu (26.09.2026)” — statusy w tabeli niżej.
> Decyzje Artura (26.09.2026): pulpit i kreator metryk DL zawężone do portfela; kwoty i off-limits klientów spoza portfela DL ukryte na ekranach rekrutacji; PFRON — jawne „netto” przy stawce wygrywa (bez ÷1,23).
> Poprzednie rundy: [README](README.md). Reguły po naprawach: `CLAUDE.md`, sekcja „Audyt 25.09.2026 — reguły po naprawie”.

## Zakres i metoda

19 agentów, wyłącznie odczyt, znaleziska sprawdzone przez koordynatora w kodzie (oznaczenie **potwierdzone**) albo przyjęte z plik:linia i scenariuszem agenta. Zakres ustalony z raportów rund 1–5 tak, żeby nie powtarzać przejrzanych obszarów. Potem 15 agentów naprawczych, każdy we własnym worktree i w swoim obszarze, scalenie i przegląd kodu.

| Agent | Obszar | Dlaczego teraz |
|---|---|---|
| A | #1843 — DL widzi tylko swoich klientów, trasa po trasie | wszedł po bazie r5, nikt nie audytował |
| B | #1846 (kolejność „Dopasowanie”, pole klasyfikacji), #1848, korpus 0385 | jw. |
| C | weryfikacja poprawek r5 (#1849), #1850, #1851 | stały punkt każdej rundy |
| D | fazy Traffita: pliki, CV, tekst CV, enrich, cv_fields, workflows, sources, talents, mappers, rejection_backfill | r5: „niesprawdzone” |
| E | dokumenty pochodne B2B (0362), rejestr z Excela (0363), scalanie kandydatów, przepięcie kontraktu, anulowanie MD | logika nigdy nieaudytowana |
| F | przekrój po wzorcach z README (nieaktywne konto, NULL w SQL, daty, niedomknięte stany, połykane wyjątki) | lekcja „co się powtarza” |
| G | nowe trasy od r4, frontend przekrojowo, eksporty | — |
| H | usunięcie kandydata (art. 17) od końca do końca | nigdy przekrojowo |
| I | rdzeń kontraktów: harmonogramy, aneksy, jednostki, sync, cron, marża | poza ścieżkami zakończenia/cofnięcia z r1–r5 |
| J | deterministyczne polityki odczytu PDF zamówień per klient | regexy i arytmetyka kwot |
| K | rozliczenia MD i kosztowe, offboarding | spójność z poprawkami r1–r4 |
| L | integracja M365 użytkowników (poczta, kalendarz, załączniki) | poza callbackiem OAuth z r3 |
| M | cykl rozmów u klienta, sloty, prepy Teams | poza poprawkami r2–r4 |
| N | automaty rekrutacji (nocny przegląd, auto-match, auto-CV, Moi ludzie) | — |
| O | poprawność LICZB w Insights/KPI/kreatorze/analityce | r3 sprawdzała konkursy i uprawnienia |
| P | wydajność jedynego procesu uvicorna | nigdy |
| Q | wycieki przez logi, Sentry, workflowy publicznego repo | nigdy przekrojowo |
| R | zakładanie i edycja rekrutacji, Champion, nazwy, HM | poza notatkami Championa z r3 |
| S | moduł Finanse — logika (Zmiany, Braki, PDF) | r4 tylko uprawnienia |

## Wynik

| Waga | Liczba |
|---|---|
| krytyczne | 1 (M365-1) |
| wysokie | 13 |
| średnio-wysokie | 2 |
| średnie | ~50 |
| niskie | ~35 |

Trend błędów w kodzie poprawionym w poprzedniej rundzie: 61 → 19 → 2 → 10 → 1 → **2** (R6-C1, R6-C2 — obie w poprawce R5-6). Pozostałe pozycje pochodzą z obszarów dotąd nieaudytowanych albo z kodu, który wszedł po bazie r5 (#1843, #1846).

## Najważniejsze

- **M365-1 (krytyczne, potwierdzone):** „stopka Outlooka” doklejana do każdego maila z NEXUSA to wszystko od OSTATNIEGO znacznika podpisu do końca treści ostatniego wysłanego maila — razem z cytatem innej rozmowy (adres, stawka innego kandydata). `services/m365/signature_cache.py:126-148`.
- **T6-1 (wysokie, potwierdzone, regresja #1730):** od 22.09 powody i komentarze odrzuceń z Traffita przestały się wypełniać — backfill czyta `activity_date` jako UTC, a mapper etapów od #1730 jako Europe/Warsaw; złączenie po dokładnym znaczniku nie trafia nigdy. `services/traffit/rejection_backfill.py:57,108`.
- **RODO-01 (wysokie, potwierdzone):** usunięty kandydat z Traffita wraca z nocnym syncem (brak nagrobka, jak `purged_clients` u klientów). **RODO-02:** wygenerowane CV przeżywają usunięcie kandydata i są czytelne/pobieralne.
- **A6-1 (wysokie, potwierdzone):** retencja przeglądów automatycznych (2 dni) kasuje jedyną pamięć „ten request już przejrzany” → stare rekrutacje wracają do nocnej kolejki co 2 noce i zjadają limit nowym.
- **DOC-1 (wysokie, potwierdzone):** rozwiązanie/wypowiedzenie umowy „bez projektu” nadpisuje datę i powód zakończenia starego projektu na kontrakcie (zejście przesuwa się w Insights, powód zamienia na rezygnację).
- **L1 (wysokie):** „zapytania” DL w Insights liczone od `jobs.created_at` = data importu z Traffita (3859/4229 z maja 2026) — hit ratio DL kilka % zamiast kilkudziesięciu.
- **W1/W2/W5 (wysokie):** URL webhooka Slacka i iCal w logach przez logger `httpx` na INFO; `coolify-ops client-lookup` drukuje nazwiska konsultantów do publicznego logu Actions; raport Playwright z produkcji (trace z tokenem) jako artefakt publicznego repo (uśpione do założenia konta E2E).
- **PERF-1 (wysokie):** ranking puli praktykantów (do 60 tys. profili) liczony na pętli zdarzeń przy każdej zmianie pola w ustawieniach reguł — sekundy blokady całego API.

## Znaleziska i status

Legenda statusu: ✅ naprawione w PR rundy 6 · ⛔ odrzucone po przeczytaniu kodu · 🟡 zostawione (powód).

| ID | Waga | Agent | Znalezisko | Status |
|---|---|---|---|---|
| M365-1 | krytyczne | L | Podpis Outlooka dokleja cytat innej rozmowy do każdego maila z NEXUSA (`signature_cache.py`) | ✅ ucięcie na znaczniku cytatu, pierwszy znacznik podpisu, odrzucenie podpisu z cudzym adresem |
| T6-1 | wysokie | D | Powody odrzuceń z Traffita puste od 22.09 (strefa w `rejection_backfill.py`) | ✅ złączenie po czasie warszawskim i starym UTC |
| RODO-01 | wysokie | H | Usunięty kandydat wraca z nocnym syncem Traffita | ✅ nagrobek `purged_candidates` (HMAC external_id, migracja 0388), importer pomija |
| RODO-02 | wysokie | H | Wygenerowane CV przeżywają usunięcie kandydata | ✅ kasowane z plikiem zgody; odpięte dokumenty niewydawane |
| A6-1 | wysokie | N | Retencja kasuje pamięć nocnego przeglądu → rekrutacje wracają co 2 noce | ✅ start i odcisk we wpisie „Praca w tle”; `failed` nie zamyka zdarzenia |
| DOC-1 | wysokie | E | Rozwiązanie umowy „bez projektu” nadpisuje zakończenie starego projektu | ✅ zakończony kontrakt nietknięty, zamyka się tylko wiersz rejestru |
| L1 | wysokie | O | Zapytania DL liczone od daty importu z Traffita | ✅ `COALESCE(opened_at, created_at)` w rankingu, trendzie, portfelu, HM, raporcie DL |
| P1 | wysokie | J | Nordea: model widział tylko wyciąg regexu, sprawdzenie krzyżowe nic nie łapało | ✅ surowy fragment tabeli dla modelu + niezależna kontrola kompletności |
| W1 | wysokie | Q | URL webhooka Slacka i iCal w logach (`httpx` INFO) | ✅ `httpx`/`httpcore` na WARNING, redakcja Slack/iCal |
| W2 | wysokie | Q | `coolify-ops client-lookup` drukuje nazwiska do publicznego logu | ✅ same ID, bez surowego wyjścia przy porażce |
| W5 | wysokie (uśpione) | Q | Raport Playwright z produkcji (trace z tokenem) jako artefakt | ✅ bez uploadu z joba produkcyjnego, trace tylko lokalnie |
| M365-2 | wysokie | L | Kolejka CV z maili staje, płatny odczyt co 15 s | ✅ rollback + próba oznaczona osobno; e-mail zajęty nie jest wpisywany |
| M365-3 | wysokie | L | Dopasowanie po nazwisku wczytuje całą tabelę kandydatów | ✅ zapytanie zawężone w SQL, kontakt < 90 dni, niejednoznaczne = brak |
| PERF-1 | wysokie | P | Ranking puli praktykantów na pętli zdarzeń | ✅ liczenie w wątku, single-flight, podgląd z pamięcią 120 s |
| MD-1 | średnio-wysokie | K | Decyzja „oddaj pulę” + późny import = fałszywe przekroczenie | ✅ korekta dla `remove` jak dla transferu |
| K1 | średnio-wysokie | I | Aneks stawki sprzed startu umowy nie działa od startu | ✅ bez kroku bazowego późniejszego niż aneks |
| C1 | średnie | C | Formuła Nordei: JSON `null` zamiast SQL NULL, pętla nie dosypuje | ✅ `JSONB(none_as_null=True)` + predykat `jsonb_typeof` |
| C2 | niskie | C | Odczyt PDF Nordei pod blokadami | ✅ odczyt przed blokadami, raz na dokument |
| T6-2 | średnie | D | Plik z Traffita odbiera „główne CV” plikowi z NEXUSA | ✅ zdejmowane tylko kopie z Traffita |
| T6-3 | średnie | D | `cv_fields`: limit 200 gubi resztę okna na zawsze | ✅ kursor okien w `cursor_payload` |
| T6-4 | średnie | D | Nieudane pliki blokują kolejkę tekstu CV; faza niewidoczna w statusie | ✅ odroczenia 1/3/7/14/30 dni, klucze w `_summarize` |
| T6-5 | średnie | D | Generator CV wybiera parser po rozszerzeniu (PDF jako .docx) | ✅ rozpoznanie formatu z bajtów |
| T6-6..8 | niskie | D | Błędy bez klucza wiersza; zaległe CV bez wskaźnika w delcie | ✅ |
| M1 | średnie | B | Górne pole zamienia alias na frazę kanoniczną (kafka → Apache Kafka) | ✅ alias zostaje wariantem wiersza |
| M2 | średnie | B | Kolejność „Dopasowanie” czeka na Voyage 60 s | ✅ limit 3 s, potem „najnowsi” |
| M3, M4 | niskie | B | Wersja składania ze stałej Pythona; eksport przy `sort=match` | ✅ znacznik wersji w funkcji; eksport w kolejności ekranu |
| X1 | średnie | F | „Requesty do decyzji” do nieaktywnego DL | ✅ eskalacja do HoR jak `_delivery_lead_targets` |
| X2 | średnie | F | „Utknął na etapie” i telefon po rozmowie do nieaktywnego / bez zastępcy | ✅ `effective_owner_id` + zapas |
| X3/IC-2 | średnie | F/M | Sprawa „brak prepu” i podpowiedź organizatora — nieaktywna osoba | ✅ ta sama reguła co podpowiedź organizatora |
| X4 | średnie | F | Follow-up w Teams: edycja 409, odwołanie tylko lokalne | ✅ ścieżka app-only jak prep |
| IC-1 | średnie | M | Przełożona rozmowa zostawia starą → fałszywe telefony i alarmy prepów | ✅ nieodbyte rozmowy założone przez NEXUS odwoływane |
| IC-3 | średnio-niskie | M | Potwierdzenie terminu bez ponownego sprawdzenia rekrutera | ✅ |
| IC-4/RODO-04 | średnie | M/H | Usunięcie kandydata nie odwołuje prepów w Teams, kalendarz z nazwiskiem | ✅ odwołanie po commicie, anonimizacja wydarzeń |
| IC-5, IC-6 | niskie | M | Ponowienie prepu z innym terminem; zmiana kandydata na wydarzeniu prepu | ✅ |
| DOC-2 | średnie | E | Efekty dokumentu idą do kontraktu z chwili generowania | ✅ bieżący kontrakt rodzica, `void` = 409 |
| REA-1 | średnie | E | Przepięcie kontraktu nie przenosi dokumentów pochodnych | ✅ także przy „Powiąż z kontraktem” |
| DOC-3, XLS-1, LOCK-1 | niskie | E | Wypowiedzenie Excel bez wersji; import nadpisuje zmiany z dokumentów; kolejność blokad | ✅ (`/render` zapisuje `template_version`) |
| MRG-1/RODO-05 | średnie | E/H | Scalanie gubi powiązania rozmów Jarvisa | ✅ `jarvis_conversation_entities` w `_POLYMORPHIC`; linki powiadomień innych typów |
| DL-01 | średnie | A | Kafle i kreator metryk DL liczą całą firmę | ✅ decyzja: portfel DL |
| DL-02 | średnie | A | „Edytuj kartę klienta” → 403 dla DL spoza portfela | ✅ edytor w Ustawieniach |
| DL-03, K4 | niskie/średnie | A/I | Off-limits i marża klientów spoza portfela DL | ✅ decyzja: ukryte poza portfelem |
| DL-04, DL-05 | niskie | A | Scalony klient przed 307; pickery Kontraktów i angielski 403 | ✅ |
| G1, G2 | niskie | G | CSV Insights bez ochrony formuł; awaria = „Brak wyników” | ✅ |
| A6-2 | średnie | N | Dzwonek „N nowych propozycji” bez nowych | ✅ tylko faktycznie nowe |
| A6-3 | średnie | N | Automaty dla requestów „Zakończony”/„Klient milczy” | ✅ `IN_WORK_STATES` |
| A6-4, A6-5 | niskie | N | Przegląd bez wektora = sukces; publikacja dla zamkniętej | ✅ |
| P2, P3, P4 | średnie | J | Polkomtel sklejanie kolumny MD; Cardif pierwsza stawka dla wszystkich; PFRON „od DATA” jako koniec | ✅ (+ bliźniaki KIR, mLeasing, VeloBank) |
| P5 | średnie | J | PFRON jawne „netto” dzielone przez 1,23 | ✅ decyzja: netto wygrywa |
| MD-2..6 | średnie/niskie | K | Sprawa offboardingu nie wraca; numer kosztowy nie wiąże; wspólna pula; reapply; łańcuch zamian | ✅ |
| IC/M365-4..10 | średnie/niskie | L | Heurystyki domen, odpięcie nietrwałe, „Odpowiedz” na własny mail, drugie CV w mailu, rematch prywatnych, załączniki, webhook w trakcie syncu | ✅ |
| J1..J5 | średnie/niskie | R | PATCH waliduje niezmienione pola; kopia kasuje lata/dealbreakery; briefing w kopii; null = 500; ranking bez zmian | ✅ |
| K2, K3, K5..K7 | średnie/niskie | I | Przedłużenie z minioną datą; marża /h w historii; cron bez savepointu; próg jednodniowy; `/generate` jednostka | ✅ |
| L2..L7 | średnie/niskie | O | Firma pełny okres; fill rate; średnia inną atrybucją; opis celu DL; lejek; alert DL | ✅ |
| FIN6-1..6 | średnie/niskie | S | Anulowane zastępstwo = „zastąpiony”; brak nie wraca; linia MD bez daty; Wejścia; duplikat; ZIP w pamięci | ✅ |
| W3, W4, W6 | średnie | Q | Klucze CV w publicznym logu; `%40` w access logu; nazwiska w logach generatora | ✅ + strażnik AST logów |
| RODO-03, 06, 07 | średnie/niskie | H | Powiadomienia z nazwiskiem; dziennik integracji; CV z maila zakłada usuniętego | ✅ |
| PERF-2..4 | średnie/niskie | P | Podobne rekrutacje na pętli; zapis zużycia AI; parsowanie XLSX rejestru | ✅ |

## Sprawdzone i czyste (skrót — co NIE wymaga powtórki w rundzie 7)

- **Poprawki r5:** R5-1 (każda ścieżka przesuwająca datę końca odwołuje zastępstwo), R5-2 (stała `REQUEST_BODY_METHODS`, kolejność middleware, handlery czytające surowe ciało), R5-3, R5-4 (wszystkie odpowiedzi `text/html` do nowej karty mają CSP), R5-5, R5-7 (każde `.weekday()` w BUSINESS_TZ albo z komentarzem), R5-8; #1850 (bez wyścigu deployów, `concurrency` seryjne); #1851 (idempotentna, marker).
- **#1843:** resolvery i hybrydy ról, bramka routera na 8–9 routerach i trasy bez `{client_id}`, Kontrakty/Zamówienia/poczta zamówień/portal DL/konflikty/kontakty/⌘K, `purpose="org"` tam, gdzie decyzja tak mówi.
- **#1846/#1848:** pamięć kolejności (klucz z osobą i solą etapów, LRU 32), wektor rekrutacji tylko przez `_authorized_job`, stronicowanie i `total`, skaner alertów wymusza `newest`, `/keywords/classify` (bramka, limit), lustro myślnika SQL↔Python, `note_unwrap_json`, `_list_page_ids_first`.
- **Traffit:** `import_workflows` + parkowanie, `import_candidates_cv` (nagrobek tylko na 404/410 listy), `import_candidate_files`, `enrich_missing_names`/`cv_backfill`, `cv_field_backfill`, ścieżka `glued`, `import_candidate_sources`, `import_talents`, `mappers.py`, kwarantanna, `ADVISORY_PHASES`, `full_sweep_pending`.
- **Wzorce przekrojowo:** 40 miejsc `~`/`not_` (SQL trójwartościowy czysty), `date_trunc` z `AT TIME ZONE`, brak `CURRENT_DATE`, `except Exception` w ścieżkach pieniędzy z logiem; stany 0365/0375/0376/0380/0382.
- **Frontend (pliki zmienione od r4) i eksporty:** brak `data?.detail`, `confirm`/`alert`, `dangerouslySetInnerHTML` bez sanitizacji; wszystkie eksporty backendu przez `safe_cell`/`safe_row`, nazwy w ZIP bez path traversal.
- **RODO:** FK kandydata bez `ON DELETE` — brak (skrypt po migracjach i entrypoincie); outbox indeksu, klucze `stage-cv/`, kopie PDF grupy.
- **Kontrakty:** resolver harmonogramu = lustro SQL, przeliczenia jednostek (6 miejsc, bez podwójnego ×8/÷8), `sync_contract_from_orders`, `run_daily_order_cost_sync`, `fold_money`, FX, listy/eksporty z harmonogramami.
- **Parsery PDF:** `net_rate_from_gross` (HALF_UP), `_bp_hourly_from_md` (CEILING), BNP, Credit Agricole, PKO BP, BIK, VeloBank, KIR, Erste, dopasowanie osób (`_name_match_score`, `resolve_contract`), `order_mail_gate.evaluate`, `drop_md_absence_reasons`.
- **MD:** `apply_md_consumption` (W2–W4), `_revert_earlier_transfer`, idempotencja powtórnego importu, `recompute_remaining`, `split_md_usage`, `cost_orders.settle_group`, wspólna pula, parser XLSX, brak `float()`.
- **M365:** rezerwacja wysyłki przed Graphem, odświeżanie tokenów, kursory delty, strefy czasowe, kalendarz `transactionId`, webhook.
- **Kalendarz/prepy:** `compute_steps`/`compute_todos`, `load_overview` (stała liczba zapytań), sloty pod `FOR UPDATE`, debrief, `prep_review` (awaria = `level NULL`).
- **Automaty:** okno nocne, ustępowanie ludziom, tryb `propose`, `_BLOCKING_WARNINGS`, idempotencja auto-CV, serie awarii, archiwum 25.09 poza automatami.
- **Insights:** `/team/*`, `previous_matching_window`, `PRECISION_COHORT_CTE`, `VERIFIER_ANCHORED_CTE`, widok z wykluczeniami, kokpit Rady i rok do roku, analityka kontraktów.
- **Logi:** Sentry backend i front (`scrub_event`, replay), `RedactingJsonFormatter`, gałęzie błędów Slacka, workflowy z redakcją.
- **Finanse:** `order_change_audit` (savepointy), daty w Warszawie, `order_change_checks`, `finance_order_pdfs` (nazwy), `finance_trend`.
- **Rekrutacje:** `job_edit_level`, HM, `job_delivery_lead_fill`, `job_working_title`, `request_stage_expr`, handoff, lustra readiness/intake.
- **Wydajność:** synchroniczne I/O w trasach odciągnięte do wątków (eksporty, ZIP, DOCX, OCR, Qdrant, MSAL/Graph, SMTP, `call_claude`), pamięć procesu ograniczona, `LIMIT` na gorących listach.

## Co się powtarza — dopisane w tej rundzie

1. **Kolumna JSONB i `None`.** `JSONB` bez `none_as_null=True` zapisuje JSON `null`, którego `IS NULL` nie widzi (R6-C1). Każda kolumna JSONB czytana przez `is_(None)` musi mieć `none_as_null=True` albo predykat z `jsonb_typeof(...) = 'null'`.
2. **Retencja kasuje pamięć automatu.** Stan „już zrobione” trzymany wyłącznie w wierszach, które kasuje retencja (A6-1). Przy każdej retencji: kto czyta te wiersze jako pamięć.
3. **Zmiana strefy czasowej w jednym miejscu rozjeżdża złączenia po dokładnym czasie** (T6-1). Po zmianie parsera czasu grep wszystkich SQL-i łączących po tym znaczniku.
4. **Walidacja po kluczach żądania, nie po zmianie wartości** (J1, J5): formularze wysyłają komplet pól, więc „pole w `model_fields_set`” ≠ „pole zmienione”.
5. **Heurystyka wybierająca „ostatnie” albo „pierwsze z brzegu” dopasowanie** (M365-1, Cardif P3, Polkomtel P2): przy niejednoznaczności jawna odmowa albo „do sprawdzenia”.
6. **Publiczne repo = publiczne logi Actions i artefakty** (W2, W3, W5): każdy `echo` wyniku z produkcji i każdy `upload-artifact` to publikacja.
7. **CPU w `async def`** (PERF-1, PERF-2): obliczenie po tysiącach wierszy w Pythonie → `asyncio.to_thread` + single-flight.

## Rekomendacje na rundę 7

- **Weryfikacja poprawek r6** (stały punkt), ze szczególnym naciskiem na: podpis M365 (realne HTML-e odpowiedzi OWA/mobile), nagrobek kandydata we WSZYSTKICH fazach Traffita, pamięć nocnego przeglądu po retencji, redakcję logów `httpx`, zawężenie kreatora metryk DL.
- **Obszary nadal nieprzejrzane:** `contract_merge.py` (`apply_contract_merge_plan`), `stage_side_effects.py` i `merge.py` Traffita, parser i dopasowanie importu z Excela (`b2b_register_import/parser.py`, `matching.py`), replay Polkomtela (`reprocess_polkomtel_import`), `md_consumption_view`, `onedrive.py`, `aad_groups.py`, `actionable_messages.py`, `mail_circuit.py`, `chat_email_fallback`, `teams_notifications.py`, `durable_jobs.execute_job` i recovery generatora CV, `queue_retention`, `talent_pool_auto_add`, `pipeline_auto_move`, `auto_assign_owners`, lista `/jobs` (filtry i liczniki), `DELETE /api/jobs`, `dashboard_v2_sources`, `insights_competence_matrix`, `alior.py`/`mleasing.py`/`known_clients.py`, prompt `ORDER_EXTRACTION`, CPU hydratacji ORM listy kandydatów i `/api/kpis/me/today`.
- **Przekroje, które się opłaciły — powtórzyć na nowym kodzie:** wzorce z README (agent F), logi/workflowy publicznego repo (agent Q), wydajność pętli zdarzeń (agent P), RODO od końca do końca (agent H).
- **Czego nie da się sprawdzić z kodu (wymaga produkcji):** częstość układów PDF z P1–P4, liczba rekrutacji z nieaktywnym DL (J1), rozmiary PDF-ów w ZIP Finansów (FIN6-6), stan `remaining_references` korekty E-Zdrowie, czy Alloy wysyła logi do Grafany.

## Do wiadomości (poza progiem blokady, bez zmian)

- Refresh token bez rotacji, stary WS `?token=`, `/public/sign/*` przy `SIGNING_ENABLED=false`, `/api/health/deep` i webhook M365 bez limitu (r5).
- `printHtml` w `B2BContractGeneratorV2.tsx` bez CSP — szablon edytuje tylko admin, zmienne escapowane (`SandboxedEnvironment`).
- Natywne `confirm`/`alert` w 7 starszych plikach niezmienianych od r4 (`NotificationsTab.tsx`, `contract-templates`, `rate-benchmarks`, `api-integration`, `scoring`, `ExtendOrderDialog.tsx`, `RateHistoryWidget.tsx`).
- Test AST eksportów sprawdza import `safe_cell`, nie każdą komórkę — ryzyko na przyszłość, dziś czysto.
- M365: odświeżenie tokenu commituje sesję wołającego; `M365ReauthRequired` po szkicu daje `uncertain`; 4xx Grapha w compose zostawia szkic w Szkicach.
- Kopie denormalizowane `client_id` klienta 37721 (`interview_questions`, `calendar_events`, `client_interview_slot_requests`, `cv_generated_documents`, `candidate_search_runs`) poza korektą E-Zdrowie — paragon `remaining_references` pokaże skalę.
- `client_deletion`: DL z imiennym `can_delete_clients` usunie klienta spoza portfela (uprawnienie globalne z definicji).
