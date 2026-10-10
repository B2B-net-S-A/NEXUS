# Centrum e-Zdrowia: umowy ramowe (części) → umowy wykonawcze + zamówienia MD (09.2026)

Ticket „Struktura umów wykonawczych" + ticket danych startowych MD (16.09.2026).
Migracje `0312_ezdrowie_executive_contracts`, `0313_md_optional_scope_and_consumption_status`
(+ lustro DDL i zasiewu w `entrypoint.sh`, sonda `client_executive_contracts`
w `/api/health/deep`). Funkcja dotyczy WYŁĄCZNIE klienta 115 (bramka
`app/services/ezdrowie.py`); u innych klientów pola są NULL, a trasy odpowiadają 422.

- **Umowa ramowa JEST częścią.** `client_framework_contracts.project_part`
  (`cz1|cz2|cz4|cz5|cz6`, jedna ramowa na część u klienta —
  `ux_client_framework_contracts_client_part`). Pod nią `client_executive_contracts`
  (numer unikalny per klient, status `active|ended`, domyślnie `active` — ticket).
  Docelowa struktura (5 ramowych, 3 wykonawcze) jest zasiana idempotentnie z JEDNEGO
  źródła SQL `app/services/ezdrowie_structure.py` (migracja + entrypoint; no-op bez
  klienta 115; `source_key` bez dwukropka — `:cz1` w literale `text()` byłoby
  parametrem wiązanym). Numery „DO UMOWY RAMOWEJ" na dokumentach są BŁĘDNE —
  struktura nigdy nie jest parsowana z treści dokumentu.
- **Konsultant jest przypisany do umowy WYKONAWCZEJ, nie do części.**
  `client_orders.executive_contract_id` i `client_order_groups.executive_contract_id`;
  `project_part` zostaje jako WARTOŚĆ POCHODNA z części umowy ramowej (czytają ją
  dziedziczenie z maila i stare konsumenty). Jedna reguła
  `resolve_ezdrowie_assignment(db, client_id=…, executive_contract_id=…, project_part=…, require=…)`:
  u CeZ przy nowym zamówieniu / przedłużeniu / nowej karcie MD umowa wykonawcza jest
  WYMAGANA („Wybierz umowę wykonawczą" — sama część już nie wystarcza, bo pod jedną
  częścią bywa kilka umów), musi być `active` i tego klienta; jawna część niezgodna
  z umową → 422; u innych klientów oba pola muszą być puste. Wołają ją Flow A/B/PATCH
  w `client_orders.py`, `create_order_group` i przypisanie z ekranu przeglądu.
- **Tag na profilu = reprezentatywne zamówienie kontraktu** (`app/services/representative_order.py`
  — wyniesione z `clients.py`, ta sama reguła co dotąd dla części): `ActiveConsultantItem.executive_contract`.
  Linie kart MD dziedziczą umowę i część z grupy, więc po imporcie startowym tag idzie z linii.
