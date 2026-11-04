# Zakładka „Zakończeni" — decyduje umowa, nie okres zamówienia

Zgłoszenie (VeloBank, 09.2026): 11 osób miało to samo zamówienie do 31.08,
a po jego upływie do „Zakończonych" trafiły dokładnie te 4, którym umowa
miała wpisaną datę końca 30.06 — przepisaną przy zakładaniu kontraktu
z pierwszego okresu zamówienia, bez wypowiedzenia. Reszta (umowy
bezterminowe) została w „Aktywnych". Jedna reguła w trzech miejscach:

- **Zakładka czyta WYŁĄCZNIE umowę** (`contractClosed` w
  `lib/client-order-list.ts`, jedyne źródło pigułek dla obu rejestrów):
  „Zakończeni" = status końcowy ORAZ `contract_end_date < dziś`. Do daty
  końca włącznie osoba jest w „Aktywnych", od następnego dnia przechodzi
  sama (nocny cron `contract_alerts._promote_statuses`). Upływ okresu
  zamówienia nie przenosi nikogo — osoba zostaje w „Aktywnych" z dopiskiem
  **„Brak aktywnego zamówienia"** (`lacksCurrentOrder`: żadne zamówienie
  nie obejmuje dziś ani nie zaczyna się później).
- **Data końca umowy rządzi zamówieniem, nie odwrotnie.** PATCH daty końca
  w Kontraktach (`update_contract`) woła `_sync_client_orders_to_contract_end`
  (ten sam co `/terminate`): otwarte zamówienia dostają tę datę, zaczynające
  się później są anulowane, `completed` dopiero gdy dzień nadejdzie. Wyłącznie
  SKRACANIE — zamówienie to PO klienta, przedłużenie umowy go nie wydłuża;
  wyczyszczenie daty (bezterminowa) nie rusza zamówień.
  W drugą stronę zamówienie NIGDY nie ustawia daty końca umowy:
  `sync_contract_to_live_order` wskrzesza kontrakt jako bezterminowy.
- **Korekta danych (migracja `0274` + lustro w `entrypoint.sh`, SQL w
  `services/contract_ended_tab_repair.py`)**: wskazany w tickecie Contract 469
  (Piotr Klimczak, VeloBank) wraca na `active` po pełnych kluczach
  biznesowych; klasa „zakończona bez wypowiedzenia, a zamówienie trwało po
  dacie końca umowy" jest tylko AUDYTOWANA do `app_settings` — masowe
  wskrzeszenie wciągnęłoby do MRR osoby, które faktycznie odeszły
  (dwie z trzech u VeloBanku nie są na nowym zamówieniu).
