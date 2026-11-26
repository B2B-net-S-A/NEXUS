# Rekrutacja „Wstrzymana” (on hold): stan pracy, pas na Tablicy i pytania do DL (26.11.2026)
<!-- indeks: `work_state='on_hold'`, `jobs.hold_reason/hold_review_on/hold_ended_at`, `api/job_hold.py`, `GET /api/hold-checks`, `job_hold_changed`, `job_hold_check`, „Przesuń mimo to”, `JobHoldBanner`, `HoldChecksPanel` -->

Zgłoszenie rekruterki z 26.11.2026: zaproponowała kandydatowi projekt i zrobiła
weryfikację, a dopiero potem DL powiedział jej, że klient wstrzymał rekrutację.
W NEXUSIE rekrutacja dalej była „Szukamy”. DL zdjął wcześniej P1 i zespół
przeszedł do „Poprzednich rekruterów”, ale status się nie zmienił. Produkcja
26.11: wszystkie 141 otwartych rekrutacji w „Szukamy”. Od 01.09 „Klient milczy”
ustawiono 3 razy, a zamknięcie z powodem „wstrzymana” 6 razy. W 15 rekrutacjach
„Szukamy” DL nie ruszył nic od 14 dni, a rekruterzy w tym tygodniu pracowali
(119 ruchów kart). Makiety: https://claude.ai/artifact/H6jsE9rofb3VDj24apGe92.

## Decyzje Artura (26.11.2026)

- **Osobny stan pracy `on_hold`** („Wstrzymana”) obok „Klient milczy”, który
  zostaje bez zmian. Rekrutacja jest otwarta: hit ratio, karty, przypisania
  i „Poprzedni rekruter” się nie zmieniają.
- **Ostrzeżenie, nie blokada.** Ruch karty naprzód w wstrzymanej rekrutacji
  pyta „Przesuń mimo to” / „Nie przesuwaj”, jak przy innych ostrzeżeniach ruchu.
  Bywają uzgodnione wyjątki.
- **Oba etapy naraz:** to, co widzi rekruter (pigułka, pas, ostrzeżenie, lista),
  i to, co pilnuje DL (zgłoszenie rekrutera, panel „Czy te rekrutacje nadal
  trwają?”, termin sprawdzenia).

## Reguła

- **Kto ustawia:** te same osoby co stan pracy dziś (`WorkStateEditor`: DL, HoR,
  admin). Wstrzymanie wymaga powodu. „Sprawdzę z klientem” to data
  w kalendarzu firmy (domyślnie +14 dni, najdalej 120). Batch na
  `/jobs/review-states` nie ustawia `on_hold`, bo nie ma tam powodu, ale może
  z niego wyjść. Wyjście batchem do „Szukamy” albo „Do przejrzenia” wysyła
  ten sam dzwonek „Rekrutacja wznowiona” co „Wznów rekrutację”
  (`job_hold.resumes_work`). Przejście do „Klient milczy” takiego dzwonka nie wysyła.
- **Gdzie widać:** pigułka w nagłówku w paski, pas nad Tablicą (kto, od kiedy,
  powód, „nie proponuj kandydatom tego projektu”, termin), pigułka „Wstrzymana
  od DD.MM” i filtr „Wstrzymane” na liście, zakładka na stronie przeglądu stanów.
  Status requestu i stan na liście mają `on_hold` po „Umowie”, przed championem.
  W „Wymaga uwagi” wstrzymane są na końcu.
- **Kogo powiadamia:** dzwonek i mail obowiązkowy `job_hold_changed` przy
  wstrzymaniu i wznowieniu. Dostają go osoby prowadzące kandydatów w toku
  (kolumny inne niż „Zamknięci” i „Zatrudniony”), aktywne przypisania
  i współpracownicy, bez osoby, która zmienia stan. DL może odznaczyć
  powiadomienie, a zmiana samego powodu lub terminu nie wysyła nic.
