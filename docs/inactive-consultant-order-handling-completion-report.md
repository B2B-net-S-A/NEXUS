# Konsultant nieaktywny/nieznaleziony na zamówieniu MD/kosztowym — raport

Ticket B (09.2026): reguła ogólna dla wszystkich klientów rozliczanych w MD albo
kwotą budżetową. Punkt wyjścia: #1494 zrobił kartę „Zakończył współpracę"
w oknie **Nowe zamówienie** i zostawianie zużycia przy osobie usuniętej
z zamówienia. Brakowało dwóch ścieżek odczytu i jednego źródła komunikatu.

## Co było nie tak

| Ścieżka | Przed | Po |
|---|---|---|
| Poczta (MD/kosztowe) | osoba z zakończonym kontraktem — automat zapisywał zamówienie i **po cichu wznawiał kontrakt**; osoby spoza klienta — automat zakładał nowego kandydata i szkic | wiersz `decide_person` z komunikatem, „Zastosuj" wyłączone, przycisk **Rozstrzygnij w oknie zamówienia** |
| „Uzupełnij zamówienie" | odczyt PDF-a tylko nagłówka; osoby z dokumentu jako tabela informacyjna, bez dopasowania | ten sam odczyt co „Nowe zamówienie": karty osób spoza zamówienia z odznakami i wyborem, zapis atomowy |
| „Nowe zamówienie" — lista „kilka osób" | wybór kontraktu **zakończonego** z listy zapisywał zwykłą linię i wznawiał kontrakt | wybór zakończonego kontraktu przechodzi w pytanie zostaw / wznów / zastąp / usuń |
| Karta zamówienia | „Wykorzystał(a) na tym zamówieniu X MD" (bez nazwiska, kosztowe inaczej) | „[osoba] wykorzystał(a) X zł / Y MD na tym zamówieniu przed zakończeniem współpracy — ta kwota nie wraca do puli" dla MD i kosztowych |

## Zmiany

**Backend**
- `services/order_consultant_match.py` — `inactive_consultant_reason`,
  `unknown_consultant_reason`: jedno źródło komunikatu dla okna i poczty.
- `services/order_mail_resolver.py` — `ResolvedConsultant.contract_end_date` (ISO,
  bo rekord trafia do JSONB dokumentu).
- `services/order_mail_planner.py` — `ACTION_DECIDE_PERSON` dla `order_type ∈ {md, cost}`;
  zamówienie okresowe bez zmian (decyzja z 10.09: powrót po przerwie / nowy szkic).
- `api/order_mail_queue.py` — `GET /api/order-mail/queue/{id}/order-target`
  (klient, otwarta grupa o tym numerze przez `titles_collide`, typ zamówienia),
  `POST /api/order-mail/queue/{id}/resolved-in-order` (dokument → `applied`,
  `proposal.resolved_in_order`, Activity `order_mail_resolved_in_order`; bez
  `applied_order_id`, bo to pole czyta aktywacja szkiców z maila po podpisie).
  Obie trasy za tymi samymi bramkami co „Zastosuj" (`_load_visible` +
  `_require_apply_rights`).
- `api/client_order_groups.py` — `POST /api/clients/{c}/order-groups/{g}/lines/batch`
  (osoby z dokumentu razem albo wcale); `add_line` rozbite na
  `_group_accepting_lines` + `_add_line_to_group` (wspólne dla obu tras);
  `OrderPlanContractRead.inactive_reason` dla zakończonych kontraktów.

**Frontend**
- `OrderGroupFormModal` — tryb edycji czyta PDF przez `/order-groups/extract`,
  karty tylko dla osób spoza zamówienia (`splitPlanForGroup`), ramka „Już na
  zamówieniu"; `autoReadFile` + `sourceNotice` dla PDF-a z maila; plik z maila
  przy grupie z własnym PDF-em domyślnie tylko do odczytu (checkbox podmiany).
- `MultiConsultantOrdersTab` — `?orderMailDoc=` (przez stronę klienta): pobiera PDF,
  otwiera „Uzupełnij" albo „Nowe zamówienie", po zapisie `resolved-in-order`;
  przy edycji dopisuje osoby `addLines` po PATCH-u nagłówka (błąd dopisania
  zostawia okno otwarte i mówi, że nagłówek jest zapisany).
