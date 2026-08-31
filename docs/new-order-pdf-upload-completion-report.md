# Odczyt PDF przy tworzeniu nowego zamówienia + numer zamówienia Nordei

Jeden ticket, dwie sprawy: brakująca funkcja w formularzu nowego zamówienia
i zgłoszona regresja numeru zamówienia dla Nordei. Łączy je to, że obie
kończą się złym numerem w utworzonym zamówieniu.

---

## 1. PDF w formularzu nowego zamówienia — dla wszystkich klientów

### Stan przed

Odczyt PDF istniał wyłącznie w ścieżce „Uzupełnij zamówienie". Formularz
„Nowy kontraktor / zamówienie" (`NewContractorOrderDialog`, Flow B: atomowy
Contract + Order) przyjmował wyłącznie ręczne wpisy — także wtedy, gdy
operator miał PDF od klienta otwarty obok.

### Stan po

`FileDropZone` + przycisk „Zczytaj dane z dokumentu", widoczne **od razu
i dla każdego klienta**. Ten sam endpoint (`POST /orders/extract`) i te same
reguły klientowe co w „Uzupełnij zamówienie" — zero dodatkowej konfiguracji.

Wypełniane pola: numer zamówienia, okres zamówienia, data rozpoczęcia
kontraktu (dopóki operator nie poda innej), stawka przychodowa, jednostka
stawki i waluta przychodowa.

### Decyzje, które nie są oczywiste

- **Klient wynika z profilu, nie z dokumentu.** Endpoint dostaje `clientId`
  z trasy; z PDF-a nie jest czytany ani weryfikowany żaden identyfikator
  klienta. Test dowodzi wprost, że wywołanie idzie z `clientId` formularza.
- **Dwie polityki nadpisywania w JEDNYM formularzu, obie świadome.** Odczyt
  automatyczny (po wgraniu pliku) uzupełnia **tylko puste pola**; przycisk
  odczytu **nadpisuje**. Reguła repo „dodanie pliku samo z siebie nie zmienia
  pól" broni ręcznej pracy operatora — tutaj formularz startuje pusty, więc
  jej sens spełnia wariant „tylko puste", a ticket dostaje swoje „po wgraniu
  PDF pola uzupełniają się automatycznie".
- **Stawka KOSZTOWA nie pochodzi z dokumentu.** PDF opisuje pozycję
  przychodową klienta; kwota, którą płacimy kontraktorowi, nie wynika z niego.
  Wypełnienie jej czymkolwiek byłoby zgadywaniem na pieniądzach.
- **Jednostka stawki przelicza, a nie przemianowuje.** Gdy dokument mówi
  „MD", a w polu stoi kwota godzinowa, `convertRateInput` przelicza obie
  stawki. Samo przestawienie etykiety dałoby cichy błąd ×8 albo ×22.
