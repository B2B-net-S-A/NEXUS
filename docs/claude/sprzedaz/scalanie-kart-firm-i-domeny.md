# Scalanie zdublowanych kart firm i domeny: jednorazowy skrypt (B6) — decyzje Artura 10.11.2026
<!-- indeks: scripts/sales_company_merge.py, services/sales/merge.py, names_to_join, konta lejka atlas-it-factories i lista z researchu centrów IT, grupa = ta sama nazwa kanoniczna albo NIP, karta docelowa, „do decyzji”, karty tej samej marki (wariant nazwy, inna spółka), --decide, blokada dotyku szansy, nazwy dołączone po scaleniu (także z ekranu Firmy), punkty do rozmowy z bota po scaleniu, ten sam mail z Outlooka na dwóch kartach (outlook_duplicates, ux_sales_activities_outlook), domena z poczty kontaktów, konflikt domen, --accept-domain, --expect-merge, --expect-domains, lista poza repo, bieg na produkcji workflowem coolify-sales-company-merge.yml (dry-run → liczby → zgoda Artura → apply), filtr raportu sales_company_merge_report.py, limit 25 wejść workflow_dispatch -->


Kartoteka Sprzedaży po imporcie z Atlasa ma po kilka kart tej samej firmy, a karty
kont „Fabryk IT” nie mają domeny. Bez domeny nie działa dopasowanie poczty i kalendarza
z Outlooka (`outlook-handlowcow-w-sprzedazy.md`) ani punkty do rozmowy z bota
(`sygnaly-grok-bot.md`), a import listy osób z researchu musi przy każdej firmie pytać
o kartę. Rekomendacja B6: https://claude.ai/artifact/PEfTGijHaxrPDZS2mkxKty.

Ekran „Porządki” i scalanie zakładek Artur odrzucił, dlatego to jednorazowy skrypt:
`backend/scripts/sales_company_merge.py`, testy `backend/tests/test_sales_company_merge.py`.
Wzór biegu na sucho i liczników to `scripts/sales_cleanup.py`.

## Co pokazały dane (kopia produkcji z 10.11.2026)

- **Prawie nie ma duplikatów w ścisłym sensie.** Na 48 firm z kontem w lejku żadna nie
  ma drugiej karty o tej samej nazwie kanonicznej, a jedyna para ze wspólnym NIP-em to
  dwa różne banki (błąd wpisu). „Po 4–11 kart na firmę” z rekomendacji to karty tej
  samej marki o innych nazwach: spółki grupy, oddziały, zapis z formą prawną. Takich kart wokół
  kont lejka jest 60, z czego 17 różni się tylko końcówką („… Polska”, „… Group”,
  „… Bank Polska S.A.”).
- **Konto w lejku bywa pustą kartą.** Import zakładał kartę z nazwy szansy, a kontakty
  zostały na karcie spółki (np. 0 kontaktów na karcie konta i 161 na karcie banku
  w Polsce). Dlatego decyzja o kartach tej samej marki należy do człowieka, a skrypt
  podaje przy każdej liczniki i domeny poczty.
- Domeny: 2 z 48 kart mają ją wpisaną, dla 27 wynika jednoznacznie z adresów
  kontaktów, 16 nie ma z czego jej wziąć.

## Zakres i grupy

- **Zakres:** firmy z szansą w lejku `atlas-it-factories` (także zamkniętą i w archiwum),
  firmy z pliku z nazwami (`--names-file`, jedna nazwa w wierszu) i karty po id
  (`--company-ids`). Plik z nazwami nie trafia do repo. Na produkcji zamiast nazw idą id
  kart, bo komenda biegu jest w publicznym logu.
- **Grupa** to karty o tej samej nazwie kanonicznej (`normalize_company_name`) albo
  NIP-ie, czyli ta sama definicja duplikatu co na ekranie Firmy.
- **Karta docelowa:** powiązana z klientem NEXUSA, potem karta z kontem w lejku, potem
  z największą liczbą kontaktów, potem z największą historią (szanse, aktywności, pliki),
  na końcu najstarsza. Reguła jest jawna, żeby lista do przejrzenia nie zależała od
  kolejności wierszy.
