# Kontrakty: jedna lista z szybkimi filtrami (18.11.2026)

<!-- indeks: `/contracts` bez trybów, pigułki, `bucket=ending`, `ending_bucket_clause`, „Uzupełnij · N” w wierszu, `contracts-quick-counts` -->

Decyzja Artura z 18.11.2026 po makietach na stagingu. Tryby „Obsługa kontraktorów”
i „Rejestr kontraktów” pokazywały te same umowy w dwóch cięciach i liczyły
„kończące się” trzema definicjami (8 / 7 / 6 na tej samej bazie). Teraz `/contracts`
to jedna lista `ContractsListV2` z rzędem pigułek nad paskiem filtrów.

- **Pigułki:** „Do uzupełnienia” (`draft` + `ready_for_signature`), „Aktywne”
  (`active` + `ending`, domyślne), „Kończące się” (`bucket=ending`), „Wszystkie”.
  Liczniki to cztery zapytania `/api/contracts` z `page_size: 1` (klucz
  `["contracts-quick-counts"]`): ten sam zakres co lista (portfel DL), bez frazy
  i dat, bo pigułka mówi, ile jest w module.
- **„Kończące się” liczy serwer, jedną regułą:** `contract_service.ending_bucket_clause`
  / `in_ending_bucket` = zapisany status `ending` albo żywa umowa z końcem w 30 dni.
  Czytają ją `/api/contracts?bucket=ending`, eksport i `/api/contractors` ze
  statystykami. Nie dokładaj drugiego licznika z inną definicją (baner „N kontraktów
  kończy się w ciągu 30 dni” po samej dacie zniknął z tego powodu). Trasa
  `/api/contracts/expiring` i parametr `expiring_in_days` zostają dla Jarvisa.
- **Adresy:** pigułka „Kończące się” zapisuje `?status=all&ending=30`. Stare
  `?view=operations&tab=draft|active|ending` i `/contractors?tab=` strona zamienia
  (`legacyOperationsTarget`) na ten sam zbiór listy, bez nowego wpisu w historii.
- **Szkic w wierszu:** serwer dokłada `missing_fields` (bramka aktywacji,
  `validate_ready_for_activation`) tylko szkicom i umowom do podpisu. Osoba z
  „Kontrakty i zamówienia: edycja” widzi „Uzupełnij · N” albo „Aktywuj”, które
  otwierają `DraftCompletionModal`, nie panel; podgląd bez edycji widzi „N braki”
  albo „gotowy”. Kolumna Status ma przy 1280 px ok. 80 px treści, więc pełna
  nazwa („Uzupełnij · 2 braki”) i nazwy pól są w etykiecie i podpowiedzi. Braki
  liczą się bez stawek, których konto nie widzi, a szkic z samymi brakami stawek
  u osoby bez „Stawki i kwoty: zmiana” pokazuje „Czeka na stawki” (`draftRowAction`,
  jak w dawnej „Obsłudze”). Wiersz kilku umów osoby nie ma przycisku, brak jest
  w panelu umowy. „Zakończ projekt” z dawnej „Obsługi” to „Zakończ współpracę”
  w panelu.
- **Ostrzeżenie „N szkice z brakami”** (`drafts_incomplete` z `/api/contractors/stats`)
  to jeden przycisk, który włącza pigułkę „Do uzupełnienia”; krótki, żeby rząd
  pigułek z „Zamówieniami z maila” mieścił się w jednej linii przy 1280 px.
- **Kontrakty jednego klienta** są w profilu klienta (zakładka „Konsultanci”,
  18.11.2026): wybór klienta w pasku filtrów otwiera
  `/clients/{id}?tab=konsultanci`, a stary rejestr pod `?client=` przekierowuje
  tam samo (`klienci/zakladka-konsultanci-u-klienta.md`).
- **„Zamówienia z maila”** to przycisk z licznikiem „do weryfikacji” w rzędzie
  pigułek; otwiera kolejkę pod `?view=order-mail` (linki z powiadomień), powrót
  „Wróć do listy kontraktów”.
- **Odświeżanie:** akcja zmieniająca status albo koniec umowy unieważnia
  `["contracts-v2"]` i `["contracts-quick-counts"]` (ostrzeżenie o szkicach:
  `["contractors-stats-v2"]`). Kluczy `["contracts-expiring-v2"]` i `["contractors-v2"]`
  już nie ma; strażnik `lib/__tests__/query-key-producers.test.ts` wymaga producenta
  każdego unieważnianego klucza.
- Testy: `components/v2/pages/__tests__/ContractsListV2QuickFilters.test.tsx`,
  `app/contracts/__tests__/page-navigation.test.tsx`, backend
  `tests/test_contracts_expiring.py` (zbiór i `bucket=ending`). Inwentarz:
  `k.modes`, `k.quick-filters`, `k.expiring-banner`, `k.operations`.
