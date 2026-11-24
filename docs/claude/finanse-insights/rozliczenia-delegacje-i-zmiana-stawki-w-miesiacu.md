# Rozliczenia: akceptacja kosztów delegacji i koszt z dwóch stawek w miesiącu
<!-- indeks: travel.rcp_costs zdejmuje akceptacja klienta (RCP podpisany certyfikatem z domeny klienta albo mail z kwotą lub pozycjami jak w RCP), travel_acceptance.py, rate_split.py, Stawka kontraktora: podział kosztu według godzin z RCP dzień po dniu, pierwszy krok i ta sama stawka to nie zmiana, przychód bez podziału -->

Próba rozliczeń IX–X 2026 (powtórka 7). Dwie luki trzymały u człowieka
rozliczenia z MD zgodnymi z fakturą Finansów.

## Koszty delegacji (`travel.rcp_costs`)

RCP z kosztami delegacji zawsze dawał uwagę „Delegacja do sprawdzenia”.
W obu przypadkach z próby klient te koszty zaakceptował, a Finanse fakturowały
dokładnie kwotę z RCP jako osobną pozycję faktury.

- **Uwagę zdejmuje akceptacja klienta** (`services/client_settlements/travel_acceptance.py`,
  `service._travel_acceptance`). Liczy się jedna z dwóch postaci:
  - **RCP podpisany przez klienta.** Szablon BNP ma wiersz „Koszty wyjazdu” w tym
    samym pliku, który przełożony podpisuje elektronicznie („dane wpisane
    w dokumencie traktujemy jako podstawę do rozliczenia faktury”). Podpis musi
    być ważny i obejmować cały plik. Certyfikat musi mieć adres w domenie klienta
    (`acceptance_senders`), a wystawca musi pasować do reguły `proof.signed_pdf`.
    Podpisującym nie może być sam konsultant (porównanie imienia i nazwiska).
  - **Mail klienta.** Odpowiedź ze słowem akceptacji („Potwierdzam”,
    „Akceptuję”) z domeny klienta, w wątku o wyjeździe. W wątku musi być kwota
    z RCP albo kwoty wszystkich niezerowych pozycji z RCP (pociąg, hotel, …).
    Mail szukamy w `.eml`/`.msg` i w wydruku PDF w plikach miesiąca każdego rodzaju,
    bo wydruk akceptacji przychodzi z fakturami kosztowymi i czytnik poczty
    zapisuje go jako fakturę.
- **Uwaga zostaje:**
  - bez akceptacji;
  - przy akceptacji z innej domeny albo od samego konsultanta;
  - przy innej kwocie. Szacowany koszt pociągu („około … zł”) niższy niż
    w RCP też jest inną kwotą. W opisie uwagi stoi, co klient zaakceptował.
- Kwoty bierzemy z walutą (zł, PLN). Kwotę od miliona pomijamy, bo to kapitał
  zakładowy ze stopki banku.
- Pozycji delegacji na fakturze klienta to nie dodaje. „Do faktury” to dalej
  usługi, a dodatek do faktury robi `client_settlement_extras`
  (`dodatki-do-rozliczenia-kontraktora.md`).

## Zmiana stawki kontraktora w trakcie miesiąca (grupa „Stawka kontraktora”)

Harmonogram kontraktu (`contract_candidate_rates`) zmienił stawkę Partnera
w środku miesiąca, a linia zamówienia ma jedną stawkę kosztu. Kontraktor
fakturuje dni przed zmianą starą stawką, a od zmiany nową. Faktura kontraktora
w próbie była równa podziałowi co do złotówki.

- **Stawka w dniu** liczy się jak `Contract.effective_candidate_rate`:
  - ostatni krok nie późniejszy niż ten dzień;
  - przed pierwszym krokiem stawka pierwszego kroku.

  Dlatego dwa rodzaje kroków nie są zmianą i nie dają uwagi:
  - pierwszy krok w środku miesiąca, np. krok z dnia startu kontraktu (dawniej
    „Zmiana stawki DD.MM: ? → X”);
  - krok z tą samą stawką (dawniej „125 → 125”).

  Zmiana od 1. dnia miesiąca to jedna stawka na cały miesiąc.
- **Prawdziwa zmiana:** MD dzielimy według godzin z RCP dzień po dniu
  (`ProofResult.day_hours`, dziś RCP BNP z 31 kolumnami; w krótszym miesiącu
  ostatnie kolumny są pomijane). Koszt części = MD części × stawka części w zł/MD
  (przeliczenie jednostek jak zamówienie, 1 MD = 8 h). Reszta z zaokrąglenia MD
  idzie na ostatnią część. Silnik daje osobną linię „Dni zwykłe DD.MM–DD.MM” na
  każdą stawkę (`Inputs.cost_parts`). MD ponad pulę idą stawką ostatniej części,
  bo pula kończy się na ostatnich dniach. Kod: `services/client_settlements/rate_split.py`,
  `service._rate_change_checks`.
- **Uwaga zostaje tylko wtedy, gdy podziału nie da się policzyć.** W opisie stoi
  powód:
  - dowód bez godzin dzień po dniu (np. MD wpisane przez Finanse);
  - godziny nie dają MD rozliczenia;
  - praca dodatkowa;
  - podział na zamówienia z maila;
  - stawka kontraktu nie w zł;
  - linia zamówienia ze stawką, której nie ma w harmonogramie w tym miesiącu.
- **Przychód się nie dzieli.** Stawka klienta liczy się stawką z pierwszego dnia
  miesiąca (`order_revenue_steps`, decyzja Artura z 16.11.2026). W IX–X 2026 żadna
  faktura sprzedaży nie miała dwóch stawek w miesiącu.

## Pomiar (klon kopii produkcji z nocy 23/24.11, przeliczenie IX–X w transakcji z ROLLBACK)

Na 369 rozliczeń zmieniły się dokładnie 4:
- dwie delegacje przeszły na `ok` podpisem klienta na RCP;
- jedno rozliczenie z kosztem z dwóch stawek: koszt równy fakturze kontraktora;
- z jednego zeszła fałszywa uwaga o zmianie stawki przy starcie kontraktu.

Żadne inne rozliczenie nie zmieniło kwoty ani uwag.

Testy: `test_client_settlements_travel_acceptance.py`, `test_client_settlements_rate_split.py`
(bez bazy), `test_client_settlements_rate_change_db.py`.
