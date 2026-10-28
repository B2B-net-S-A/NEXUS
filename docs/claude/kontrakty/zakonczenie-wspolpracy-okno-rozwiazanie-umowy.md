# Zakończenie współpracy = okno + rozwiązanie umowy + Generator (0367, 23.09.2026)

Ticket „Zakończenie współpracy — obowiązkowy formularz” (kontrakt #674:
lista statusu kończyła kontrakt bez powodu i daty). Serwis
`app/services/contract_termination_sync.py`, okno
`components/contracts/ContractTerminationDialog.tsx` (jedno dla karty
kontraktu, formularza edycji, „Zakończ wcześniej” w aneksach, karty
kontraktora na profilu klienta, listy kontraktorów i zbiorczego „Oznacz
zakończone”), logika `lib/contract-termination.ts`.

- **„Zakończony” wyłącznie przez `/terminate` albo `/bulk-mark-ended`.**
  `PATCH /status` i `PATCH /{id}` z `ended` na istniejącej umowie = 409
  `termination_required`; wyjątek `allow_direct_end` ma tylko POST (wpis
  umowy zakończonej przed założeniem rekordu). `/terminate` ma role
  `ContractStatusWriteUser` (admin, DL, TCM) — te same co lista statusu.
- **Status liczy DATA ZAKOŃCZENIA PROJEKTU** (`_status_after_termination`):
  data ≥ dziś → „Kończący się”, < dziś → „Zakończony” od razu, nocny
  `_promote_statuses` przestawia dzień po dacie i zapisuje `Activity`
  `status_auto_changed`. Ostatni dzień UMOWY statusu nie wydłuża — nie ma
  statusu „W wypowiedzeniu”.
- **Rozwiązanie umowy** = `contracts.agreement_termination_*` +
  `agreement_last_day` (komplet albo nic, CHECK). Odznaczone pole w oknie
  CZYŚCI zapisane wcześniej dane. `notice_period_months` (edycja kontraktu)
  podpowiada ostatni dzień przy wypowiedzeniu; brak = puste pole. Załącznik
  idzie DRUGIM żądaniem do dokumentów kontraktu (`termination_notice` /
  `termination_agreement`) — padnięty upload nie cofa zakończenia.
- **Generator zmienia się w chwili „Zakończony”**, nie przy zapisie okna:
  rozwiązanie → `closed`, `closure_date` = ostatni dzień umowy,
  `project_end_date` = koniec projektu, `termination_mode`; bez rozwiązania →
  `suspended` („Umowy bez projektu”), chyba że osoba ma inny trwający
  kontrakt (`active`/`ending`) — wtedy umowa bez zmian. Wiersz szukany po
  `contract_id`, zapasowo po kandydacie (bez linku albo z linkiem do
  kontraktu `ended`/`void`, nigdy do innego żywego). Powód projektu mapuje
  `_CLOSURE_REASON` na katalog Generatora. Idempotentne po
  `termination_restore` (migawka stanu sprzed zmiany + `contract_id`).
- **„Cofnij zakończenie” = `reopen_contract`** (lista statusu na „Aktywny”,
  aneks przedłużenia, `/bulk-extend`): odtwarza wiersz z migawki, czyści dane
  rozwiązania na kontrakcie, załącznik zostaje. `reopen_contract(...,
  after_break=True)` woła wyłącznie `sync_contract_to_live_order` (nowe
  zamówienie wskrzesza kontrakt = powrót po przerwie): przy ROZWIĄZANEJ
  umowie zakłada nową umowę `in_progress` z `previous_generated_contract_id`
  (numer z `_next_seq`), poprzednia zostaje w „Zakończonych”. Lista statusu
  przy powrocie na „Aktywny” zeruje datę końca umowy B2B (lustro PATCH-a) —
  inaczej cron kończyłby ją ponownie w nocy.
- Historia umowy: `b2b_generated_contract_status_events.details` (źródło,
  kontrakt, daty, tryb, strona); „Zakończone umowy” mają kolumny „Data
  zakończenia zamówienia”, „Tryb” i filtr `?termination_mode=`.

## „Co z umową B2B?” — porozumienie z okna (propozycja zespołu, decyzja Artura 28.10.2026)

Zespół prosił o porozumienie z zachowaniem i ze zdjęciem zakazu konkurencji
oraz „Przygotuj porozumienie” w oknie. Oba dokumenty istniały od 23.09
(`termination_agreement`, przełącznik `release_non_compete`), a okno miało
link pod polem wniosków. Mimo to na kopii z 22.10 18 z 22 zakończeń B2B od
23.09 zostawiło umowę bez rozwiązania, a generator nie wydał ani jednego
porozumienia. Problemem była ścieżka, nie brak wzoru — nie dokładaj drugiego
typu dokumentu.

- **Przy jednej umowie odpowiedź jest obowiązkowa** (`agreementPlan`
  w `lib/contract-termination.ts`): „Przygotuj porozumienie” (zalecane),
  „Umowa jest już rozwiązana albo wypowiedziana” (dotychczasowe pola trybu,
  strony, dat i skanu), „Umowa zostaje” (umowa idzie do „Umów bez
  projektu”). Bez odpowiedzi „Zakończ” jest nieaktywne — decyzja o umowie
  zawsze pada. Zbiorcze „Oznacz zakończone” zostaje przy polu „Rozwiązanie
  umowy”: przy wielu umowach nie ma jednej umowy do porozumienia.
- **„Zakończ i przygotuj porozumienie”** zapisuje koniec projektu BEZ danych
  rozwiązania (jak „Umowa zostaje”), potem otwiera generator
  (`documentsHref` z `values`). Rozwiązanie dopisuje podpis porozumienia
  (`effects.apply`: projekt już zakończony = kontrakt bez zmian, umowa
  w rejestrze „Zakończona” z dniem rozwiązania). Odmowa serwera zostaje
  w oknie i nie otwiera generatora.
- **Zakaz konkurencji wybierany w oknie:** domyślnie „zostaje”, przy powodzie
  „Przejście do klienta” — „zdejmujemy” z `client_name` kontraktu. Ręczny
  wybór nie jest nadpisywany zmianą powodu.
- **Wartości startowe kreatora z adresu:** `v_<klucz>` (`1`/`0` = bool,
  wartość ≤ 255 znaków, klucz `[a-z_]`), zdejmowane z adresu po otwarciu jak
  `new`/`parent`/`contract`; wygrywają z podpowiedzią serwera.
- **Przypomnienie na zakończonym kontrakcie B2B bez rozwiązania**
  (`data-testid="agreement-not-terminated"` na karcie „Zakończenie
  współpracy”) z linkiem „Przygotuj porozumienie” i datą końca projektu —
  dla zaległych umów sprzed zmiany.
- Testy: `ContractTerminationDialog.test.tsx` („przygotuj porozumienie”),
  `contract-termination.test.ts`, `b2b-documents.test.ts` („adres kreatora”),
  `app/contracts/[id]/__tests__/signed-delete-flow.test.tsx`.
