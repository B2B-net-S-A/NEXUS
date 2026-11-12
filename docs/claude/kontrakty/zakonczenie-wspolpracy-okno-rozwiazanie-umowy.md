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
  dla zaległych umów sprzed zmiany. Drugi link, „Wszystkie nierozwiązane
  umowy”, prowadzi do filtra rejestru (`filtr-umowa-nierozwiazana-w-rejestrze.md`),
  bo zespół domyka zaległe umowy z tej jednej listy (decyzja Artura 28.10.2026).
- Testy: `ContractTerminationDialog.test.tsx` („przygotuj porozumienie”),
  `contract-termination.test.ts`, `b2b-documents.test.ts` („adres kreatora”),
  `app/contracts/[id]/__tests__/signed-delete-flow.test.tsx`.

### „Przygotuj wypowiedzenie” (zgłoszenie zespołu, 10.11.2026)

Zespół pisał wypowiedzenia ręcznie, bo okno proponowało tylko porozumienie,
choć generator ma „Wypowiedzenie umowy (przez B2B.net)” (`termination_notice`)
od #1759. Brakowało drogi, nie wzoru — tak samo jak przy porozumieniu.

- **Czwarta odpowiedź `notice`** działa jak `prepare`: zapisuje koniec
  projektu bez danych rozwiązania, potem otwiera generator na
  `termination_notice`. Dane rozwiązania (tryb, strona B2B.net, doręczenie,
  ostatni dzień) dopisuje `effects.apply` przy dokumencie.
- **Dat okno nie przekazuje.** Doręczenie (dziś) i rozwiązanie (koniec
  okresu wypowiedzenia z wersji wzoru umowy, a gdy koniec projektu jest
  późniejszy — koniec projektu, punkt niżej) podpowiada serwer generatora;
  `v_termination_date` z okna przykryłby to wyliczenie końcem projektu.
  Okno nie liczy daty z `notice_period_months` kontraktu: na kopii z 10.11
  pole było puste na 502 z 502 żywych kontraktów B2B, a 113 z 114 aktywnych
  umów w generatorze ma wersję wzoru, z której generator zna okres.
- **Rozwiązanie = późniejsza z dwóch dat** (audyt 12.11.2026, K1). Do tej poprawki
  generator podpowiadał koniec okresu wypowiedzenia także wtedy, gdy koniec
  projektu z okna był późniejszy, a podpis ustawiał ten dzień jako koniec
  kontraktu i przycinał zamówienia (projekt do 31.01.2027 kończył się 31.12.2026).
  Teraz prefill (`document_prefill`) bierze koniec projektu z kontraktu umowy
  bazowej (`effects.project_end_from_window`: kontrakt aktywny albo kończący się
  z `terminated_at` z okna), gdy jest późniejszy, i mówi to w notce pod polem
  (`notes` w odpowiedzi prefillu, `DocumentFieldsForm`). Okno dalej nie podaje
  daty w adresie, bo `v_termination_date` przykryłby wyliczenie okresu; koniec
  projektu czyta serwer z kontraktu, który okno zapisało przed otwarciem generatora.
- **Podpis wypowiedzenia z wcześniejszą datą nie skraca projektu z okna**
  (`notice_keeps_project_end`): kontrakt i zamówienia zostają, umowa w rejestrze
  zamyka się z dniem rozwiązania, a podgląd skutków ostrzega, że umowa rozwiąże
  się przed końcem projektu. Dotyczy tylko `termination_notice`: porozumienie ma
  własny ostatni dzień świadczenia usług i on decyduje. Kontrakt bez decyzji
  z okna (`terminated_at` puste) wypowiedzenie kończy jak dotąd. Testy:
  `tests/test_b2b_termination_notice_project_end.py`.
- **Powód idzie jako `v_termination_reason` tylko z listy wypowiedzenia**
  (`noticeReason`, lustro `_TERMINATION_BY_COMPANY`). Inny powód kontraktu
  zostawia pole puste do wyboru w generatorze.
- Wypowiedzenie złożone przez Partnera dalej zapisuje się przez „Umowa jest
  już rozwiązana albo wypowiedziana” — generator nie ma tego dokumentu, bo
  pisze go Partner.

## Rozwiązanie podpisane poza NEXUSEM (zgłoszenie zespołu, decyzja Artura 29.10.2026)

Kontrakt zakończony bez danych rozwiązania nie miał gdzie ich dopisać: okno
działa w chwili kończenia, a podpis porozumienia — tylko dla umowy
z generatora (umowy sprzed NEXUSA nie mają wiersza). Przypomnienie na karcie
wisiało więc na zawsze mimo podpisanego porozumienia.

- **`PUT /api/contracts/{id}/agreement-termination`** (`ContractStatusUser`,
  zakres DL-a jak `/terminate`) zapisuje wyłącznie komplet
  `agreement_termination_*` na kontrakcie B2B „Zakończony”/„Kończący się” —
  także zakończonym nocną zmianą po dacie końca, bez okna i bez
  `terminated_at` (28 z 69 nierozwiązanych na kopii z 22.10). Koniec projektu,
  zamówienia, status i aneksy zostają — nie wołaj do tego ponownie
  `/terminate`, który rusza zamówienia i dopisuje drugi wpis „terminated”.
  Inny typ umowy = 422, kontrakt niezakończony = 409, rozwiązanie już
  zapisane = 409 (zmiana przez „Cofnij zakończenie”, bo nadpisanie rozjechałoby
  kontrakt z zamkniętą umową w Generatorze). Wpis `Activity`
  `agreement_termination_recorded`.
- **Generator jak w oknie z rozwiązaniem:** na „Zakończonym” umowa zawieszona
  TYM zakończeniem (`suspended` z `termination_restore.contract_id` =
  kontrakt) przechodzi do „Zakończonych” z ostatnim dniem umowy
  (`close_rows_after_recorded_termination`, migawka z zawieszenia zostaje),
  a pozostałe umowy kontraktu — także zostawione przy innym trwającym
  projekcie — zamyka `sync_generator_after_contract_ended`. „Cofnij
  zakończenie” wraca do stanu sprzed zakończenia projektu i czyści
  rozwiązanie. „Kończący się” Generatora nie rusza — zrobi to nocna zmiana
  statusu.
- **Wejścia:** „Zapisz rozwiązanie umowy” w przypomnieniu na karcie i „+
  Rozwiązanie” w wierszu listy „Umowa nierozwiązana” — to samo okno
  `ContractAgreementRecordDialog` (tryb domyślnie porozumienie, ostatni dzień
  z końca projektu, skan drugim żądaniem do dokumentów). Bez zapisu
  zbiorczego: każda umowa ma własne daty, a zgadnięty ostatni dzień umowy
  przesuwa okres wypowiedzenia i zakaz konkurencji.
- Testy: `tests/test_contract_agreement_termination_record.py`,
  `ContractAgreementRecordDialog.test.tsx`.
