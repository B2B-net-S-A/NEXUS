# Zamówienie MD i zamówienie okresowe to DWA niezależne byty

Kontrakt (`Contract`) opisuje parę *osoba × klient*, a nie pojedyncze
zamówienie. U klientów wielo-konsultantowych ta sama osoba bywa więc opisana
dwa razy: linią grupy MD/kosztowej (`ClientOrder.order_group_id IS NOT NULL`)
i samodzielnym zamówieniem okresowym. Zgłoszenie z sierpnia 2026
(BNP / Polkomtel / BIK / Lotte Wedel): zakończenie tego drugiego kasowało
budżet MD tej samej osoby. Migracja `0262_separate_md_periodic`.

- **Przyczyna była DWUCZĘŚCIOWA i obie połowy trzeba było zamknąć.** Hook
  zatrudnienia (`_ensure_open_order`) zakłada szkic-zaślepkę „(bez numeru)"
  **zanim** Delivery obsadzi osobę na zamówieniu MD, więc bramka przy tworzeniu
  zamówienia nie miała czego odrzucić. Teraz: hook nie tworzy nic, gdy żywa
  linia grupowa już jest, a wejście na linię grupy **kasuje** zostawioną
  zaślepkę (`absorb_auto_draft_shells`). Kasujemy WYŁĄCZNIE wiersz, który na
  pewno niczego nie niesie (szkic, tytuł-zaślepka, bez pliku PO, bez budżetu MD,
  bez `filled_at`) — usunięcie szkicu kasuje też jego plik, a bywa on jedyną
  kopią dokumentu.
- **Ręczne założenie zamówienia okresowego obok żywej linii MD → 409**
  (`assert_no_open_group_line`). Ścieżki AUTOMATYCZNE pytają predykatem i po
  cichu odpuszczają: zatrudnienie nie może się wywrócić dlatego, że ktoś jest
  już na zamówieniu MD. Reguły odwrotnej („nie dodawaj linii MD, gdy jest
  okresowe") świadomie NIE ma — linia grupy powstaje zawsze decyzją operatora.
- **„Zakończ zamówienie" ≠ „Zakończ współpracę" i to są dwa różne przyciski.**
  `POST /api/clients/{c}/orders/{o}/close` domyka JEDEN wiersz i nie dotyka ani
  umowy, ani sąsiednich zamówień. Wypowiedzenie umowy (`/contracts/{id}/terminate`)
  zostaje bez zmian — domyka wszystkie zamówienia kontraktu i otwiera sprawy
  offboardingowe MD, bo umowa opisuje CAŁĄ współpracę u klienta. Zawężenie jej
  po cichu zabiłoby workflow decyzji Delivery Leada.
- **Linia grupy jest z nowego endpointu odrzucana (409)** — grupa ma własne
  zakończenie (`POST /order-groups/{id}/close`), które prowadzi budżet, historię
  i sprawy offboardingowe. Dwie drogi do jednego wiersza rozjechałyby się przy
  pierwszej zmianie którejkolwiek.
- **Data w przyszłości zapisuje się, ale nie wyłącza zamówienia** — lustro
  `close_order_group` i syncu terminacji umowy. Resztę materializuje dzienny
  `dl_portal_expiry_scanner`.
- **`flush` + `refresh` PRZED commitem w `close_order`.** `updated_at` ma
  serwerowy `onupdate`, więc po UPDATE atrybut jest wygasły niezależnie od
  `expire_on_commit=False`; sięgnięcie po niego przy budowaniu odpowiedzi to
  w sesji async `MissingGreenlet`, czyli 500 bez CORS („Network Error").
- **Kontrakt NIE dziedziczy daty końca zamówienia.** Szkic zakładany przy
  obsadzie linii (`_contract_for_candidate`) kopiował `end_date` linii/grupy,
  więc umowa B2B, która ma być bezterminowa, dostawała datę, której nikt nie
  zadeklarował — a nocny `_promote_statuses` przestawiał ją na „Kończąca się",
  potem „Zakończona". Kopiujemy wyłącznie datę ROZPOCZĘCIA. Datę zakończenia
  umowy ustawia człowiek (rejestr umów albo `/terminate`).
  `sync_contract_to_live_order` **zostaje** jako mechanizm wskrzeszania
  („Przedłużenie zamówienia wskrzesza zakończony kontrakt"), ale od 09.2026
  wskrzeszony kontrakt jest BEZTERMINOWY — nie dziedziczy już daty końca
  zamówienia (patrz „Zakładka „Zakończeni" — decyduje umowa, nie okres
  zamówienia").
- **Zakończenie u jednego klienta nie sięga do drugiego.**
  `client_orders.client_id` to WŁASNA kolumna, a baza nie ma więzu wiążącego ją
  z klientem kontraktu (rozjazd zna też `contract_merge`). Kaskada offboardingu
  bierze teraz wyłącznie zamówienia, dla których `ClientOrder.client_id ==
  Contract.client_id`; wiersz rozjechany zostaje nietknięty i widać go
  w `GET /api/admin/engagement-inventory` (checki `order_client_mismatch`
  i `periodic_duplicates_group_line`). Cicha zmiana czyjegoś stanu na podstawie
  niespójnych danych jest gorsza niż jej brak — dlatego audyt, nie automat.
- **Naprawa danych: migracja `0262` + lustro w `entrypoint.sh`** (prod alembic
  bywa osierocony, a ta naprawa jest treścią ticketu). SQL ma JEDNO źródło:
  `app/services/order_separation_repair.py`. Jest jednorazowy (advisory lock +
  marker w `app_settings`) i regułowy — **ani jednego `client_id` w SQL-u**.
  Czterej klienci ze zgłoszenia są przypadkiem reguły, nie jej definicją.
  Krok A kasuje puste zaślepki i ANULUJE (nie kasuje) pozostałe duplikaty;
  krok B czyści datę końca umowy i przywraca `active` tylko tam, gdzie widać,
  że nikt współpracy nie zakończył (brak `terminated_at`, brak powodu, brak
  aneksu `early_termination`, żywa linia grupowa obejmująca dziś). Paragon
  w `app_settings`.
- **Karta kontraktora znika, gdy zostaje po niej wyłącznie martwy duplikat**
  (`filterMaterializedContractorShells` — warunkiem jest brak ŻYWEGO zamówienia
  samodzielnego, nie brak zamówień w ogóle). Osoba z realnym, otwartym
  zamówieniem okresowym obok linii MD nadal ma obie pozycje: to dwa różne
  zaangażowania i o ich rozdzielenie w tym tickecie chodzi.
