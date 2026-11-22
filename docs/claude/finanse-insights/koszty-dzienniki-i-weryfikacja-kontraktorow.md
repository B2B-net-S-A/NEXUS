# Koszty: dzienniki jak w eBI24 i wstępna weryfikacja kontraktorów (22.11.2026)

Prośba głównej księgowej z 18.11.2026, decyzje Artura z 22.11.2026. Uzupełnia
`ksiegowosc-koszty-i-kontrahenci.md` (kolejka E1, dekret E2) — tamte reguły
obowiązują dalej.

## Dzienniki

- eBI24 trzymało faktury w folderach-dziennikach: „Przychody”, „Kontraktorzy”,
  „Zakupy pozostałe”, „BENEFITY”, „BIURO”. Artur wybrał **cztery** dzienniki
  (przychody, kontraktorzy, zakupy pozostałe, biuro). Przychody są
  w Księgowość → „Źródła”, więc kolejka „Koszty” ma trzy.
- **Dziennik nie jest zapisany — wynika z kategorii wpisu**
  (`services/finance_ledger/journals.py`, `CATEGORY_JOURNAL`):
  - Kontraktorzy ← Kontraktorzy, Zespół (osoby na B2B; w eBI24 ten sam folder),
  - Zakupy pozostałe ← Benefity, Proforma, Inne (osobnego dziennika benefitów
    nie ma — Artur wybrał cztery),
  - Biuro ← Biuro.
  Zmiana kategorii przenosi fakturę do innego dziennika; reguła dekretu
  (wybierana po kategorii) zostaje spójna z dziennikiem. Mapowanie
  „Zespół → Kontraktorzy” i „Benefity → Zakupy pozostałe” jest do potwierdzenia
  z księgową na teście po 25.11 — zmienia się jedną linią w `CATEGORY_JOURNAL`.
- Kolejka: zakładki „Wszystkie · Kontraktorzy · Zakupy pozostałe · Biuro” nad
  etapami (`?costJournal=`), liczniki dzienników dla bieżącego etapu, filtr
  `GET /api/finance/costs?journal=` (inna wartość = 422).
- **Eksport** („Księgowanie”): podgląd podaje dziennik każdej faktury i sumy
  per dziennik (`journals`), plik ma kolumnę „Dziennik” (druga, po „Rejestr”),
  kolejność wierszy rejestr → dziennik → data. „Pobierz plik” może założyć
  paczkę jednego dziennika (`POST /batches` z `journal`, nazwa pliku
  `symfonia-RRRR-MM-<dziennik>-n`); faktury innych dzienników zostają na liście.
  Numeracja paczek zostaje jedna na miesiąc.

## Kategoria dokumentu wydatku z historii sprzedawcy

- Faktura osoby zespołu i kontraktora klienta mają kategorię ze źródła.
  Dokument wydatku dostawał „Biuro” z góry, a na kopii produkcji z 19.11.2026
  3 229 z 4 849 takich dokumentów eBI24 trzymało w „Kontraktorach”, tylko 216
  w „BIURZE”. Folder w eBI24 zależał wyłącznie od sprzedawcy (710 sprzedawców,
  żaden w dwóch folderach).
- `journals.suggest_categories` (woła go `costs.catch_up` na końcu każdego
  przebiegu KSeF — nie po każdej fakturze, bo zapytanie archiwum kosztuje
  ok. 0,3 s) podpowiada
  kategorię dokumentu wydatku: najpierw **ręczna** zmiana kategorii innej
  faktury tego samego sprzedawcy w NEXUSIE (ostatnia), potem folder jego
  ostatniej faktury kosztowej w archiwum eBI24 (`finance_archive_documents`,
  NIP z `meta._partner.officialId`). Ręczna decyzja Finansów u sprzedawcy
  wygrywa z eBI24, także gdy zostawiła kategorię domyślną.
- Podpowiedź dotyczy tylko wpisów nietkniętych: poczekalnia albo „Do opisu”,
  bez dekretu, bez paczki, bez wcześniejszej zmiany kategorii. Zostaje
  w historii jako zmiana kategorii bez osoby, z `source` (`history` / `ebi24`)
  i folderem; karta pokazuje autora „NEXUS — …”. Kolejny przebieg wpisu już
  nie rusza. Na kopii z 19.11: 4 544 zmiany w 0,3 s.

## Wstępna weryfikacja kontraktorów i akceptacja księgowej

- Lista **„Weryfikujący kontraktorów”** (`app_settings['ledger'].cost_verifiers`,
  Księgowość → Ustawienia, `PUT /api/accounting/config/cost-verifiers`)
  ustawia administrator, na tych samych zasadach co „Księgowi”: aktywne konta
  z „Modułem Finanse”, najwyżej 20. Nazwisk nie ma w kodzie.
- **Kroki z listy** (`costs.stage_refusal`, 403 z powodem; zbiorczo odmowy
  w `refused`):
  - „Zweryfikuj” fakturę z dziennika „Kontraktorzy” i cofnięcie jej
    z „Zweryfikowanych” — lista „Weryfikujący kontraktorów”, „Księgowi” albo
    admin. W innych dziennikach weryfikuje każdy z „Modułem Finanse”.
  - „Gotowa do księgowania” i cofnięcie z „Gotowej” — **tylko „Księgowi”**
    (i admin), w każdym dzienniku. Na start na liście jest sama księgowa.
  - Wyjęcie faktury z „Kontraktorów” zmianą kategorii (w każdym etapie)
    i wstawienie tam faktury już zweryfikowanej wymaga tej samej listy co
    weryfikacja — inaczej zmiana kategorii i „Zweryfikuj” omijałyby krok
    (przegląd kodu 22.11.2026).
  - Przyjęcie z poczekalni, odrzucenie i cofnięcie do poczekalni — bez list.
- Lista i karta dostają `can` (`verify`, `ready`), przyciski bez prawa są
  wyłączone z podpowiedzią; serwer i tak odmawia.
- **Zgodność z rozliczeniem miesiąca** (`finance_ledger/settlement_match.py`):
  faktura kontraktora klienta → rozliczenie osoby za `period_month` (rodzaj
  `actual`). Porównujemy tylko fakturę przypiętą do kontraktu (`known`,
  `confirmed`): z NIP-em odrzuconym = „NIP odrzucony — faktura nie należy do
  kontraktu”, z NIP-em do zatwierdzenia = „NIP do zatwierdzenia” —
  `reject_nip` zostawia `contract_id`, a stan miesiąca liczą inne, przypięte
  faktury, więc bez tego obca faktura dostałaby „zgodną”. Nic nie liczymy od nowa: stan i kontrole to
  `client_settlements/contractor_invoices.state` i `.card` (kwota równa
  wyliczeniu z RCP z tolerancją `ci.amount`, korekty z tego miesiąca razem,
  NIP nabywcy, biała lista, termin), zapłata — `service.payment` (ta sama
  bramka co plan przelewów). Stany: zgodna, inna kwota, RCP nieprzyjęte (bez
  kwoty), reguła kwoty wyłączona, NIP do zatwierdzenia, brak rozliczenia
  w NEXUSIE, bez kontraktu i miesiąca (np. dokument wydatku przeniesiony do
  „Kontraktorów” — porównanie ręczne). Kolejka pokazuje plakietkę pod „Kogo
  dotyczy”, karta panel „Rozliczenie miesiąca MM.RRRR” z kontrolami i linkiem
  do „Faktury i rozliczenie” klienta. Faktury osób zespołu pomijamy — ich
  rozliczenie to Płace („Kogo dotyczy”).
