# Historia stawek kontraktu z faktur KSeF (0782, 25.11.2026)
<!-- indeks: stawka klienta z ceny pozycji faktury sprzedaży, stawka kosztowa = netto faktury konsultanta ÷ godziny klienta, okres stałej stawki ≥ 2 miesiące ±1%, krok bazowy od startu, wpis automatyczny tylko historii, karta „Faktury KSeF pokazują inną stawkę”, pigułka „Stawka z faktur”, `contract_rate_history_findings`, `CONTRACT_RATE_HISTORY_AUTO_APPLY` -->

Audyt finansów 25.11.2026: kontrakty często trzymają tylko bieżącą stawkę
klienta i kosztową, więc po zmianie stawek w ciągu roku marża i MRR za
wcześniejsze miesiące są złe. Faktury KSeF mają historię. Artur chce, żeby
brakujące dane, które NEXUS umie udowodnić, uzupełniała reguła. Decyzje
Artura z 25.11.2026 (pytanie z pomiarem):

- **wpis automatyczny tylko historii** — jednoznaczne kroki, które nie
  zmieniają dzisiejszej stawki; rozjazdy bieżące i przypadki „do sprawdzenia”
  idą na kartę dla Finansów;
- **krok bez aneksu** — krok w `contract_client_rates` /
  `contract_candidate_rates` z notą „Z faktur KSeF: …”, wpis na osi czasu.
  Aneksów nie ma na papierze, a faktury za te miesiące są już wystawione,
  więc zamówienia i rejestr aneksów zostają bez zmian;
- **karta w kontrakcie + pigułka na liście** (jak „Stawka z dokumentu”).

## Dowód (`services/contract_rate_history/collect.py`)

- **Stawka klienta** = cena jednostkowa pozycji faktury sprzedaży z osobą
  (MD ÷ 8 → zł/h). Nordea ma rabat 2,5% w netto, a kontrakt trzyma cenę
  z pozycji (sprawdzone na 25 kontraktach Nordei) — porównujemy cenę, nie
  netto. Pomijamy pozycje „szt.” (refaktury, hotele), nadgodziny, onboarding
  i korekty, ceny ≤ 0 i faktury w innej walucie niż zł. Dwie różne ceny
  osoby w miesiącu = miesiąc bez dowodu.
- **Osoba na pozycji**: numer osoby u klienta z kartoteki
  (`client_external_ids`, potwierdzony; Nordea `ID: M…`), a bez niego pełne
  imię i nazwisko osoby z kontraktem u tego klienta, trwającym w miesiącu
  („Contractor:Jan” to dwa słowa, „Contact: …” to osoba klienta). Pozycja bez
  nazwiska („Praca kontraktora: 414097”) należy do osoby, gdy faktura jest
  przypięta do zamówienia jednej osoby. Imiennicy albo dwa kontrakty osoby
  u klienta w miesiącu = bez kontraktu.
- **Stawka kosztowa** = netto faktur konsultanta z KSeF (`approval_documents`,
  `source='ksef'`) za miesiąc ÷ godziny z faktury do klienta. Sprzedawca =
  pełne imię i nazwisko jednej osoby z kontraktem w NEXUSIE. Miesiąc faktury:
  od 25. dnia bieżący, wcześniej poprzedni; gdy poprzedni ma już fakturę
  z końca miesiąca, a bieżący ma godziny u klienta — bieżący (okno ±1).
  Miesiąc z korektą (konsultanta albo sprzedaży z osobą) i osoba z więcej
  niż jednym kontraktem w miesiącu = bez obserwacji kosztu.

## Reguła (`infer.py`, czysta funkcja)

- **Stała stawka** = co najmniej 2 miesiące z obserwacją w ±1% od mediany
  okresu. Jeden odstający miesiąc między dwoma miesiącami tej samej stawki
  nie przerywa okresu. Mediana bliżej pełnego złotego niż 0,15% → pełny złoty;
  okres zgodny z NEXUSEM dostaje dokładnie wartość z NEXUSA.
- **Krok** od 1. dnia pierwszego miesiąca okresu, gdy NEXUS w którymkolwiek
  miesiącu okresu ma inną stawkę (±1%). Kroki liczone po kolei, więc po
  okresie starej stawki wraca krok z bieżącą. Pierwszy okres zaczyna się
  od pierwszego miesiąca z fakturą — wcześniejszych miesięcy nie ruszamy.
- **Krok bazowy**: harmonogram przed pierwszym krokiem czyta najwcześniejszy
  krok (`Contract._resolve_scheduled_rate`, lustro `infer.rate_on`), więc
  pierwszy krok z faktur zmieniłby też miesiące bez dowodu. Gdy krok z faktur
  jest najwcześniejszy, dochodzi krok od startu kontraktu z dotychczasową
  stawką („Stawka sprzed historii z faktur KSeF”).
- **Do sprawdzenia** (nie automat): krok zmienia dzisiejszą stawkę, krok
  człowieka w NEXUSIE wewnątrz okresu z faktur, miesiąc bez dowodu między
  dwiema stawkami, po okresie miesiąc ze stawką, której krok nie wyjaśnia,
  różnica ponad 50%, okres przed startem kontraktu, kontrakt bez daty startu
  albo nie w zł/h, nieprzyjęte rozliczenie (`client_settlements`) w miesiącach
  od kroku.
- **Kategorie**: `brak_historii` (klient i koszt zmienione razem, NEXUS ma
  tylko bieżącą), `rozjazd_biezacy` (ostatni miesiąc z faktur ≠ NEXUS),
  `rozjazd_w_przeszlosci` (jedna strona w części miesięcy).

## Zapis i decyzje (`service.py`, `tasks/contract_rate_history.py`)

- Pętla w workerze co 6 h: reguła dla wszystkich kontraktów z fakturami
  od 01.2026 do ostatniego pełnego miesiąca, wiersz na kontrakt
  w `contract_rate_history_findings` (`signature` = te same kroki w kolejnym
  przebiegu), potem wpis automatyczny (`CONTRACT_RATE_HISTORY_AUTO_APPLY`,
  domyślnie włączony). Odrzucona propozycja nie wraca, dopóki faktury nie
  dadzą innej. Na stagingu pętla działa (sama baza).
- „Wprowadź do harmonogramu” (zmiana kwot albo Delivery Lead klienta,
  `can_confirm_rate_annex`) liczy regułę od nowa po blokadzie kontraktu.
  Krok kosztowy zmieniający dzisiejszą stawkę przestawia też
  `rate_candidate` i koszt trwających zamówień (`resync_contract_safely`).
  Dzisiejszą stawkę klienta prowadzi zamówienie — taki krok to 409
  z prośbą o aneks „Zmiana stawki”.
- „Cofnij” wpisu automatycznego przez 7 dni usuwa jego kroki; podpowiedź
  wraca na kartę, automat jej już nie rusza. „Odrzuć” — edycja kontraktu.
- Lista: `bucket=rate_history`, adres `?rate_hist=1`, notka w wierszu
  z `rate_history_change` (redagowana razem z kwotami).
- Pomiar: `python -m scripts.contract_rate_history_report [--json plik]`
  (tylko odczyt; plik ma stawki — nie do repo). Kopia z 24.11.2026, IV–X:
  480 kontraktów z fakturami, 27 z krokami (6 brak historii, 5 rozjazd
  bieżący, 16 w przeszłości), 50 kroków, 12 kontraktów automatem.
- Testy: `test_contract_rate_history_infer.py` (bez bazy),
  `test_contract_rate_history_api.py`, `ContractRateHistoryKsefCard.test.tsx`.