- `lib/order-plan.ts` — `chooseContract` (zakończony → decyzja), `backToOptions`,
  `splitPlanForGroup`; `OrderPlanLineCard` — „Wybierz inną pozycję z listy".
- `OrderMailQueue` — ramka „Osoba do rozstrzygnięcia", link do okna, „Zastosuj"
  wyłączone z wyjaśnieniem.
- `lib/order-line-usage.ts` + `OrderGroupCard` — zdanie o wykorzystaniu.

**Instrukcja w Pomocy** przejrzana i przestemplowana (sekcje: odznaki kart,
„Uzupełnij zamówienie", usunięcie/zastąpienie, zamówienia ze skrzynki).

## Testy

- `backend/tests/test_inactive_consultant_all_paths.py` (15): ten sam komunikat
  w oknie i w poczcie; planer poczty parametryzowany klientem (układ Polkomtela —
  kosztowe, BIK — MD, dowolny klient) + okresowe bez zmian; usunięcie i
  zastępstwo nie zwracają zużycia (kosztowe i MD per osoba); batch atomowy;
  kolejka → okno → `resolved-in-order` (w tym odmowa dla grupy innego klienta);
  batch odmawia osoby, która już pracuje na zamówieniu;
  `inactive_reason` na liście opcji. Sabotaż sprawdzony: wyłączenie decyzji
  w planerze i commit po każdej linii w batchu zapalają testy.
- `test_order_mail_gate_and_planner.py` — zaktualizowane oczekiwanie: osoba
  nieznaleziona na zamówieniu MD to `decide_person` (okresowe: nadal szkic).
- Szeroki przebieg celowany: 60 plików dotykających zamówień / poczty — 1138 zielonych
  (jedna zmiana oczekiwania, opisana wyżej).
- Frontend: `CompleteOrderFromPdf`, `MultiConsultantOrdersTabMailDoc`,
  `order-line-usage`, nowe przypadki w `order-plan` i `OrderMailQueueView`;
  katalogi zamówień, kolejki, `lib` i profilu klienta — 105 plików, 1354 testy.

## Przegląd adwersarialny — co znalazł i co poprawiono

- **Dublowanie osoby przy „Uzupełnij":** karta bez dopasowania (BNP — sam numer ID,
  literówka, „kilka osób") pozwalała wskazać osobę, która już pracuje na zamówieniu,
  czyli dać jej drugi budżet MD. Teraz karta to zgłasza i blokuje zapis, a
  `…/lines/batch` odmawia 409 (także dwóch kart jednej osoby). Karta BNP bez
  nazwiska nie powstaje w trybie uzupełniania (to pola nagłówka).
- **Aktywacja pustego szkicu z osobami z PDF-a** padała (serwer nie aktywuje
  zamówienia bez konsultantów, a aktywacja szła przed dopisaniem). Kolejność:
  nagłówek jako szkic → osoby → aktywacja; awaria samej aktywacji to częściowy
  sukces z komunikatem (ponowny zapis dopisałby osoby drugi raz).
- **„bez zmian"** w ramce „Już na zamówieniu" — teraz porównuje MD i stawkę z PDF-a.
- Błąd sieci bez odpowiedzi nie przechodzi już jako angielskie „Network Error";
  grupa ukryta na liście nie otwiera po cichu „Nowego zamówienia" (drugiego
  o tym numerze); Esc w trakcie zapisu nie odpina dokumentu z maila; TCM nie
  widzi pełnych powodów planu (lustro `gate_reasons`).

## Świadomie poza zakresem

- „Dodaj przedłużenie" (nowa grupa z poprzednika) nie dopasowuje osób z PDF-a —
  kopiuje obsadę poprzednika; ticket wymienia trzy ścieżki.
- Osoba nieznaleziona NIGDZIE w bazie nie może zostać „zapisem historycznym" —
  linia musi wisieć na kontrakcie u klienta. Karta daje wtedy: wskaż ręcznie
  (osoba z bazy), zastąp, usuń.