- **Scalenie idzie wyłącznie przez `services/sales/merge.py`:** źródło trafia do
  archiwum z `merged_into`, szansa dostaje wpis `company_merged` w historii, nic nie jest
  kasowane. Nowa tabela z `company_id` musi trafić do `merge.py`, nie do skryptu.

## „Do decyzji” zamiast scalenia

- Grupa nie jest scalana sama, gdy ma różne NIP-y, karty dwóch różnych klientów NEXUSA,
  kartę matkę i córkę, wspólny NIP przy niepowiązanych nazwach albo różne domeny poczty
  na kartach o tej samej nazwie. Dwie spółki o tej samej nazwie istnieją naprawdę,
  a ostrzeżenie o duplikacie w NEXUSIE jest podpowiedzią, nie blokadą.
- **Karty tej samej marki** skrypt tylko wypisuje obok grupy: „wariant” (nazwa różni się
  końcówkami z `company_aliases.brand_of`) albo „inna spółka”. Nie scala żadnej z nich
  bez `--decide DOCELOWA:ŹRÓDŁO[,ŹRÓDŁO]` (same id). Decyzja przejmuje całą grupę: karty
  o tej samej nazwie trzeba w niej wymienić razem z wariantami (lista podaje gotowy
  zapis w `decide_variants`).
- Decyzja nie znosi blokad niżej.

## Kiedy grupa nie jest scalana mimo zgody

- **Dotyk otwartej szansy by się przesunął.** Aktywność firmy jest dotykiem jej szans
  (`touch.py`), więc po scaleniu szansa z karty A dostałaby świeżą aktywność karty B
  i zniknęła z „Do decyzji” oraz spod automatu archiwizacji. Skrypt liczy to przed
  zapisem i sprawdza jeszcze raz po nim; różnica wycofuje całą transakcję (kod 3).
- **Zgubiłaby się nazwa dołączona** w „Innych nazwach z CV”: `merge.py` przy tej samej
  nazwie zostawia decyzję karty docelowej, więc „Dołącz” ze źródła przegrałoby z „Nie ta
  firma” na docelowej.
- **Karty dwóch różnych klientów NEXUSA:** jedna firma sprzedaży ma jednego klienta
  (`ux_sales_companies_client`), drugie powiązanie zostałoby na karcie w archiwum.

## Nazwa wchłoniętej karty zostaje jako dołączona

„Kogo znamy” dopasowuje osoby dokładnie po nazwie kanonicznej. Bez dopisku osoby
z „Marka Group” w CV znikłyby z liczników po scaleniu tej karty w „Marka”. Scalenie
dopisuje więc nazwę (i nazwę prawną) wchłoniętej karty do `sales_company_aliases` jako
`joined`, gdy różni się od nazw docelowej i wolno ją doliczyć do firmy
(`company_aliases.can_be_alias`). Da się to cofnąć na karcie („Cofnij”).

Od 10.11.2026 robi to `merge.py` (`names_to_join`), więc scalenie z ekranu Firmy
i skrypt dają ten sam wynik. Do tego dnia nazwę dopisywał tylko skrypt i to samo
scalenie zależało od drogi. Skrypt liczy te nazwy w biegu na sucho tą samą funkcją
i po zapisie sprawdza, że są przy karcie docelowej.

- Nazwa idzie po decyzjach źródła i nie nadpisuje tego, co już jest przy docelowej:
  „Nie ta firma” przy nazwie wchłanianej karty zostaje. Z ekranu scalenie przechodzi
  wtedy bez dopisku, a skrypt takiej grupy nie scala (blokada wyżej).
- Pusta nazwa prawna docelowej dostaje nazwę prawną źródła (`FILLABLE_FIELDS`), więc
  ta nazwa nie trafia do dołączonych drugi raz.
- Karty scalone z ekranu przed 10.11.2026 dopisku nie mają. Nazwę takiej karty widać
  na karcie w archiwum (`custom_fields.merged_into`), a dołącza się ją ręcznie
  w „Innych nazwach z CV”.

