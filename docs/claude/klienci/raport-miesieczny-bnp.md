# Raport miesięczny BNP na karcie klienta (09.11.2026)
<!-- indeks: Projekty → „Raport miesięczny BNP”, dwa arkusze szablonu banku, stawki za MD, „# CV zgodna stawka” z budżetu, „Klient wybrał kogoś innego” to nie odrzucenie, widełki z umowy do `rate_cards` -->

Zgłoszenie Delivery Leada: co miesiąc ręcznie wypełniany plik do BNP. Reguły kolumn
pochodzą z pliku porównanego przez Delivery Leada 09.11.2026 z danymi z NEXUSA, więc
nie zmieniaj ich „dla porządku”. Kod: `services/bnp_report/`, `api/bnp_report.py`.

- **Zakres:** rekrutacje klienta otwarte w miesiącu (`opened_at`, bez niej `created_at`),
  bez szkiców. Stan na dzień pobrania, więc wysyłki z kolejnego miesiąca się liczą.
- **START** można poprawić w oknie. Zapis idzie do `opened_at`, bo NEXUS bywa o dzień
  czy dwa późniejszy niż zapytanie banku. Od START liczy się SLA: 10 dni roboczych.
- **„# CV”** to osoby, które doszły do „CV wysłane” albo dalej, każda raz.
- **„# CV zgodna stawka”** porównuje stawkę KANDYDATA z górną granicą budżetu
  rekrutacji (`rate_budget_hourly`). Nie widełki z umowy: Delivery Lead liczy tak ten
  arkusz i wysyłka ponad widełkami też bywa zgodna z budżetem.
- **„Stawka min/max z oferty”** to najniższa i najwyższa stawka DO KLIENTA wszystkich
  wysłanych, nie tylko osób z ofertą. „# Ofert” to akceptacja klienta albo dalej.
- **Kwoty w pliku są za MD** (zł/h × 8), widełki też. „Średnia z rekomendacji” to
  środek min i max, nie średnia osób. Rozbieżność = (średnia − średnia z umowy) / średnia
  z umowy. Różnica = stawka min − górna granica.
- **Odrzucenia:** tylko wysłane osoby z `ended_by='client'`. Powody z `CLIENT_NOT_A_VERDICT`
  („Klient wybrał kogoś innego”, zamknięty request, milczenie) to zamknięcie rekrutacji,
  nie ocena: na październiku dawały 7 fałszywych odrzuceń. Odrzucenie po spotkaniu
  liczy się osobno i nie wchodzi do „# odrzuconych CV”.
- **Widełki z umowy:** tabela leży w umowie klienta, nie w repozytorium (repo jest
  publiczne). `rate_annex.py` czyta ją z fragmentów tekstu umowy jako propozycję;
  po sprawdzeniu zapis do `rate_cards` (zł/h). Rola z umowy przy rekrutacji:
  `jobs.client_rate_card_id` (0675); bez zapisu rola jest propozycją z nazwy.
- **Dostęp:** kto widzi stawkę do klienta (`user_can_view_client_rate`) i klienta
  w zakresie Delivery. Zapisy: uprawnienie „Rekrutacje”, także widełek, bo sprawdza je
  Delivery Lead (reszta kart stawek zostaje przy Finansach; rola zapisana w innej
  jednostce niż zł/h kończy się 409). Plik idzie do banku, więc
  stawki kandydata nigdy nie ma w arkuszu, mimo że liczy z niej kolumnę zgodności.
