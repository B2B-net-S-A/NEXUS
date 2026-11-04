# Aktywacja umowy: `end_date` NIE jest wymagane (umowa bezterminowa)

`ACTIVATION_REQUIRED_FIELDS` (`contract_service.py`) to `start_date`,
`rate_candidate`, `rate_client`, `contract_type` — **bez daty
zakończenia**. Umowa bezterminowa jest w body-leasingu normalnym stanem
docelowym, a nie brakiem danych: rejestr renderuje ją jako „bezterminowo”,
`_status_after_end_date_change` leczy z niej `ended`/`ending` na `active`,
a `ending_soon_clause` jej nie łapie. Wymaganie daty w bramce dawało **stan
bez wyjścia** — taka umowa nie wychodziła z Draftu żadną ścieżką (objaw: 409
przy każdym zapisie na „Aktywny”). PR #1260 obszedł skutek w UI; ten PR usunął
przyczynę. Lustro po stronie zamówień: `_order_has_required_activation_data`.

- **Bramka rozpoznaje stawkę z HARMONOGRAMU**, nie tylko z kolumny cache’u
  (`_has_activation_value` + `inspect(..., raiseerr=False)`, bo woła się ją
  także na wierszach bez eager-loadowanych relacji — inaczej `MissingGreenlet`).
- **W `PATCH /api/contracts/{id}` harmonogramy są wyprowadzane PRZED przejściem
  stanu.** `POST` zawsze miał tę kolejność; `PATCH` ją odwracał, więc bramka
  oglądała pustą kolumnę i odmawiała `missing: rate_candidate` dla stawki
  przysłanej w tym samym żądaniu.
- **„Kończący się” WYMAGA daty końca** (409 `ending_requires_end_date`) — bez
  niej `_status_after_end_date_change` i nocny cron cofają status na `active`,
  więc zapis zwracałby 200 i nie robił nic. Odmowa idzie PO pełnej liście
  braków, żeby nie odsyłać operatora po kolejną odmowę.
- FE ma trzy lustra tej bramki: `DraftCompletionModal`, walidacja „Nowy
  kontrakt” i `extractErrorMsg` (`CONTRACT_FIELD_LABELS`).
