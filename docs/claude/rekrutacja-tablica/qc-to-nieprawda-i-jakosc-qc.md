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
  (notatka), nie pominięcie.
- **Nie da się pominąć** `cv_present` i `client_rules` (stawka, kontakt,
  zgoda RODO) — 422, przycisku nie ma.
- **Uwaga blokująca = obejście.** Pomija ją ten, kto może przesunąć kartę
  mimo uwag (`api/cv_qc._can_override`: prawo wysyłki CV, a w trybie
  doradczym każdy członek rekrutacji); inaczej 403. Delivery Lead dostaje
  dzwonek „Pominięta uwaga blokująca QC” (bez autora), przebieg zapisuje
  `dismissed_blocking`, `pair_statuses` zwraca `overridden`
  z `dismissed_blocking` > 0, a przegląd DL pokazuje ryzyko `qc_dismissed`.
  Zwrot karty przywraca pominięcia blokad osób bez prawa wysyłki — jak
  obejście doradcze (`api/pipeline._spend_advisory_qc_override_on_return`).
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
