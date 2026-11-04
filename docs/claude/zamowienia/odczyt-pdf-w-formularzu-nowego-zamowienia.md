# Odczyt PDF w formularzu NOWEGO zamówienia

„Zczytaj dane z dokumentu" działa też w „Nowy kontraktor / zamówienie"
(`NewContractorOrderDialog`), dla KAŻDEGO klienta. Ten sam endpoint i te same
reguły klientowe co w „Uzupełnij zamówienie" — bez osobnej konfiguracji.

- **Klient wynika z profilu**, z którego formularz otwarto, i nigdy nie jest
  czytany z dokumentu: endpoint dostaje `clientId` z trasy.
- **Dwie polityki nadpisywania w jednym formularzu, obie świadome.** Odczyt
  AUTOMATYCZNY po wgraniu pliku uzupełnia wyłącznie PUSTE pola — formularz
  startuje pusty, więc jest to skrót, a nie kasowanie cudzej pracy. Przycisk
  „Zczytaj dane z dokumentu" NADPISUJE, bo to świadoma prośba o ponowny odczyt.
  Reguła repo „dodanie pliku samo z siebie nie zmienia pól" broni ręcznych
  wpisów i tutaj jest spełniona wariantem „tylko puste".
- **PDF zapisuje się DRUGIM żądaniem.** `contract-with-order` jest atomowym
  zapisem JSON, więc plik idzie po nim (`PUT …/orders/{id}/file`). Nieudany
  upload NIE cofa utworzonego kontraktu — mówimy o tym wprost w toaście,
  zamiast udawać, że nic się nie stało.
- **Stawka KOSZTOWA nie pochodzi z dokumentu.** PDF opisuje pozycję
  przychodową klienta; kwota, którą płacimy kontraktorowi, nie wynika z niego
  i zostaje do wpisania ręcznie.

### `client_policy` — brak reguł klientowych ma być WIDOCZNY

Odpowiedź odczytu niesie `client_policy`: nazwę zastosowanej reguły klientowej
albo `null`. To nie jest kosmetyka — bramki są fail-closed i sterowane env-em,
więc **niewłączona bramka nie daje żadnego objawu poza cichą zmianą wyniku**.
Zgłoszenie „Nordea nadal bierze numer z Frame Agreement" jest dokładnie tym
trybem awarii: odczyt „działa" (model coś wypełnia), a numer przychodzi
z niewłaściwego pola. Pusta nazwa jest w interfejsie zdaniem, a nie ciszą.

Uwaga na wording: brak reguł NIE znaczy „odczyt niedostępny" — odczyt ogólny
(sam model) działa u każdego klienta i pola wypełnia. Komunikat mówi więc
„nie ma jeszcze własnych reguł, sprawdź pola", bo tak jest naprawdę.

### Etykieta Nordei nie ma jednego zapisu

`Call Off` / `Call-Off` / `Calloff`, a po niej `number` / `no.` / `nr` / `#`
albo nic. Wąskie wyrażenie wypadało na każdym wariancie poza pierwszym, a
polityka jest fail-closed: nierozpoznana etykieta CZYŚCI numer. Przy
niewłączonej bramce zostawał wtedy numer wybrany przez model — czyli zwykle
`Frame Agreement number`, bo stoi w dokumencie wyżej i wygląda równie
oficjalnie (prompt dopuszcza „a similar document reference"). Test negatywny
`test_frame_agreement_number_never_becomes_the_order_number` pilnuje, że numer
UMOWY RAMOWEJ nigdy nie wygrywa — także wtedy, gdy stoi przed właściwą etykietą.
