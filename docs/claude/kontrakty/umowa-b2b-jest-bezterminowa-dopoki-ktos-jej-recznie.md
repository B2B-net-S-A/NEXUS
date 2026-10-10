# Umowa B2B jest bezterminowa, dopóki ktoś jej ręcznie nie zakończy (11.09.2026)

Data zakończenia umów B2B była przepisywana z końca ZAMÓWIENIA (pole
„Contract end" w oknie „Nowy kontraktor / zamówienie", aneks „Przedłuż",
scalanie duplikatów), a nocny cron kończył potem umowę, choć współpraca
trwała. Reguła ma jedno źródło: `app/services/b2b_contract_end_date.py`
(front: `lib/contract-end-date.ts`).

- **Umowa B2B w statusie innym niż „Zakończony"/„Anulowany" nie ma daty
  zakończenia, chyba że ktoś ją ręcznie zakończył** — `/terminate`
  („Zakończ współpracę": `terminated_at` + `termination_reason`, data także
  przyszła) albo aneksem `early_termination`. Umowy zlecenie i o pracę bez
  zmian — tam data końca jest częścią umowy.
- **API odmawia 422 (`reason: b2b_end_date_requires_termination`), nie
  zeruje po cichu:** tworzenie (`POST /contracts` — datę niesie tylko wpis
  umowy już zakończonej), edycja (`PATCH` — sprawdzana wyłącznie ZMIANA daty
  albo typu, więc zapis innego pola z nieruszaną datą przechodzi; status
  liczony wynikowy), aneks `extension`, `contract-with-order`
  (`contract_end_date` wycofane z formularza). `/bulk-extend` pomija takie
  umowy. Wyczyszczenie daty jest zawsze dozwolone.
- **Przywrócenie umowy B2B z „Zakończony"/„Kończący się" na „Aktywny"
  w rejestrze czyści datę** (jak wskrzeszenie zamówieniem) — ze starą datą
  cron kończyłby ją następnej nocy.
- **Scalanie duplikatów** (`contract_merge.merge_field_plan`) zostawia żywą
  umowę B2B bez wypowiedzenia bezterminową zamiast brać „najpóźniejszą datę".
- **„Kto i dlaczego" żyje w `termination_lessons`** (pole tekstowe dialogu
  „Zakończ współpracę", format „[Kto] — [Powód]"); `termination_reason` to
  słownik analityki odejść (inicjatywa konsultanta = rezygnacja). Karta
  „Zaplanowane zakończenie współpracy" na szczegółach kontraktu pokazuje je
  od chwili wypowiedzenia, nie dopiero w dniu końca (dyskryminator: umowa
  przywrócona ma `terminated_at`, ale `end_date IS NULL`).
- **Zakończenie z datą przyszłą NIE daje dziś statusu „Zakończony"** (P0.7):
  umowa pracuje do tej daty (od 23.09.2026 od razu „Kończący się”, także
  gdy datą jest dziś), cron domyka ją dzień po dacie — inaczej osoba
  znikałaby z MRR przed czasem. Szczegóły w sekcji niżej.
- **Jednorazowa korekta:** `app/services/b2b_end_date_repair.py`, blok
  w `entrypoint.sh`, marker `0307_b2b_indefinite_end_date` (paragon: liczby,
  ID, daty) + `repair_details_0307_…` (treść wpisów, poprzednie wartości —
  klucz innego kształtu, publiczny workflow `migration-receipts` go nie
  drukuje). Najpierw zakończenia osób ze zgłoszenia — **po trójkach
  ID (kontrakt, kandydat, klient), bez nazwisk w repo**; niezgodna trójka =
  pominięcie z kodem powodu. Potem każda umowa B2B „Aktywny"/„Kończący się"
  z datą i bez ręcznego zakończenia → bezterminowa („Kończący się" →
  „Aktywny"). Szkice świadomie poza korektą (wyczyszczona data wpuściłaby
  martwy szkic do MRR przy najbliższej aktywacji). Test
  `test_ticket_lists_all_sixteen_people…` trzyma CI na czerwono, dopóki
  lista nie jest kompletna — marker jest jednorazowy.