Próba na osobnej kopii bazy (10.11.2026, 18 kart wchłoniętych): mapy 55 kont listy
z `fabryki-it-lista-kont-i-kolejka.md` wyszły bez zmian, a „Znamy teraz” scalonej karty
równało się sumie kart sprzed scalenia i nigdzie nie spadło.

## Ten sam mail z Outlooka na obu kartach (poprawka 12.11.2026)

Synchronizacja Outlooka (`outlook_activities.record`) zapisuje mail i spotkanie przy
każdej dopasowanej firmie, a `ux_sales_activities_outlook` wpuszcza jeden taki wiersz
(`external_source`, `external_id`) na kartę. Zwykłe przepięcie `company_id` dawało więc
IntegrityError i wycofanie całego biegu (kopia z 10.11: 54 aktywności na co najmniej
dwóch kartach, 8 par aktywnych kart).

- `merge.py` (`join_outlook_duplicates`) przed przepięciem dołącza kopię ze źródła do
  wiersza docelowej: docelowa bierze szansę i osobę kopii, gdy sama ich nie ma, a kopia
  znika. Wiersze z importu Atlasa (`external_ref`) indeks pomija i przechodzą jak dotąd.
- Bieg na sucho liczy takie kopie w `outlook_duplicates` (sama liczba w raporcie; filtr
  workflow zna to pole). Dotyk szansy się nie zmienia, bo kopia ma tę samą datę co
  wiersz, który zostaje.
- Test: `test_same_outlook_mail_on_both_cards_becomes_one_activity`.

## Punkty do rozmowy z bota

`sales_company_briefings` ma jeden wiersz na firmę, nadpisywany kolejnym biegiem bota
(`sygnaly-grok-bot.md`). Scalenie daje docelowej punkty źródła, gdy nie ma własnych
albo ma starsze (`generated_at`); nowsze punkty docelowej zostają. Przy karcie
w archiwum wiersz nie zostaje, tak jak nazwy dołączone i powiązania osób.

Bieg bota (`sales_signal_runs.company_ids`) to zapis tego, co wysłano, i scalenie go
nie zmienia. Raport z biegu, który trwał w chwili scalenia, pomija kartę w archiwum
(`signals._companies`), a następny bieg bierze już kartę docelową.

## Domeny

- Propozycja dla karty docelowej (z kontaktami kart, które wchłania): najczęstsza
  firmowa domena z adresów kontaktów, bez darmowych skrzynek (`PUBLIC_EMAIL_DOMAINS`),
  w drugiej kolejności pole strony www. Domena już wpisana zostaje.
- **Pewna** jest domena od dwóch adresów i od połowy firmowych adresów karty, albo
  z jedynego adresu, gdy wyraz z nazwy firmy siedzi w domenie. Remis i pojedynczy adres
  z cudzą domeną (doradca, pośrednik) to propozycja słaba.
- **Ta sama domena na dwóch firmach to konflikt**, także gdy drugą firmą jest karta spoza
  zakresu z domeną już wpisaną. Dopasowanie poczty przestaje wskazywać firmę, gdy domenę
  dzieli więcej kart niż `MAX_DOMAIN_COMPANIES`.
- Słabej i konfliktowej propozycji skrypt nie zapisuje bez `--accept-domain ID[,ID]`.

## Uruchomienie

```bash
# z backend/, baza z DATABASE_URL; domyślnie na sucho (transakcja READ ONLY)
python -m scripts.sales_company_merge --names-file ~/lista-firm.txt --list-out ~/b6-lista.json
python -m scripts.sales_company_merge --apply --actor-id <admin> \
    --expect-merge <liczba> --expect-domains <liczba> [--decide …] [--accept-domain …]
```

- `--apply` wymaga obu liczników z biegu na sucho z tymi samymi flagami i aktywnego
  konta administratora (`--actor-id`, trafia do historii szans). Niezgodny licznik kończy
  bieg odmową bez zapisu. Drugi bieg nie ma czego scalić.
