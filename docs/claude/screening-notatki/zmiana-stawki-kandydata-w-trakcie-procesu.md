# Zmiana stawki kandydata w trakcie procesu (0418, 04.10.2026)

Sandra zapisała w debriefie „chce jednak 125 zł/h” w polu warunku i nikt tego
nie zobaczył; korekta stawki nadpisywała wiersz etapu bez śladu i bez dzwonka.
Decyzje Artura D1–D8 04.10.2026 (makiety https://claude.ai/artifact/2bJy59VoHb67EcX5wj1tz9).
Kod: `services/candidate_rate_change.py` (reguła), `api/candidate_rate_changes.py`,
`services/rate_change_tasks.py` („Czeka na Ciebie”), front `lib/rate-change.ts`,
`components/v2/rate-change/`.

- **Każda zmiana stawki pary idzie przez `change_rate`** (panel osoby „Zmień”,
  debrief, zakładka Rekrutacje profilu, okno stawki profilu ze źródłem
  `profile`, ręczne pole stawki na karcie rekomendacji od „Zweryfikowany” ze
  źródłem `card`). Nowe miejsce zapisu `expected_rate_*` pary = `change_rate`,
  nie `update_latest_expected_rate` wprost. Źródło `move` (ponowny ruch na
  „Zweryfikowany” z inną stawką) nie jest jeszcze podpięte.
- **Jeden wiersz `candidate_rate_changes` = jedna sprawa** z cyklem
  `noted | requested → negotiating → agreed → closed`, `superseded` przy
  kolejnej zmianie. Jedna OTWARTA sprawa na parę (częściowy UNIQUE).
  Przed „Zweryfikowany” wpis bez powiadomień (D1); od niego dzwonek DL
  (`_dl_reviewers`) i każdego Head of Recruitment (D2); wzrost od „CV wysłane”
  = zadanie DL `candidate_rate_change_task` (kategoria obowiązkowa) z mailem
  (rodzaj `rate_change`, opt-in w Ustawieniach) (D3); spadek i pomyłka = info (D5).
- **Otwarta sprawa czekająca na DL porównuje się ze stawką, z którą CV poszło
  do klienta** (`previous_*` sprawy), nie z kwotą zgłoszoną przed chwilą —
  korekta 180 → 170 przy CV za 150 nadal czeka na DL (przegląd #2028).
- **Negocjację zleca DL rekrutacji albo HoR, o stawce do klienta decyduje
  WYŁĄCZNIE DL rekrutacji albo admin** (D6, `can_manage` / `can_decide`).
  W trakcie negocjacji obowiązuje stawka zgłoszona (D7); ustalona niższa trafia
  na wiersz etapu, zejście do stawki sprzed zmiany zamyka sprawę samo
  (`decision=auto`). „Podnoszę” zapisuje stawkę do klienta z audytem
  `client_rate_changed`; oś czasu kandydata nie niesie stawki do klienta.
- **Blokady w kolejności `change_rate`: kandydat → wiersz etapu → sprawa**
  (`lock_change`). Akcje działają tylko na sprawie otwartej (`requested`,
  `negotiating`), nigdy na starym `noted`.
- **Sprawa po końcu procesu** (odrzucenie, rezygnacja, zatrudnienie, zamknięta
  rekrutacja — `change_still_active`) znika z „Czeka na Ciebie”, a przebieg
  przypomnień (8–17, raz dziennie) zamyka ją bez decyzji.
- **Debrief wysyła stawkę tylko po zmianie w tym otwarciu okna**, a serwer
  pomija stawkę równą tej, którą ten debrief już zgłosił — ponowny zapis
  (np. dopisane pytanie) nie cofa późniejszej korekty. Debrief ma do 30 pytań
  klienta (D8) i jest widoczny w kalendarzu, panelu osoby i profilu.
- **„Stawka od”:** obserwacje `rchange:{id}:req|agreed|prev`; pomyłka przy
  wpisie nie zostawia starej kwoty jako obserwacji.
