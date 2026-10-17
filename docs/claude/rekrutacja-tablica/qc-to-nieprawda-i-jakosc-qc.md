# „To nieprawda” i „Jakość QC” (13.10.2026, D5–D6)
<!-- indeks: pominięcie uwagi per para, blokada = obejście, trafność < 70% → informacja -->

Zespół mówił, że QC daje dużo nieprawdziwych uwag i nie da się ich odznaczyć.
Makiety i decyzje: https://claude.ai/artifact/BZZRshjBDC4CMEGGP6m4Wr. PR 3 z 4
(po „QC mówi prawdę” — klucz pozycji `item["key"]` jest stamtąd).

## Pominięcie („To nieprawda”, D5)

- **Tabela `cv_finding_dismissals`** (migracja 0439 + lustro w `entrypoint.sh`,
  `test_cv_finding_dismissals.py`). Pominięcie dotyczy pary (kandydat,
  rekrutacja), nie pliku: nowe CV tej osoby w tej rekrutacji nie wskrzesza
  uwagi. Aktywne pominięcie pary i klucza jest jedno (indeks częściowy);
  przywrócone zostaje w tabeli jako historia (`restored_reason`:
  `user` | `card_returned`).
- **Klucz liczy serwer** z pól pozycji (`cv_qc._assign_keys`: sprawdzenie |
  wymaganie lub termin | rola z oryginału albo `cv`), nigdy z `role_index`.
  Etykietę bierze ze świeżego przebiegu — nigdy od klienta. Uwagi generatora
  i kontroli AI w edytorze: skrót znormalizowanego tekstu (+ status kontroli
  AI), `cv_finding_dismissals.text_key`.
- **Jedno miejsce nakładania: `cv_qc.evaluate`.** Okno QC, zapisany przebieg
  (plakietka na Tablicy), bramka ruchu, obejście i propozycje AI widzą to
  samo. Pominięte pozycje są w `check["dismissed_items"]` (z `dismissal`:
  powód, kto, kiedy), status sprawdzenia liczy się z pozostałych.
- **Powody** (`REASONS`): „Jest w CV — QC tego nie znalazło”, „Jest
  w źródłach pod inną nazwą”, „Dotyczy innej roli albo sekcji” (te trzy to
  „QC się myli” i liczą się do trafności), „Nie dotyczy tej rekrutacji”,
  „Inny powód” (wymaga opisu). „Pod inną nazwą” przy treści spoza oryginału
  wymaga fragmentu, który serwer znajdzie w oryginale, notatkach albo
  odpowiedziach. „Mówił(a) w rozmowie” to dalej „Potwierdzone z kandydatem”
  (notatka), nie pominięcie. Poza formularzem są dwa powody jednego
  kliknięcia, przypisane do części uwag (`REASON_CHECKS`, zbiory): `kept_order`
  („Zostaw tę kolejność”, tylko `role_order`, 16.10.2026) i `kept` („OK” /
  „Zostaw” przy uwadze generatora albo kontroli AI w edytorze, tylko źródła
  `generator` i `review`, 17.10.2026). Żaden nie liczy się do trafności.
- **Nie da się pominąć** `cv_present` i `client_rules` (stawka, kontakt,
  zgoda RODO) — 422, przycisku nie ma.
- **Obejście „Kandydat potwierdził to w rozmowie” zapisuje fakt** (D3,
  decyzja Artura 17.10.2026). `record_override` z `reason_code
  confirmed_in_call` dodaje „Potwierdzone z kandydatem: X — opis” (ta sama
  notatka co `confirm_with_candidate`, `_add_confirmation`, Activity
  `cv_qc_confirmed` z `via: override`) przy każdej rzeczy z
  `confirmable_terms`: termin `no_unsupported` i krytyczna `ask_candidate`
  bez roli (brak zdania w roli to poprawka CV, nie fakt). Najwyżej
  `CONFIRMATIONS_MAX`. Przebieg obejścia zapisuje stan sprzed potwierdzeń,
  następny — już z nimi. Okno obejścia przy tym powodzie mówi, że powstaną
  notatki (czytają je QC i generator). Pomiar 17.10: 24 z 47 obejść niosło
  `no_unsupported`, a rekruter wiedział z rozmowy to, czego nie było
  w notatkach.
- **Uwaga blokująca = obejście.** Pomija ją ten, kto może przesunąć kartę
  mimo uwag (`api/cv_qc._can_override`: prawo wysyłki CV, a w trybie
  doradczym każdy członek rekrutacji); inaczej 403. Delivery Lead dostaje
  dzwonek „Pominięta uwaga blokująca QC” (bez autora), przebieg zapisuje
  `dismissed_blocking`, `pair_statuses` zwraca `overridden`
  z `dismissed_blocking` > 0, a przegląd DL pokazuje ryzyko `qc_dismissed`.
  Zwrot karty przywraca pominięcia blokad osób bez prawa wysyłki — jak
  obejście doradcze (`api/pipeline._spend_advisory_qc_override_on_return`).
