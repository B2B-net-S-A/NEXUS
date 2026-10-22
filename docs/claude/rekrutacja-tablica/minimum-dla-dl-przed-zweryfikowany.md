# Minimum dla Delivery Leada przed „Zweryfikowany” (21.10.2026)
<!-- indeks: lokalizacja, tryb, dostępność, „Dlaczego ten kandydat”; okno na Tablicy -->

Zgłoszenie Delivery Leadów z 21.10.2026: rekomendacje przychodziły bez lokalizacji
i trybu pracy, DL dopytywał rekrutera na Teams. Rekruterzy tłumaczyli, że to przepięcia
i nic nie trzeba uzupełniać. Pomiar na produkcji (tylko odczyt, wejścia na
„Zweryfikowany” 12–21.10, 251 par): 16 bez lokalizacji albo trybu pracy (plus 4 z wpisem
„-”, „.” albo jedną literą), z czego 6 miało tę wartość w innej rekrutacji tej osoby;
**0 z 18 formalnych przepięć** miało taki brak; „Dlaczego ten kandydat” puste w 123 z 251;
u Nordei 43 ze 104 bez „Dlaczego”, 73 ze 104 bez motywacji. W 9 dni DL-e wysłali 3 prośby
o poprawki w NEXUSIE. Makiety: https://claude.ai/artifact/3FCPzpNSprtjv3mBz9ZjRC.

Decyzje Artura 21.10.2026:

- **D1 — minimum blokuje przekazanie.** Wejście na „Zweryfikowany” z Nowych/Screeningu
  wymaga, oprócz arkusza (albo „Dlaczego” w rekrutacji bez pytań) i stawki: lokalizacji,
  trybu pracy, dostępności i „Dlaczego ten kandydat”
  (`recommendation_card_rules.VERIFIED_MINIMUM_FIELDS`). Jedna reguła
  (`move_requirements.minimum_missing`) dla bramki 409 `VERIFIED_REQUIREMENTS_MISSING`
  (nowe klucze w `missing` i osobna lista `card_fields`), okna „Przesuń dalej” (pozycje
  blokujące z akcją `open_card`), karty Tablicy (`minimum_missing`) i formularza
  (`state.card.required`, lustro `minimumMissingForForward`). Dostępność liczy się też
  z daty w profilu, wartość z notatki — także przy pustym polu formularza. W rekrutacji bez
  pytań niewpisane „Dlaczego” stoi raz, jako `why_candidate`; gdy rozmowę zapisały odpowiedzi
  z notatki albo stary arkusz (`why_candidate` spełnione), minimum dalej wymaga „Dlaczego”
  (`_why_candidate_reported`, przegląd 21.10.2026). „Pomiń brakujące” dotyczy tylko pytań
  i minimum nie pomija. Wyłącznik: `VERIFIED_MINIMUM_FIELDS_ENABLED` (testy: autouse
  w `conftest.py` wyłącza, `minimum_on` w `test_verified_gate.py` włącza).
- **Zaślepka nie jest wartością.** Pole bez litery i cyfry („-”, „.”, „?”) liczy się jako
  puste — w minimum i w „Screening: brakuje N” (`has_value`, front `cardValueCounts`).
  Wyjątek: red flags, gdzie „-” znaczy „brak uwag”.
- **D2 — pola o osobie przechodzą same.** `GET /api/screening-form` oddaje
  `card.carried`: najświeższą wartość lokalizacji, trybu pracy, narodowości i angielskiego
  (do 183 dni) oraz dostępności (do 30 dni) z kart tej osoby w innych rekrutacjach
  w zakresie odczytu patrzącego (`recommendation_cards.carried_fields`). Pole bez daty
  odpada. Formularz w Nowych/Screeningu wpisuje je w puste pola jak stawkę na start:
  zmiana formularza zapisywana z „Zapisz”, pod polem „z rozmowy 20.10.2026 · <rekrutacja> —
  sprawdź i zapisz”, bez „Niezapisanych zmian” i bez wpisu do pamięci rozmowy, a pole ruszone
  przez rekrutera nie wraca. „Dlaczego ten kandydat” dotyczy rekrutacji — nie przechodzi.
- **Tablica nie otwiera całego panelu dla samego minimum.** Strzałka albo przeciągnięcie ze
  „Screeningu” na „Zweryfikowany”, gdy arkusz jest, a brakuje tylko pól minimum
  (`minimumOnlyGap`), otwiera `MinimumFieldsDialog`: same brakujące pola (z wartościami
  z innej rekrutacji), „Zapisz i przesuń” = `PUT /api/screening-form` z samymi polami karty
  i ruch. To samo okno po odmowie 409 z samymi `card_fields` i z akcji „Uzupełnij
  w screeningu” w „Przesuń dalej” (wtedy „Zapisz” i powrót do okna). Strzałka jest szara
  z podpowiedzią „Brak: lokalizacja, tryb pracy”.
- **D3 — pola per klient** (`motivation`, `worked_at_client`, `english`, `nationality`,
  `red_flags`, `CLIENT_EXTRA_FIELDS`) dokłada Delivery Lead w karcie klienta; do minimum
  wchodzą przez `PairFacts.client_required_fields` z podpisem „wymaga <klient>”.

Świadomie poza zakresem: formularz wspólny („Screening dla”) liczy minimum per para
w „Zanim przekażesz dalej, uzupełnij”, ale nie wpisuje pól z rekrutacji spoza zaznaczenia
(pola wspólne biorą wartość z innej zaznaczonej pary jak dotąd). Dok osoby nazywa braki
minimum „przypomnieniem” tak samo jak brak arkusza (`SERVER_ENFORCED_REQUIREMENT_KEYS`).
Pary, które już stoją w „Zweryfikowanym” albo dalej, się nie cofają.

Od 22.10.2026 minimum (jak cała bramka „Zweryfikowany”) nie zatrzymuje samego
Delivery Leada — `dl-przesuwa-bez-blokad.md`.
