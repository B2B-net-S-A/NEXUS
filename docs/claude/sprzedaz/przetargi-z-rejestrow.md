# Przetargi z BZP i TED: bramka zakłada szanse (wariant B) — decyzje Artura 24.11.2026
<!-- indeks: przetargi, BZP, TED, e-Zamówienia, mo-board API, kursor publicationDate, bramka reguł Kingi, lejek Przetargi, atlas-tenders, tender-identified, Termin minął, Odsiane, Przywróć, SALES_TENDERS_ENABLED, sales_tender_notices, sales_tender_rules, sales_tenders_state, Biznes Polska w Vault, Grok Zbieracz przetargów, Grok Analityk SWZ, Sprzedaż → Leady → Przetargi -->

Wątek „Grok bot zamiast Kingi” (20.11.2026): bot szuka przetargów, a Kinga
przestaje ręcznie przeglądać rejestry. Makiety M1–M3 z liczbami sprawdzonymi
24.11: https://claude.ai/artifact/BhRnTKUALkZaHhkfN8QKyQ (prywatny). Wcześniej:
27.10 „kanał przetargów” był poza zakresem Sprzedaży, a 12.11 Artur odrzucił
G-C (przesiew przetargów). 20.11 sam wrócił do tematu z instrukcją Kingi.

## Decyzje z 24.11.2026

- **Wariant B: bot zakłada szanse sam.** Ogłoszenie, które przeszło bramkę, od razu
  jest szansą w lejku Przetargi, bez „Bierzemy”. Od pierwszego dnia działa automat
  zamykania po terminie. Rekomendacja A (człowiek klika) odrzucona. Nie wracaj do
  listy „Do decyzji” w kolejnych etapach.
- **Biznes Polska kontem Kingi z Vault Grok Bota**, jak LEX w Przepisach (etap 3,
  Zbieracz). Hasło wpisuje do Vault Artur albo Kinga, nigdy sesja Claude, Codex
  ani kod. Ryzyko regulaminu portalu Artur bierze na siebie świadomie.
- **Etap 1 zbudowany bez Groka:** BZP i TED z otwartych API, reguły Kingi,
  widok „Przetargi”, szansa z bramki.

## Przepływ (etap 1)

1. Pętla `sales_tenders` (kontener worker, `tasks/sales_tenders.py`) w dni
   robocze kalendarza firmy od 5:30: jeden udany bieg dziennie, nieudany
   ponawia się po godzinie, najwyżej trzy próby.
2. `services/sales/tenders/sources.py` pobiera BZP od kursora z poprzedniego
   biegu i TED od dnia ostatniego udanego biegu. Pierwszy bieg sięga 7 dni wstecz.
3. `rules.py` (bramka) decyduje o każdym ogłoszeniu. Ogłoszenie spoza IT
   (bez frazy i bez kodu CPV usług IT) nie trafia do bazy wcale.
4. `flow.py` zakłada szansę albo zapisuje odsiane z regułą, potem zamyka szanse
   od bramki po terminie. Sieć idzie poza transakcją, a przetwarzanie trzyma
   blokadę doradczą, więc bieg ręczny i bieg z pętli nie założą dwóch szans.
5. Ręczny bieg (`POST /api/sales/tenders/run`, przycisk „Uruchom teraz”) tylko
   administrator, także przy wyłączonej fladze. Rusza w tle, a ekran odświeża
   się co 3 s, dopóki bieg trwa.

## Bramka: reguły z instrukcji Kingi

- **Wejście:** fraza w przedmiocie (16 fraz Kingi z Biznes Polski) albo główny
  kod CPV usług IT: 720, 722–729 (bez 721, doradztwo sprzętowe) oraz 7961/7962
  (pośrednictwo i dostarczanie personelu, tam trafia body leasing).
- **Odsiew, w tej kolejności:** nie usługa (dostawa, roboty budowlane), słowo
  w przedmiocie (dostawa, zakup, licencja, subskrypcja, szkolenie, sprzęt,
  urządzenie, wyposażenie, dostęp, odnowienie, przedłużenie), słowo w nazwie
  zamawiającego (gminy, starostwa, szkoły, uczelnie, szpitale, SP ZOZ, domy
  kultury, biblioteki, muzea, OPS, spółdzielnie, wodociągi, MPK, MPGK), termin
  minął. „Dostęp”, „odnowienie” i „przedłużenie” są dlatego, że tytuły mówią
  „Usługa dostępu do…” i „Odnowienie wsparcia…”, bez słowa „zakup”.
