# Dane firm z rejestrów państwowych (biała lista VAT i KRS) — decyzja Artura 13.11.2026
<!-- indeks: services/sales/registry.py, services/sales/registry_cards.py, rodzaj biegu registry (0688), Dane firm (automat), wl-api.mf.gov.pl search/nips, limit 100 zapytań MF wspólny z Rozliczeniami (hr/white_list.py), DAILY_MF_QUERIES, api-krs.ms.gov.pl OdpisAktualny i OdpisPelny, firma wykreślona, likwidacja, upadłość, status VAT, tylko puste pola, pole człowieka zostaje, dubel NIP-u albo KRS-u z inną kartą, historia karty w sales_bot_results (accepted, payload.fields/outcomes), checked_key, 30 dni, noc 1–6, po zapisaniu NIP-u (ekran Firmy, bot enrich), SALES_REGISTRY_ENABLED, staging bez wyjścia do rejestrów, skrypt sales_registry_trial -->

Krok 6 planu botów Sprzedaży (raport: https://claude.ai/artifact/2Hxqi6uLTSE4AYp1GPqtpV).
Artur 13.11.2026: dane od botów zapisują się od razu, bez „Przyjmij”, a NIP, KRS,
REGON, nazwa prawna i miasto siedziby mają być potwierdzone u źródła. Na kopii
produkcji z 13.11: 9687 aktywnych kart, NIP na 357, miasto na 277.

Kod: `backend/app/services/sales/registry.py` (klient i walidacja odpowiedzi),
`backend/app/services/sales/registry_cards.py` (zapis na karty, historia, harmonogram).
Testy: `backend/tests/test_sales_registry_unit.py`, `backend/tests/test_sales_registry_api.py`,
nagrania odpowiedzi w `backend/tests/data/sales_registry/` (fikcyjne firmy, bez sieci).

## Źródła

- **Biała lista VAT** (`wl-api.mf.gov.pl`, metoda `search/nips`): po NIP-ie nazwa,
  REGON, KRS, adres siedziby i status VAT. Limit MF: 100 zapytań `search` dziennie,
  do 30 NIP-ów w jednym, po wyczerpaniu blokada do 0:00
  (https://www.gov.pl/web/kas/api-wykazu-podatnikow-vat). **Ten sam limit zużywają
  Rozliczenia** (`services/hr/white_list.py`, „Pobierz z białej listy” i sprawdzenie
  rachunku), dlatego Sprzedaż bierze najwyżej `DAILY_MF_QUERIES` (25) zapytań dziennie,
  liczonych z raportów biegów `registry` od początku dnia firmy, a noc pyta paczkami po 30.
- **KRS** (`api-krs.ms.gov.pl`, odpis aktualny rejestru przedsiębiorców `P`): nazwa,
  NIP, REGON, miejscowość siedziby, likwidacja i upadłość (dział 6). Odpis aktualny 204
  albo 404 sprawdza odpis pełny: ostatni wpis „WYKREŚLENIE” to firma wykreślona.
  Rejestr stowarzyszeń (`S`) jest poza zakresem.
- Formularz firmy ma dalej osobne „Pobierz z rejestru” (`GET /api/sales/companies/registry`,
  łańcuch Generatora umów). To podpowiedź w oknie, nie zapis i nie historia.

## Zapis na kartę

- **Tylko puste pola**, tą samą ścieżką co ekran Firmy (`companies.apply_fields`).
  Pole z inną wartością zostaje, a wartość z rejestru idzie wyłącznie do historii
  (`kept` z obecną wartością). Ten sam numer w innym zapisie („111-222-33-32”,
  KRS bez zer z przodu) to zgodność (`same`), nie różnica.
- KRS wygrywa z białą listą przy nazwie, REGON-ie i mieście, bo ma je w osobnych
  polach; biała lista daje miasto z adresu po kodzie pocztowym. Miasto z rejestru
  pisanego wielkimi literami idzie jako „Bielsko-Biała”. Kraj `PL` tylko razem
  z miastem z rejestru albo przy mieście zgodnym z rejestrem.
- **NIP albo KRS z innej niezarchiwizowanej karty: nic się nie zapisuje**, historia ma
  `taken` z numerem i nazwą tamtej karty. Scalanie kart zostaje ręczne
  (`scalanie-kart-firm-i-domeny.md`).
- **Firma wykreślona z KRS:** wpis w historii (`state = removed`, data wykreślenia),
  bez żadnych pól i bez archiwizacji. Likwidacja i upadłość (`liquidation`,
  `bankruptcy`) oraz wykreślenie z rejestru VAT (`vat_removed`) też są tylko wpisem
  w historii; pola z rejestru takiej firmy się zapisują, bo spółka istnieje.
- NIP z błędną sumą kontrolną nie idzie do MF: wpis `invalid_nip`. NIP-u nie ma
  w wykazie i karta nie ma KRS-u: wpis `not_found`.

## Historia karty

- Jedno sprawdzenie karty to wiersz `sales_bot_results` rodzaju `registry` ze statusem
  `accepted`, w tym samym kształcie co zapis od razu bota `enrich`: `payload.fields`
  (wartość, źródło `vat`/`krs`, link do odpowiedzi rejestru), `payload.outcomes`
  (`applied`, `same`, `kept`, `taken`), a do tego `actor` („Dane firm (automat)”),
  `checked_at`, `state`, `vat_status`, `sources` i `checked_key`.
- Odcisk to wartości, wyniki pól, stan i numery z karty, bez daty sprawdzenia:
  to samo sprawdzenie drugi raz odświeża datę wiersza zamiast dokładać nowy.
  Pierwsze sprawdzenie zostaje jako „wpisano”, kolejne jako „potwierdzono”.
- Każde sprawdzenie ma bieg `sales_signal_runs` rodzaju `registry` (migracja 0688
  podmienia CHECK rodzaju, lustro w `entrypoint.sh` przez `REGISTRY_DDL`): bez tokenu,
  od razu `received`, w `report` same liczby (`checked`, `applied_fields`,
  `kept_fields`, `taken_fields`, `inactive`, `errors`, `mf_queries`, `krs_queries`).
  Bieg bez żadnej odpowiedzi rejestru ma `failed`.

## Kiedy

- **Noc:** krok pętli `tasks/sales_signals.py` od 1:00 do 6:00 kalendarza firmy, jedna
  paczka 30 kart na godzinę, we własnej sesji. Najpierw karty z opiekunem albo trwającą
  szansą, wśród nich najpierw niesprawdzone. Karta sprawdzona z tymi samymi NIP-em
  i KRS-em (`checked_key`) nie wraca przez 30 dni.
- **Po zapisie:** nowy albo zmieniony NIP lub KRS z ekranu Firmy (założenie i edycja)
  i raport bota `enrich` uruchamiają sprawdzenie od razu, w tle (`core.tasks.spawn`),
  w tym samym limicie dziennym. Po limicie karta czeka na noc.
- **Zapytania do rejestrów idą poza transakcją:** najpierw odczyt numerów, potem sieć,
  na końcu blokada wiersza karty. Karta, której NIP albo KRS zmienił się w trakcie,
  nie dostaje wyniku dla starych numerów. Timeout (10 s, trzy próby z odstępem) albo
  awaria rejestru zostawia kartę bez zmian i bez wpisu, więc wraca w kolejnym biegu.
- **Flaga `SALES_REGISTRY_ENABLED`**, domyślnie wyłączona (rejestr flag
  `core/feature_flag_registry.py`). Pętla startuje także przy samej tej fladze.
  Na stagingu pętla stoi (`STAGING_BLOCKED_TASKS`), a zapora wyjścia nie wpuszcza
  rejestrów, więc próbę robi się skryptem z hosta (niżej).

## Dane z zewnątrz i logi

- Odpowiedź rejestru przechodzi przez modele pydantic (`extra=ignore`, bo rejestr
  dokłada pola bez zapowiedzi): teksty bez znaków sterujących i ucięte do długości,
  NIP z sumą kontrolną, KRS i REGON z samych cyfr (REGON 14 cyfr z „00000” → 9),
  dłuższa wartość niż kolumna karty odpada. Zły kształt odpowiedzi to awaria rejestru.
- Logi i raport biegu to same liczby, bez nazw firm i numerów: repo i logi Actions
  są publiczne. Nazwy rejestru leżą tylko w bazie (karta i historia).

## Próba na stagingu z laptopa

`backend/scripts/sales_registry_trial.py`: bierze N kart z NIP-em z bazy z
`DATABASE_URL` (staging na laptopie, port 5433), pyta rejestry z hosta i pokazuje
liczby. Domyślnie transakcja tylko do odczytu, nazwy i różnice idą do pliku poza
repozytorium (`--list-out`). `--apply` zapisuje wynik w tej bazie (nigdy na
produkcji: skrypt odmawia, gdy baza nie jest stagingiem).
