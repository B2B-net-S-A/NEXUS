# Kody osób klienta z faktur KSeF — uzupełnienie kartoteki (25.11.2026)

<!-- indeks: client_external_ids, client_person_no, backfill_client_person_numbers_from_ksef, „NEXUS nie zna kodu”, fill_from_ksef, Nordea Contractor ID, podpowiedzi kartoteki raportu godzin -->

Kontrola formalna faktury sprzedaży (`cl.contractor_person_id`,
`kontrola-formalna-faktury-sprzedazy.md`) ostrzega „NEXUS nie zna kodu …”,
gdy pozycja „Contractor <osoba> ID: <kod>” nazywa osobę z kontraktem, a kodu
nie ma w `client_external_ids`. Automat `time_reports.fill_from_ksef` bierze
kody tylko z faktur przypiętych do linii zamówienia osoby, więc faktury bez
przypięcia zostawiały luki (u Nordei 132 faktury IV–XI 2026).

## Skrypt

`python -m scripts.backfill_client_person_numbers_from_ksef --client-id <id>`
(domyślnie dry-run w transakcji `READ ONLY`, `--apply` zapisuje, `--review
<plik.csv>` daje listę z nazwiskami do przeglądu — plik poza repo). Wyjście to
same liczby i id nowych wierszy.

Para (kontrakt, kod) wchodzi tylko, gdy:

- nazwisko z faktur pasuje (`unknown_refs.same_person`) do dokładnie jednej
  osoby z kontraktem u klienta; osoba z „Contact:” wpisana jako „Contractor”
  się nie liczy,
- kodu nie ma w kartotece klienta u nikogo (w żadnym stanie),
- osoba nie ma innego kodu ani w kartotece, ani na fakturach,
- osoba ma jeden kontrakt albo dokładnie jeden obejmuje okres tych faktur.

## Decyzja Artura (25.11.2026): podpowiedzi, nie potwierdzenia

- Wpis to `source=ksef_item`, `state=suggested`, okres z miesięcy faktur.
  Finanse zatwierdzają albo odrzucają kod w kartotece raportu godzin
  (Rozliczenia → Raport godzin → podpowiedzi). Do dopasowania raportu godzin
  kod wchodzi dopiero po zatwierdzeniu; `fill_from_ksef` potwierdza go sam,
  gdy pojawi się na fakturze przypiętej do zamówienia tej osoby.
- Uwaga w kontroli faktury znika od razu po zapisie podpowiedzi.
- Produkcja 25.11.2026: 30 par zapisanych, uwagi „NEXUS nie zna kodu” w IV–XI
  ze 132 do 15 faktur (październik z 26 do 2). Zostały: osoby z kilkoma kodami
  i nazwisko pasujące do kilku osób — te Finanse dopisują ręcznie.
- Ponowne uruchomienie jest bezpieczne: kod już w kartotece jest pomijany.