- **PDF zapisuje się DRUGIM żądaniem.** `contract-with-order` jest atomowym
  zapisem JSON, więc plik idzie po nim (`PUT …/orders/{id}/file`). Nieudany
  upload NIE cofa utworzonego kontraktu — toast mówi o tym wprost („PDF NIE
  został zapisany, wgraj go ponownie") zamiast udawać sukces.
- **Przycisk jest widoczny, nie ukryty.** Ticket zabrania tego wprost;
  nieaktywny jest wyłącznie do czasu wgrania pliku.

---

## 2. `client_policy` — brak reguł klientowych musi być WIDOCZNY

Odpowiedź odczytu niesie nowe pole `client_policy`: nazwę zastosowanej reguły
klientowej („Nordea", „Bank Pocztowy", „Credit Agricole + Erste Bank Polska"…)
albo `null`.

To nie jest kosmetyka. Bramki polityk są **fail-closed i sterowane zmienną
środowiskową**, więc niewłączona bramka **nie daje żadnego objawu poza cichą
zmianą wyniku**: odczyt „działa" (model coś wypełnia), tylko numer przychodzi
z niewłaściwego pola dokumentu. Dokładnie tak wygląda zgłoszenie o Nordei.
Front zamienia tę ciszę w zdanie:

- polityka zastosowana → „Zastosowano reguły odczytu: Nordea.";
- brak polityki → „Dla tego klienta nie ma jeszcze własnych reguł odczytu PDF
  — pola wypełnił odczyt ogólny. Sprawdź je przed zapisem."

**Wording jest celowo inny niż w tickecie.** Ticket proponuje „Automatyczny
odczyt PDF nie jest jeszcze dostępny dla tego klienta", ale to byłoby
nieprawdą: odczyt ogólny (sam model) działa u każdego klienta i pola wypełnia.
Komunikat, który twierdzi, że nic się nie wydarzyło, gdy pola właśnie się
zmieniły, jest gorszy niż brak komunikatu.

`client_policy` nie jest kwotą, więc przeżywa redakcję finansową — rola bez
`VIEW_FINANCE` też musi wiedzieć, według czyich reguł czytano dokument.

---

## 3. Numer zamówienia Nordei — „Call Off", nie „Frame Agreement"

### Co zastano

Reguła BYŁA zaimplementowana i jest poprawna: `enforce_nordea_order_number`
bierze numer wyłącznie z etykiety „Call Off Agreement number", a jej brak
CZYŚCI pole (fail-closed) zamiast zostawiać numer wybrany przez model. Nie ma
w kodzie żadnej ścieżki, która czytałaby „Frame Agreement number".

### Dwie realne drogi do objawu ze zgłoszenia

1. **Etykieta nie ma jednego zapisu.** Wyrażenie wymagało dokładnie
   `Call` + spacja + `Off` + `Agreement` + `number`/`no.`. Dokumenty mieszają
   `Call-Off`, `Calloff`, a po etykiecie bywa `nr`, `#` albo nic. Każdy taki
   wariant wypadał, a wtedy — bo reguła jest fail-closed — numer był czyszczony
   albo (przy niewłączonej bramce) zostawał numer modelu.
2. **Niewłączona bramka `NORDEA_ORDER_NUMBER_CLIENT_IDS`.** Wtedy polityka
   nie biegnie w ogóle, a model wybiera „a similar document reference" —
   prompt na to pozwala, a `Frame Agreement number` stoi w dokumencie wyżej
   i wygląda równie oficjalnie.

### Co zrobiono

- Wyrażenie przyjmuje wszystkie warianty zapisu etykiety i sufiksu.
- Test negatywny `test_frame_agreement_number_never_becomes_the_order_number`
  dowodzi, że numer UMOWY RAMOWEJ nigdy nie wygrywa — także gdy stoi
  w dokumencie PRZED właściwą etykietą. Helper
  `nordea_frame_agreement_number` istnieje wyłącznie po to, żeby ten test
  mógł pokazać, że wartość w dokumencie JEST, a mimo to nie zostaje wybrana.
- Drogę nr 2 zamyka `client_policy`: operator widzi, czy reguła Nordei w ogóle
  zadziałała, zamiast dowiadywać się o tym z numeru na fakturze.

**Do sprawdzenia po wdrożeniu:** czy `NORDEA_ORDER_NUMBER_CLIENT_IDS` jest
ustawione na produkcji dla właściwego `client_id`. Jeśli nie — to jest cała
przyczyna zgłoszenia, a komunikat „brak reguł odczytu" pokaże to od razu.

---

## Weryfikacja

| Warstwa | Wynik |
|---|---|
| `tests/test_order_pdf_parser.py` (warianty etykiety + test negatywny Frame) | zielone |
| `tests/test_order_extract_endpoint.py` (`client_policy` obecne / `null`) | zielone |
| `NewContractorOrderDialog.test.tsx` | 12 passed (7 nowych) |
| `ruff check app/` + `ruff format --check app/`, `tsc --noEmit` | zielone |

## Świadomie poza zakresem

- **Numer ID konsultanta (BNP) nie jest pokazywany w tym formularzu.** Pole
  `consultant_ref` należy do PR-a #1302; dołożenie go tutaj związałoby oba
  PR-y ze sobą. Po zmerge'owaniu obu warto je dołożyć jednym akapitem.
- **Prompt LLM nietknięty.** Kuszące byłoby dopisanie „never use Frame
  Agreement number", ale zmiana treści promptu zmienia zachowanie modelu dla
  WSZYSTKICH klientów, a regułę i tak rozstrzyga deterministyczna polityka po
  jego odpowiedzi.
