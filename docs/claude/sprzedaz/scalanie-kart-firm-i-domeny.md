# Scalanie zdublowanych kart firm i domeny: jednorazowy skrypt (B6) — decyzje Artura 10.11.2026
<!-- indeks: scripts/sales_company_merge.py, konta lejka atlas-it-factories i lista z researchu centrów IT, grupa = ta sama nazwa kanoniczna albo NIP, karta docelowa, „do decyzji”, karty tej samej marki (wariant nazwy, inna spółka), --decide, blokada dotyku szansy, nazwy dołączone po scaleniu, domena z poczty kontaktów, konflikt domen, --accept-domain, --expect-merge, --expect-domains, lista poza repo -->

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

„Kogo znamy” dopasowuje osoby dokładnie po nazwie kanonicznej, a `merge.py` nie przenosi
nazwy źródła. Bez dopisku osoby z „Marka Group” w CV znikłyby z liczników po scaleniu
tej karty w „Marka”. Skrypt dopisuje więc nazwę (i nazwę prawną) wchłoniętej karty do
`sales_company_aliases` jako `joined`, gdy różni się od nazw docelowej. Da się to cofnąć
na karcie („Cofnij”). Scalenie z ekranu Firmy tego nie robi.

Próba na osobnej kopii bazy (10.11.2026, 18 kart wchłoniętych): mapy 55 kont listy
z `fabryki-it-lista-kont-i-kolejka.md` wyszły bez zmian, a „Znamy teraz” scalonej karty
równało się sumie kart sprzed scalenia i nigdzie nie spadło.

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

## Czego skrypt nie robi

Nie scala kontaktów tej samej osoby z dwóch kart, nie zakłada firm z listy, które nie
mają karty (to robi import listy z researchu), nie zmienia etapów, opiekunów ani
powiązań z klientem i nie nadaje domen kartom spoza zakresu.
