# Finanse → Rozliczenia: dodatki do rozliczenia kontraktora (polecenie, weryfikacja, szkolenie, delegacja)
<!-- indeks: tabela client_settlement_extras (0690 + 0691), jeden model kosztów dodatkowych z integracją BNP, zgłoszenie z karty sprawy, Finanse zatwierdzają, panel: delegacja z dokumentem, ci.amount = wyliczenie + zatwierdzone dodatki, extra_pending, cl.extra_costs_on_invoice -->

Potrzeba Finansów z 13.11.2026, decyzja Artura „robimy teraz”. Kontraktor dolicza do
faktury kwoty spoza godzin: premię za polecenie, weryfikację techniczną (zleca ją
rekruter), szkolenie, delegację. Dotąd Finanse dopisywały je ręcznie do pliku
rozliczeniowego i dopytywały o dokumenty delegacji.

## Model

- Jedna tabela `client_settlement_extras` na (kontrakt, miesiąc): rodzaj (`referral`,
  `tech_check`, `training`, `travel`, `integration`, `other`), kwota netto, opis, źródło
  (`back_office`, `finance`, `portal`), kto zgłosił, stan (`pending` zgłoszony,
  `approved`, `rejected` z powodem), `bill_to_client`. Pliki w
  `client_settlement_extra_documents` przez `documents_store` (PDF, DOCX, JPG, PNG).
- Koszty integracji BNP (`cl.integration_costs`, zgoda DL-a, limit na rok) to ten sam
  model z rodzajem `integration`. Nie zakładaj drugiej tabeli kosztów. Finanse nie
  zatwierdzają integracji (403), a integracja nie liczy się do kwoty faktury
  kontraktora: obniża marżę po swojej stronie.
- Kod: `services/client_settlements/extras.py`, karta sprawy
  `services/back_office/settlement_extras.py`.

## Kto co robi

- **Back office** z karty sprawy (`source_kind = case`): „Dodaj dodatek do rozliczenia”
  z polami kto (kontrakt z karty albo wyszukany), okres, kwota. Dodatek jest
  „zgłoszony” i czeka na Finanse. Kwotę na karcie widzi wpisujący i osoby z kwotami
  back office'u (Płace, admin), w historii karty kwoty nie ma.
- **Finanse** na karcie osoby w Finanse → Rozliczenia: zatwierdzają, odrzucają
  (zawsze z powodem), zaznaczają „Na fakturę dla klienta”, dołączają pliki, a dodatek
  wpisany przez siebie mają od razu zatwierdzony.
- **KEŚU (Alior):** „Suma kosztów dodatkowych” z KEŚU tworzy jedno zgłoszenie na
  (kontrakt, miesiąc): delegacja „na fakturę dla klienta”, źródło `kesu`, netto =
  brutto / 1,23. Nowy odczyt KEŚU poprawia kwotę tylko przed decyzją Finansów
  (`extras.sync_from_kesu`). Drugiej ścieżki kosztów KEŚU w fakturze dla klienta nie ma.
- **Konsultant** w panelu widzi swoje dodatki ze stanem i powodem odrzucenia (bez
  źródła i bez informacji, czy fakturujemy klientowi) i sam zgłasza delegację; bez
  dokumentu panel jej nie przyjmie.

## Wyliczenie

- Oczekiwana kwota faktury kontraktora = `amount_cost` z RCP + zatwierdzone dodatki
  miesiąca (`contractor_invoices.expected`). Ta sama suma rozstrzyga miesiąc faktury
  przy dopasowaniu z KSeF.
- Różnica równa zgłoszonemu, a niezatwierdzonemu dodatkowi (jednemu albo wszystkim
  razem) to stan `extra_pending` i uwaga „Czeka na zatwierdzenie dodatku”, nigdy błąd,
  także przy `ci.amount` „Blokuje”. Koszty dodatkowe potwierdza rozliczający
  (`travel.extra_costs_confirm`), dlatego nic nie odrzuca się samo.
- W danych do faktury w panelu zatwierdzony dodatek to osobna pozycja, a „Kwota netto”
  zawiera usługi i dodatki.
- Faktura dla klienta: zatwierdzony dodatek z `bill_to_client` według
  `cl.extra_costs_on_invoice` (parametr `item` pusty = doliczony do pozycji zasadniczej
  bez ceny jednostkowej, nazwa = osobna pozycja). Reguła wyłączona albo linia w innej
  walucie niż zł = brak pozycji i uwaga w wierszu. Wszystkie zatwierdzone dodatki
  (poza integracją) są kosztem miesiąca w marży.