- **Dopasowanie słowa:** tekst i słowo bez polskich znaków, małymi literami;
  liczy się rdzeń (słowo bez końcowych samogłosek) z końcówką od samogłoski.
  „Umowa ramowa” łapie „umowy ramowej”, „szkolenie” — „szkoleń”, ale „dostawa”
  nie łapie „dostawcy” („Wybór dostawcy usługi SOC” to usługa). Skrót wielkimi
  literami jako cała fraza („IT”, „DORA”, „MPK”) pasuje tylko dosłownie, bo
  „it” bywa zwykłym słowem. Liczba może być doklejona („NIS 2” łapie „NIS2”).
- **Reguły edytuje „Sprzedaż: edycja”** w Sprzedaż → Leady → Przetargi → Reguły
  (`PUT /api/sales/tenders/rules`, `app_settings` → `sales_tender_rules`), bez
  programisty. Pozycja do 60 znaków, najwyżej 80 na listę. Tam też „Opiekun nowych
  szans” (tylko aktywne konto z „Sprzedaż: edycja”, inaczej 422).
- **Co zostaje dla Analityka (etap 2):** wielkość zamówienia i zamawiającego,
  „jeden specjalista”, „umowa zlecenie”, uczelnia z zamówieniem na zespół IT.
  Bez tego bramka przepuszcza też np. wsparcie producenta oprogramowania.
- **Ruch zmierzony 24.11 (17–24.11):** BZP 3 629 ogłoszeń, 60 do bramki, 21
  przeszło; TED 87 polskich ogłoszeń IT, 30 przeszło. Około 50 szans tygodniowo.

## Szansa z bramki

- Lejek `atlas-tenders` (Przetargi), etap `tender-identified` („Identyfikacja”),
  data zamknięcia = termin składania ofert (dzień w kalendarzu firmy), tytuł =
  przedmiot, `source = 'tender'`, `external_ref = 'tender:<bzp|ted>:<numer>'`.
  Brak lejka → bieg kończy się błędem „Brak lejka „Przetargi” w Sprzedaży.”
- Ta sama ścieżka co założenie ręczne: `apply_stage`, `history.record_created`
  (autor pusty, bo zakłada system). Teczka ogłoszenia to pierwsza notatka
  (numer, termin z godziną, zamawiający z NIP, CPV, próg UE, przez co przeszło,
  link) i `custom_fields["tender"]`.
- **Bez biegu dat zatrudnienia (D3)** przy szansie z bramki: kosztuje model AI,
  a automat zakłada ok. 50 szans tygodniowo. Daty uzupełnia przycisk na karcie.
- Karta zamawiającego: po NIP (BZP podaje go dla 10 cyfr), potem po nazwie
  kanonicznej, inaczej nowa karta z `source = 'tender'`. TED nie podaje NIP-u.

## Zamykanie po terminie i odsiane

- **Automat zamyka tylko szanse od bramki** (`external_ref` `tender:%`), które
  stoją w „Identyfikacji” z datą zamknięcia przed dziś: przegrana z powodem
  „Termin minął”, wpis w historii bez autora. Szansę przesuniętą dalej ktoś już
  prowadzi, więc automat jej nie rusza. 42 stare karty z Atlasa w „Identyfikacji”
  zostają bez zmian (świadomie: to nie są szanse bramki).
- **Odsiane:** wiersz z regułą i słowem, które odsiało, widoczny 14 dni.
  „Przywróć” (`POST /api/sales/tenders/{id}/restore`, „Sprzedaż: edycja”) zakłada
  szansę u osoby, która kliknęła (opiekun i autor). Po terminie 409.

## Zmiana postępowania (nowa publikacja, ten sam przetarg)

- **TED publikuje zmianę (zwykle późniejszy termin) jako nowe ogłoszenie `cn-standard`
  z nowym numerem i tym samym `procedure-identifier`** (24.11: 807300-2026 →
  815837-2026, termin 27.11 → 02.12; 801010 → 812191). Bez tego bramka zakładała
  drugą szansę, a pierwszą automat zamykał po starym terminie, choć przetarg trwał.
- Dlatego przetarg rozpoznajemy po postępowaniu (`procedure_id`: TED
  `procedure-identifier`, BZP `tenderId`; indeks unikalny ze źródłem). Nowsza
  publikacja aktualizuje wiersz (numer, link, termin) i szansę: teczkę, datę
  zamknięcia (tylko gdy nikt jej nie zmienił ręcznie) i notatkę „Zmiana przetargu…”
  z nowym terminem. Szansa zamknięta przez automat po starym terminie wraca do
  „Identyfikacji”, gdy nowy termin trwa. Odsiane, które po zmianie przechodzi
  bramkę (np. przedłużony termin), dostaje szansę. Starsza publikacja po zmianie
  jest pomijana. W linii biegu: „zmiany ogłoszeń N”.