- **Raport na standardowym wyjściu to same liczby.** Nazwy kart, liczniki na kartach
  i propozycje domen idą do pliku `--list-out`; skrypt odmawia zapisu tego pliku
  w repozytorium. Lista do przejrzenia przez Artura powstaje z tego pliku jako prywatny
  artefakt.
- Zapis na produkcji tylko po biegu na sucho, przejrzeniu listy i wyraźnym „tak” Artura,
  w oknie wdrożeń, workflowem, nie przez SSH. Zadanie Coolify odpala komendę co minutę,
  więc bieg z workflowu dostaje `--lock /tmp/nexus-sales-company-merge-<run id>`: pracuje
  pierwsze odpalenie, kolejne kończą się kodem 4. Komenda zadania mieści 255 znaków,
  dlatego długą listę decyzji dzieli się na kilka biegów, każdy z własnymi licznikami.

### Bieg na produkcji: workflow „Coolify sales company merge”

Plik `.github/workflows/coolify-sales-company-merge.yml`, filtr raportu
`.github/scripts/sales_company_merge_report.py`, test
`backend/tests/test_sales_company_merge_workflow_contract.py`. To osobny workflow, a nie
akcja w „Coolify Ops”, bo `workflow_dispatch` mieści 25 wejść, a `coolify-ops.yml` ma
ich dokładnie 25 (26. wejście unieważnia cały plik).

```bash
gh workflow run coolify-sales-company-merge.yml -f mode=dry-run
gh workflow run coolify-sales-company-merge.yml -f mode=apply -f actor_id=<admin> \
    -f expect_merge=<liczba> -f expect_domains=<liczba> [-f decide="12:34,35 40:41"]
```

- **Wejścia:** `mode` (`dry-run` albo `apply`), `expect_merge`, `expect_domains`,
  `actor_id`, `decide` (decyzje `DOCELOWA:ŹRÓDŁO[,ŹRÓDŁO]` rozdzielone spacją),
  `company_ids`, `accept_domain`. Do komendy przechodzą wyłącznie cyfry, przecinki
  i dwukropki. `--names-file` i `--list-out` nie mają wejść, bo nazwy nie mogą stać
  w publicznej komendzie; lista do przejrzenia powstaje na kopii produkcji.
- **Kolejność:** `mode=dry-run` → liczby z raportu (`to_merge`, `domains_to_set`) →
  przejrzenie listy i wyraźne „tak” Artura z tymi liczbami → `mode=apply` z tymi samymi
  `decide`, `company_ids` i `accept_domain` oraz z `expect_merge`, `expect_domains`
  i `actor_id`. `apply` bez tych trzech workflow odrzuca, zanim powstanie zadanie.
  `dry-run` z nimi też odrzuca, żeby bieg pomyślany jako zapis nie przeszedł po cichu
  na sucho.
- **Wynik:** zielony bieg drukuje raport z licznikami. Czerwony podaje kod skryptu:
  2 to odmowa bez zapisu, 3 to wynik zapisu inny niż plan (transakcja wycofana), 4 to
  blokada (ponowiona próba tego samego biegu, „Re-run”), 1 to błąd albo brak raportu.
  Po kodzie 1 i po braku wyniku w 20 minut najpierw bieg na sucho, dopiero potem
  kolejny `apply`.
- **Do logu idzie tylko to, co filtr zna:** raport o polach `Report`, odmowa z listy
  `KNOWN_REFUSALS` (z liczbami) albo sam typ wyjątku. Nowe pole raportu albo nowa odmowa
  w skrypcie wymaga dopisania w filtrze, inaczej zielony zapis wyglądałby na błąd; test
  kontraktu pada, gdy filtr i skrypt się rozjadą.

## Czego skrypt nie robi

Nie scala kontaktów tej samej osoby z dwóch kart, nie zakłada firm z listy, które nie
mają karty (to robi import listy z researchu), nie zmienia etapów, opiekunów ani
powiązań z klientem i nie nadaje domen kartom spoza zakresu.