- **Zwrot karty a zapisany przebieg (14.10.2026).** Audyt 13.10 pokazał, że po
  zwrocie karty plakietka, przegląd DL i kolejka DL mówiły „przepuszczone”, aż
  ktoś otworzył okno QC: zwrot przywraca pominięcia, ale QC nie liczy się od
  nowa. Teraz `cv_qc.pair_statuses` porównuje `dismissed_blocking` przebiegu
  z trwającymi pominięciami blokad pary — gdy część przywrócono, para jest
  `failed`, a `blocking_failed` to liczba przywróconych. Kto traci pominięcie,
  rozstrzyga prawo wysyłki z bazy („Osoby i role”, `resolve_effective_access`
  w `restore_on_card_return`), nie domyślny zestaw roli — do 13.10 rekruter
  z nadanym prawem je tracił, a DL z odebranym zachowywał. Porównanie
  przeglądu DL (D10, `dl_review.build_queue`) nazywa pominięcia `qc_dismissed`
  jak okno osoby. Testy: `test_fix48_ws11_card_return.py`,
  `test_fix48_ws11_qc_override_rule.py`, `test_fix48_ws11_qc_pair_status.py`,
  `test_fix48_ws11_dl_review_queue.py`, `test_fix48_ws11_qc_quality.py`
  (progi automatu).
- **Pominięcie roli krytycznej nie ukrywa braku w całym CV.** Pozycja roli
  krytycznej nieobecnej w CV ma `absent_in_cv`; po jej pominięciu wraca
  pozycja „Brak w CV” dla całego CV.
- **„Pogrub wszystkie”** (okno i edytor) nie pogrubia wymagania, którego
  uwagę „nie jest pogrubione” ktoś pominął.
- **Trasy:** `POST /api/pipeline/stages/{id}/qc/dismiss`,
  `POST …/qc/dismissals/{dismissal_id}/restore` (rekruter+, członek
  rekrutacji, bez integracji); edytor: `POST /api/candidates/stages/{id}/cv/
  branded/issues/dismiss` i `…/issues/dismissals/{id}/restore`, a
  `GET …/issues` ma `dismissed`. Wpisy `Activity`: `cv_qc_dismissed`,
  `cv_qc_dismissal_restored`.

- **„QC się myli” w oknie obejścia** (D4, decyzja Artura 17.10.2026). Pomiar
  17.10: 4 „To nieprawda” na 47 obejść — trafność 100% w „Jakość QC”
  znaczyła brak danych. `QcOverrideDialog` dostaje `pendingItems`
  (`taskPendingItem`: tytuł, klucze pozycji, `labelable` = blokada spoza
  `cv_present`/`client_rules`) i przy każdej blokadzie ma „Prawda”
  (domyślnie) / „QC się myli”. Żądanie obejścia niesie `wrong_keys`;
  `record_override` → `override_labels` bierze tylko klucze niezaliczonych
  blokad z bieżącego przebiegu, zapisuje pominięcie z powodem
  `qc_wrong_override` („QC się myli — zaznaczone przy przepuszczeniu”, liczy
  się do trafności), Activity `cv_qc_dismissed` z `via: override`,
  a w przebiegu obejścia `override_labels` = `{wrong, kept}`. Bez osobnego
  dzwonka — obejście doradcze już dzwoni. Powodu nie ma w formularzu „To
  nieprawda”.

## „Jakość QC” (D6)

- **Trafność** sprawdzenia = 1 − (pominięte jako „QC się myli” / pokazane)
  z 30 dni (`services/qc_quality.report`). Pokazane = różne pozycje (para ×
  klucz) we wszystkich przebiegach okna, łącznie z pominiętymi. Liczą się
  tylko trwające pominięcia.
- **Automat** (zadanie dzienne `tasks/qc_quality_daily.py`): uwaga
  z trafnością < 70% przy ≥ 30 pokazanych staje się informacją (`muted` —
  widać ją, nie liczy się do uwag w `summarize`); wraca, gdy trafność
  wzrośnie. **Blokady nigdy nie przechodzą same** — poniżej 90% jedno
  powiadomienie do adminów na serię (typ `automation_failing`, tylko admini).
- **Ręcznie** (`PATCH /api/settings/ai/qc-quality/{key}`, admin): `active`,
  `info`, `off` albo automat (`null`) — tylko dla uwag; blokad z panelu nie da
  się wyciszyć (422). Stan ręczny wygrywa z automatem. Stan leży
  w `app_settings['qc_check_states']`.
- **Panel** `GET /api/settings/ai/qc-quality` (admin) — sprawdzenia
  z trafnością, powodami i stanem oraz ostatnie pominięcia; strona
  `/settings/ai/qc-quality`.
- **Przed podbiciem `QC_VERSION`:** `backend/scripts/qc_eval_dismissals.py`
  (tylko odczyt, same liczby) starym i nowym kodem — nowa wersja nie może
  zgłaszać więcej uwag, które zespół oznaczył jako nieprawdziwe; oraz
  `qc_truth_audit.py` (liczba uwag na CV).