- **Automaty:** `on_hold` nie jest w `IN_WORK_STATES`, więc wypada z przydziału,
  porcji dnia, nocnego przeglądu bazy, propozycji i digestów, tak jak „Klient
  milczy”. Licznik „bez ruchu” 14/21/28 pomija wstrzymane i liczy od wznowienia
  (`hold_ended_at`). Wstrzymana nigdy nie zamyka się sama jako przegrana.
- **Termin i długie wstrzymanie** (pętla `job_idle`): w dniu „Sprawdzę z
  klientem” DL dostaje dzwonek `job_hold_check` „Wznawiamy?”. Po 30 dniach
  wstrzymania dostaje propozycję zamknięcia z powodem „wstrzymana” (poza hit
  ratio). Każdy dzwonek idzie raz, znaczniki są w `Activity`.

## DL zapomina: zgłoszenie rekrutera i panel na pulpicie

- **Rekruter zgłasza:** dymek pigułki „Szukamy” ma pole „Słyszysz, że klient
  wstrzymał?” i przycisk „Zgłoś DL-owi” (`POST /api/jobs/{id}/hold/report`,
  `Activity hold_reported`, dzwonek `job_hold_check` do DL, bez DL do HoR). Na
  wstrzymanej ten sam przycisk to „Zapytaj DL”. Jedno otwarte zgłoszenie na osobę
  i rekrutację (409 `already_reported`). `job_hold_check` (zgłoszenie,
  odpowiedź DL, terminy) jest w kategorii imiennej, której nie da się wyciszyć,
  bo na stagingu rekruterka z wyciszonymi „Przypomnieniami” nie dostała
  odpowiedzi „DL potwierdził: szukamy”.
- **Panel „Czy te rekrutacje nadal trwają?”** na pulpicie DL i w Daily
  (`GET /api/hold-checks`, do 10 pozycji). Pokazuje otwarte rekrutacje
  w „Szukamy” albo „Do przejrzenia” z sygnałem nowszym niż ostatnia odpowiedź DL.
  Sygnały, od najsilniejszego: zgłoszenie rekrutera; notatka z 30 dni ze słowem
  „on hold” albo „wstrzyma” (treści nie zwracamy); zejście z P1, po którym
  rekruterzy dalej ruszają karty; brak ruchu DL od 14 dni przy ruchach
  rekruterów w 7 dni.
- **Odpowiedź jednym kliknięciem:** „Szukamy” (`POST …/hold-check`, wpis
  `hold_check_answered`, zgłaszający dostaje „DL potwierdził: szukamy”),
  „Wstrzymana…” (okno wstrzymania), „Otwórz”. Sygnał „brak ruchu DL” wraca
  najwcześniej po 14 dniach od odpowiedzi.
- „Bez ruchu od 14 dni” (`JobIdleBanner`) ma obok „Jeszcze trwa” przycisk
  „Wstrzymana…”.

## Gdzie to siedzi

- Stan: `services/request_work_state.py` (`WORK_STATES`, etykiety), lustro
  `frontend/src/lib/request-work-state.ts` na wspólnym
  `lib/__fixtures__/request-work-state-cases.json`. Status i stan listy:
  `services/job_similarity.request_status_expr` / `request_stage_expr`.
- Trasy: `api/job_hold.py` (`GET/PUT/DELETE /api/jobs/{id}/hold`,
  `POST …/hold/report`, `GET /api/hold-checks`, `POST …/hold-check`).
- Migracja 0795 (`hold_reason`, `hold_review_on`, `hold_ended_at`, dwa typy
  powiadomień) z lustrem w `entrypoint.sh`.
- Front: `JobHoldDialog`, `JobHoldBanner`, `HoldChecksPanel`, pigułka
  w `JobChampionsStatus`, pytanie w `usePipelineMoveCore`, harness
  `/preview/job-hold`.
