# Rabat od obrotu liczony od pełnej kwoty; marża per konsultant (16.11.2026)
<!-- indeks: rabat po przekroczeniu progu = stawka wyższego progu × CAŁY obrót (nie nadwyżka); „Progowo” tylko gdy umowa wprost liczy od nadwyżki; inne waluty kursem NBP z dnia przed wystawieniem; marża per konsultant = generator margin_per_consultant, wzór Cost z modelu H1 -->

Polecenie Artura z 16.11.2026: rabat Nordei liczy się od **pełnej kwoty**
obrotu. Gdy roczny obrót przekroczy próg, stawka tego progu dotyczy całego
obrotu, a nie tylko części ponad progiem.

- **`compute_rebate(..., marginal=False)` to tryb domyślny** i jedyny, którego
  używa raport marży (`generators/margin_per_consultant.py` nie ma parametru
  „Progowo”). Obrót tuż nad progiem = stawka wyższego progu × cały obrót
  (test `test_turnover_just_above_threshold_takes_higher_rate_on_whole_turnover`).
  W „Rabacie od obrotu” (`annual_spend`) opcja „Progowo” zostaje dla umów,
  które wprost liczą rabat od nadwyżki — dla Nordei jej nie włączaj. Nie
  dokładaj `if client == …`, żeby to wymusić: różnice między klientami to
  `params` definicji (zasada katalogu, `katalog-raportow-klienta.md`).
- **Progi w innej walucie niż faktury** (Nordea: progi w EUR, faktury w PLN):
  obrót przeliczamy kursem średnim NBP z dnia poprzedzającego wystawienie
  faktury (`annual_spend.convert_turnover`, kursy z `fx_rates`; decyzja Artura
  16.11.2026). Faktura bez kursu wypada z obrotu i trafia do kontroli — nigdy
  1:1. Podgląd mówi, ile faktur przeliczono.
- **Obrót roku bywa niepełny:** pobieranie z KSeF cofało się 3 miesiące, więc
  faktury klienta mogą zaczynać się w połowie roku. Raport mówi to w kontroli
  i podaje tempo roczne z dni pokrytych fakturami (jaka byłaby stawka od
  całości), ale stawkę bierze z faktycznego obrotu — nie zgadujemy kwot.
- **Marża per konsultant** (`margin_per_consultant`, Governance — raport
  kwartalny albo na żądanie klienta): skład = kontrakty aktywne w dniu
  generowania, stawki z harmonogramów na ten dzień (`effective_rate_fields`),
  jedna osoba raz (najnowszy kontrakt).
  `Cost = ZAOKR(K + koszty/godziny + udział × MAX(0; D − K − koszty/godziny); 0)`,
  `E = D × (1 − rabat)`, marża `(E − Cost) / E`, portfel `(ΣE − ΣCost) / ΣE`
  (per głowa, bez ważenia godzinami). Domyślnie 648 zł / 168 h / 50% —
  parametry definicji. Zaokrąglenie jak w Excelu (połówka w górę).
- **Stawka konsultanta w NEXUSIE jest źródłem prawdy.** Gdy dawny Excel klienta
  ma inny Cost, poprawia się stawkę kontraktu, nie raport (decyzja Artura
  16.11.2026). Plik dla klienta nie ma stawki konsultanta ani rozbicia kosztu;
  marża wewnętrzna zostaje w Profilu klienta → Konsultanci.
- Kontrakty nie godzinowe, nie w PLN albo bez stawki są poza raportem (licznik
  w kontroli). Osoba bez kategorii z umowy ramowej — kontrola „uzupełnij
  w stawkach ramowych”.
- Bramki: `needs_amounts` i `needs_client_rate` (plik ma stawki do klienta).
  Podgląd w oknie pobrania pokazuje pierwsze wiersze arkusza wskazanego przez
  `Generator.preview_sheet`.
