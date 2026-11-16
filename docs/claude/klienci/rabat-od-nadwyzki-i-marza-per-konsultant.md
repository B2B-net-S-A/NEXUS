# Rabat od obrotu Nordei progowo, od nadwyżki; marża per konsultant (16.11.2026)
<!-- indeks: rabat Nordei = obrót roku do progu × niższa stawka + nadwyżka × wyższa (Appendix 6), „Progowo” domyślnie włączone w obu generatorach; inne waluty kursem NBP z dnia przed wystawieniem; marża per konsultant = generator margin_per_consultant, wzór Cost z modelu H1 -->

Decyzja Artura z 16.11.2026 po lekturze umowy ramowej Nordei (Appendix 6
„Charges” z 01.03.2026, sekcja o rabacie od obrotu; dokument jest w module
umów klienta, treści nie cytujemy w repo): rabat liczy się **progowo, od
nadwyżki** — obrót roku kalendarzowego (1.01–31.12) do progu po niższej
stawce, część powyżej progu po wyższej. Rano tego dnia padło polecenie
„od pełnej kwoty”; po przeczytaniu umowy Artur je cofnął. Nie wracaj do
trybu „od całości” dla Nordei bez nowej decyzji.

- **„Progowo” (`marginal=True`) jest domyślne** w „Rabacie od obrotu”
  (`annual_spend`) i w raporcie marży (`margin_per_consultant`). Obrót tuż nad
  progiem = próg × niższa stawka + nadwyżka × wyższa stawka (test
  `test_turnover_just_above_threshold_higher_rate_only_on_excess`). Raport
  marży bierze stawkę efektywną roku (średnia ważona). Tryb „od całości”
  zostaje jako opcja definicji dla umów, które wprost tak mówią. Nie
  dokładaj `if client == …`: różnice między klientami to `params` definicji
  (zasada katalogu, `katalog-raportow-klienta.md`).
- **Z obrotu wyłączone są podróże i faktury nieusługowe** (refaktury). NEXUS
  ich nie rozpoznaje — raport mówi to w kontroli, DL wyłącza je ręcznie.
- Rabat rozlicza się raz w roku notą kredytową do końca stycznia; faktury
  w ciągu roku idą bez rabatu (wystawianie faktur: osobna sprawa w
  `client_invoicing`).
- **Progi w innej walucie niż faktury** (Nordea: progi w EUR, faktury w PLN):
  obrót przeliczamy kursem średnim NBP z dnia poprzedzającego wystawienie
  faktury (`annual_spend.convert_turnover`, kursy z `fx_rates`; decyzja Artura
  16.11.2026). Faktura bez kursu wypada z obrotu i trafia do kontroli — nigdy
  1:1. Podgląd mówi, ile faktur przeliczono.
- **Obrót roku bywa niepełny:** pobieranie z KSeF cofało się 3 miesiące, więc
  faktury klienta mogą zaczynać się w połowie roku. Raport mówi to w kontroli
  i podaje tempo roczne z dni pokrytych fakturami (jaka byłaby stawka
  efektywna roku), ale stawkę bierze z faktycznego obrotu — nie zgadujemy kwot.
- **Marża per konsultant** (`margin_per_consultant`, Governance — raport
  kwartalny albo na żądanie klienta): skład = kontrakty aktywne w dniu
  generowania, stawki z harmonogramów na ten dzień (`effective_rate_fields`),
  jedna osoba raz (najnowszy kontrakt).
  `Cost = ZAOKR(K + koszty/godziny + udział × MAX(0; D − K − koszty/godziny); 0)`,
  `E = D × (1 − stawka efektywna roku)`, marża `(E − Cost) / E`, portfel `(ΣE − ΣCost) / ΣE`
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