- **Router `app/api/client_executive_contracts.py`** (`DELIVERY_SECTION_DEPENDENCIES`;
  zapis `DlAssignedOrAdmin`): `GET /api/clients/{id}/contract-structure`,
  `POST/PATCH …/executive-contracts[/{ec_id}]` (`ended` z żywymi przypisaniami → 409),
  `GET …/executive-contracts/review` (obecni + planowani bez umowy wykonawczej na
  reprezentatywnym zamówieniu — `suggested_framework_contract_id` to WYŁĄCZNIE
  podświetlenie nagłówka części, ekran NIE preselekcjonuje umowy: ticket zabrania
  automigracji nawet przy jednej umowie pod częścią), `POST …/executive-contracts/assignments`
  (ustawia na reprezentatywnym zamówieniu; kontrakt bez zamówienia dostaje szkic —
  lustro reguły „część umowy zakłada szkic"). Serwis: `app/services/executive_contracts.py`.
- **Front:** `lib/api/executiveContracts.ts` (typy, `useContractStructure`,
  `useExecutiveContractOptions` → grupy `<optgroup>` per część, `frameworkPartHeader`
  „Cz. II — CeZ/145/2025"); profil: `ContractStructureSection` (+ `AddExecutiveContractModal`,
  `ExecutiveContractReviewPanel`, `ExecutiveContractFilter` — pill „Nieprzypisani (n)",
  części bez umów widoczne i nieklikalne); cztery dialogi zamówień i `OrderGroupFormModal`
  mają select umowy wykonawczej zamiast części. Harness `/preview/ezdrowie-contract-structure`.
- **Zamówienia MD (Faza B, WSZYSCY klienci):** `client_orders.md_optional_total` =
  zakres OPCJONALNY (NULL = „brak opcji w umowie"); `md_total` = podstawowy;
  `md_remaining = podstawa + opcja − zejścia + korekta` (`line_budget_total`);
  zużycie wypełnia najpierw podstawę (`split_md_usage` → `md_base_used`/`md_optional_used`).
  `client_order_md_consumptions.status` (`protocol` = „Protokół", `accepted` =
  „Zaakceptowany", NULL = z importu) + `note`; oba statusy liczą się do zużycia.
  Ręczne wpisy per osoba: `GET/PUT/DELETE …/order-groups/{g}/lines/{l}/consumptions[/{RRRR-MM}]`
  (zapis = role cyklu życia zamówienia; linia kosztowa / wspólna pula → 422; import
  XLSX nadpisujący ręczny wpis zeruje status). `replaces_order_id` przy dodaniu linii
  USTAWIA `predecessor_order_id` (poprzednik nie jest zamykany) → poprzednik dostaje
  `replaced_by_*` (tag „Zastąpiony → następca"). **Sumy grupy — reguła pozycji:**
  `md_positions_total`/`contract_value_pln` pomijają linie, na które wskazuje
  `predecessor_order_id` innej linii — ale ZALEŻNIE od rodzaju (`replaced_by_kind`
  z dziennika: `replacement` = zastępstwo przez `replaces_order_id`, następca ma własny
  budżet → poprzednik wnosi tylko zużycie; `swap` = zamiana kontraktora, następca
  przejął POZOSTAŁOŚĆ → poprzednik wnosi swoje zużycie jako część pozycji, inaczej
  „wykorzystano" przekraczałoby wartość umowy); linie `cancelled` nie są pozycjami.
  Zamiana z opcją dzieli POZOSTAŁOŚĆ (z korektą ręczną) na opcję i podstawę bez
  wartości ujemnych; offboarding (`_reduce_legacy_md_budget`) zdejmuje pulę najpierw
  z opcji. Kwoty tylko z finansami. **UI „zakresów" (paski Podstawa/Opcja, nagłówek
  „Wykorzystano wartości umowy", pole „Zakres opcjonalny") renderuje się WYŁĄCZNIE dla
  karty z `executive_contract` / klienta CeZ** — BIK/Polkomtel/BNP widzą dotychczasowy
  pasek „pozostało / całość". `MdScopeBars`, `LineConsumptionTable`
  (zakładka „Zużycie MD" panelu osoby). Harness `/preview/order-md-scopes`.
- **Import danych startowych (Faza C):** `POST /api/admin/clients/{id}/ezdrowie-md-orders/import?dry_run=`
  (admin, tylko CeZ) z manifestem JSON (`app/schemas/ezdrowie_md_seed.py`) —
  **manifest żyje poza repo** (nazwiska, stawki). Serwis `app/services/ezdrowie_md_seed.py`:
  osoba po `contract_id` → `candidate_id` → nazwisku (dokładnie jedno trafienie, inaczej
  `ambiguous` z listą kandydatów do wskazania), `create_if_missing` zakłada kandydata
  i kontrakt (godzinowy, MD ÷ 8; `ended` dla poprzedników), grupa o istniejącym numerze =
  `already_exists` (idempotencja), linia jak w `_build_line`, poprzednik `completed`
  z eventem `zakonczenie_konsultanta` `reason=seed_history` (NIE `removed_from_order`),
  szkice z `supersede_order_ids` ANULOWANE (tylko draft bez pliku poza grupą).
  Historia miesięczna wchodzi w DRUGIM przejściu (po utworzeniu następców), a status
  linii zakończonej jest po przeliczeniu przywracany jawnie — inaczej `sync_md_line_status`
  wskrzeszał poprzednika z datą końca „dziś"; linia zakończona ma `skip_sync_for_contract`
  (nie przepisuje kontraktowi stawki z historycznej linii). Dry-run idzie tą samą ścieżką
  i kończy rollbackiem; apply z blokerem = 409 i zero zapisu; paragon
  `app_settings['ezdrowie_md_seed_<sha12>']` = tylko liczniki i ID (ten sam manifest
  ponownie = dopisek `reapplied_at`, nie duplikat klucza).
- **Round-trip migracji 0312 z klientem 115**: downgrade zostawia zasiane umowy ramowe,
  więc zasiew ADOPTUJE wiersz po `(source_system, source_key)` zamiast wstawiać drugi.
  Guard zakończenia umowy wykonawczej liczy także żywe karty MD; przypisanie z ekranu
  przeglądu na osobie, której reprezentatywne zamówienie jest linią karty → 409 (linia
  dziedziczy umowę z karty). PATCH zamówienia z NIEZMIENIONĄ umową nie waliduje jej
  (umowa mogła zostać zakończona po przypisaniu); sama część bez umowy → 422.