- **„Tylko usługi” w TED czyta `contract-nature-main-proc`**, bo `contract-nature`
  miesza rodzaj główny z dodatkowymi (808107-2026: dostawa z usługą dodatkową).
- **BZP:** zmiana ogłoszenia to osobny typ ogłoszenia (nie `ContractNotice`), którego
  etap 1 nie czyta. Przedłużony termin w BZP nie przesuwa więc daty szansy; szansę,
  której nikt nie ruszył, automat zamknie po pierwotnym terminie.

## Pułapki rejestrów

- **API BZP** (`ezamowienia.gov.pl/mo-board/api/v1/notice`) oddaje najwyżej
  `PageSize` pozycji, ignoruje `PageNumber` (strona 2 = strona 1), a
  `PublicationDateTo` z godziną nie działa. Dlatego kursor:
  `PublicationDateFrom` = ostatnia `publicationDate` (UTC, w sekundach), duble
  odpadają po numerze. Porcja 100, bo każda pozycja niesie pełny HTML ogłoszenia
  (ok. 30 KB). Makieta z 20.11 liczyła z jednej porcji 500 na dzień i zaniżyła
  ruch (2 994 / 68 / 17 zamiast 3 697 / 94 / 24 za 12–19.11).
- Link do ogłoszenia BZP: `mo-client-board/bzp/notice-details/id/{objectId}`
  (trasa z aplikacji BZP, sprawdzona 24.11). PDF: `mo-board/api/v1/Board/GetNoticePdfById?noticeId=`.
- **TED** (`api.ted.europa.eu/v3/notices/search`): CPV dopasowuje hierarchicznie
  (72000000 łapie 72413000); tytuł ma przedrostek „Polska – <opis CPV> – ”,
  który ucinamy; termin to sam dzień, bez godziny.

## Dane, ekran, włączenie

- Tabela `sales_tender_notices` (0768, DDL w `sales_schema.TENDERS_DDL`, lustro
  w `entrypoint.sh`, sonda w `/api/health/deep`): ogłoszenia po wejściu do bramki,
  para (źródło, numer) unikalna. Stan biegów: `app_settings` → `sales_tenders_state`
  (kursor BZP, dzień TED, ostatni bieg z liczbami; „w toku” starsze niż godzina
  to bieg przerwany).
- **Ekran:** Sprzedaż → Leady → Przetargi (`/sales/tenders`), widok obok
  „Leady | Boty”, bo Sprzedaż ma siedem zakładek (decyzja z 11.11.2026). Założone
  szanse, Odsiane (z „Przywróć”), Reguły. Nieudany bieg to czerwony pasek z godziną.
- **Trasy** `/api/sales/tenders/**`: odczyt `SalesViewUser`, zapis `SalesEditUser`,
  bieg tylko admin. Wzorzec: `tests/data/authz_golden/sales_tenders.json`.
- **Flaga `SALES_TENDERS_ENABLED`** domyślnie wyłączona: pętla stoi, ekran mówi
  „Bieg codzienny wyłączony”. Włącza Artur workflowem „Coolify set env”.
- **Staging:** pętla zablokowana (`STAGING_BLOCKED_TASKS`). Ręczny bieg wymaga
  `STAGING_EXTRA_ALLOWED_HOSTS=ezamowienia.gov.pl,api.ted.europa.eu`.
- Logi: same liczby (repo i logi są publiczne).

## Czego bot nie robi

Nie zakłada kont na platformach, nie składa ofert, nie pisze do zamawiających.
Do rejestrów idą tylko daty i kody CPV, żadnych danych firmy.

## Etap 2 i 3 (czekają)

- **Grok Analityk:** czyta SWZ ogłoszenia, które przeszło bramkę, i dokłada do
  teczki role, roboczogodziny, wadium, warunki udziału i ocenę według miękkich
  reguł Kingi. NEXUS liczy „u nas” (kandydaci na role, historia z zamawiającym).
  W wariancie B ocena „Nie pasuje” zamyka szansę z powodem, a nie blokuje jej założenia.
- **Grok Zbieracz:** platformy zamawiających z `ListaPrzetargow2025.xlsx` Kingi
  i Biznes Polska kontem Kingi z Vault (decyzja wyżej). Ogłoszenie z platformy
  przechodzi, gdy link działa i numer postępowania się zgadza. Mail od Klaudii
  z eB2B przestaje być potrzebny, gdy eB2B czyta Zbieracz.
