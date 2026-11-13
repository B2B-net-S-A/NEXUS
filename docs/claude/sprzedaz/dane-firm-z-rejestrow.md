# Dane firm z rejestrów państwowych (biała lista VAT i KRS) — decyzja Artura 13.11.2026
<!-- indeks: services/sales/registry.py, services/sales/registry_cards.py, bez migracji i bez biegu bota, custom_fields registry_history / registry_checked_at / registry_checked_key / registry_state, app_settings sales_registry_usage, wl-api.mf.gov.pl search/nips, limit 100 zapytań MF wspólny z Rozliczeniami (hr/white_list.py), DAILY_MF_QUERIES, api-krs.ms.gov.pl OdpisAktualny i OdpisPelny, firma wykreślona, likwidacja, upadłość, pole człowieka zostaje, pole automatu (rejestr, bot enrich) się aktualizuje, dubel NIP-u albo KRS-u z inną kartą, historia karty bot_card_history.registry_entries „Rejestry”, 30 dni, noc 1–6, po zapisaniu NIP-u (ekran Firmy, bot enrich), SALES_REGISTRY_ENABLED, staging bez wyjścia do rejestrów, skrypt sales_registry_trial -->

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
  a noc pyta paczkami po 30.
- **KRS** (`api-krs.ms.gov.pl`, odpis aktualny rejestru przedsiębiorców `P`): nazwa,
  NIP, REGON, miejscowość siedziby, likwidacja i upadłość (dział 6). Odpis aktualny 204
  albo 404 sprawdza odpis pełny: ostatni wpis „WYKREŚLENIE” to firma wykreślona.
  Rejestr stowarzyszeń (`S`) jest poza zakresem.
- Formularz firmy ma dalej osobne „Pobierz z rejestru” (`GET /api/sales/companies/registry`,
  łańcuch Generatora umów). To podpowiedź w oknie, nie zapis i nie historia.

## Zapis na kartę

- Tą samą ścieżką co ekran Firmy (`companies.apply_fields`). **Puste pole i pole
  automatu dostają wartość z rejestru.** Pole automatu to pole, w którym karta ma
  dokładnie ostatnią wartość wpisaną przez rejestr (z `registry_history`) albo przez
  bota `enrich` (`enrich._bot_owned`). Każde inne niepuste pole wpisał człowiek: zostaje,
  a wartość z rejestru idzie tylko do historii (`kept`). Ten sam numer w innym zapisie
  („111-222-33-32”, KRS bez zer z przodu) to zgodność, nie zmiana.
- KRS wygrywa z białą listą przy nazwie, REGON-ie i mieście, bo ma je w osobnych
  polach; biała lista daje miasto z adresu po kodzie pocztowym. Miasto z rejestru
  pisanego wielkimi literami idzie jako „Bielsko-Biała”. Kraj `PL` tylko razem
  z miastem z rejestru albo przy mieście zgodnym z rejestrem.
- **NIP albo KRS z innej niezarchiwizowanej karty: nic się nie zapisuje**, historia ma
  `taken` z numerem i nazwą tamtej karty. Scalanie kart zostaje ręczne
  (`scalanie-kart-firm-i-domeny.md`).
- **Firma wykreślona z KRS:** wpis w historii (`inactive`, data wykreślenia), bez
  żadnych pól i bez archiwizacji. Likwidacja i upadłość oraz wykreślenie z rejestru
  VAT też są tylko wpisem `inactive`; pola z rejestru takiej firmy się zapisują, bo
  spółka istnieje.
- NIP z błędną sumą kontrolną nie idzie do MF (`registry_state = invalid_nip`).
  NIP-u nie ma w wykazie i karta nie ma KRS-u: `not_found`, bez wpisu w historii.

## Historia karty (bez migracji)

Decyzja z sesji botów 13.11.2026: rejestr to nie bieg bota (nie ma webhooka ani
tokenu), więc nie ma rodzaju biegu ani wiersza `sales_bot_results`. Wszystko leży
w `sales_companies.custom_fields` karty:

- `registry_history` — lista wpisów `{at, source: "krs"|"vat", lines: [{field, before,
  after, result, other_id?, other_name?, url}]}`, najnowsze na końcu, ostatnie 30.
  `result`: `applied`, `kept`, `taken`, `inactive` (pole `state`, z `removed_on`).
  Jeden wpis na rejestr ze zmianą; sprawdzenie bez zmian wpisu nie dokłada.
- `registry_checked_at`, `registry_checked_key` (NIP i KRS z karty w chwili
  sprawdzenia) i `registry_state` (ostatni stan firmy w rejestrze).
- Ekran: `bot_card_history.registry_entries` zamienia wpisy na historię karty z botem
  „Rejestry (KRS)” albo „Rejestry (biała lista VAT)”, a `GET …/{id}/bot-history`
  dokleja je do wpisów botów (`build(..., extra=…)`). Historia jest widoczna, gdy
  włączone są zadania bota albo rejestry.
- Edycja karty (`PATCH`) nie zmienia `custom_fields`, więc ręczna zmiana pola nie kasuje
  historii. Nowe miejsce, które przepisuje cały słownik `custom_fields`, musi zachować
  te klucze.

## Kiedy

- **Noc:** krok pętli `tasks/sales_signals.py` od 1:00 do 6:00 kalendarza firmy, jedna
  paczka 30 kart na godzinę, we własnej sesji. Najpierw karty z opiekunem albo trwającą
  szansą, wśród nich najpierw niesprawdzane. Karta sprawdzona z tymi samymi NIP-em
  i KRS-em nie wraca przez 30 dni.
- **Po zapisie:** nowy albo zmieniony NIP lub KRS z ekranu Firmy (założenie i edycja)
  i raport bota `enrich` uruchamiają sprawdzenie od razu, w tle (`core.tasks.spawn`),
  w tym samym limicie dziennym. Po limicie karta czeka na noc.
- **Licznik dnia** leży w `app_settings` (`sales_registry_usage`: `day`, `mf_queries`,
  `night_at`). Zapytania MF są rezerwowane pod blokadą wiersza przed siecią, więc noc
  i zapis z ekranu nie przekroczą limitu razem. Godzinę nocy liczy tylko `night_at`:
  sprawdzenie po nocnym raporcie bota paczki nie zabiera.
- **Zapytania do rejestrów idą poza transakcją:** najpierw odczyt numerów i rezerwacja,
  potem sieć, na końcu blokada wiersza karty. Karta, której NIP albo KRS zmienił się
  w trakcie, nie dostaje wyniku dla starych numerów. Timeout (10 s, trzy próby
  z odstępem) albo awaria rejestru zostawia kartę bez zmian i bez daty sprawdzenia,
  więc wraca w kolejnym biegu. Wyjątek: karta z odpowiedzią MF przy awarii samego KRS
  dostaje wynik z białej listy, a KRS sprawdza się za 30 dni. Inaczej zepsuty numer KRS
  zjadałby co godzinę kolejne zapytanie z limitu MF.
- **Flaga `SALES_REGISTRY_ENABLED`**, domyślnie wyłączona (rejestr flag
  `core/feature_flag_registry.py`). Pętla startuje także przy samej tej fladze.
  Na stagingu pętla stoi (`STAGING_BLOCKED_TASKS`), a zapora wyjścia nie wpuszcza
  rejestrów, więc próbę robi się skryptem z hosta (niżej).

## Dane z zewnątrz i logi

- Odpowiedź rejestru przechodzi przez modele pydantic (`extra=ignore`, bo rejestr
  dokłada pola bez zapowiedzi): teksty bez znaków sterujących i ucięte do długości,
  NIP z sumą kontrolną, KRS i REGON z samych cyfr (REGON 14 cyfr z „00000” → 9),
  dłuższa wartość niż kolumna karty odpada. Zły kształt odpowiedzi to awaria rejestru.
- Logi to same liczby, bez nazw firm i numerów: repo i logi Actions są publiczne.
  Błąd w kroku nocnym i w sprawdzeniu po zapisie loguje tylko typ wyjątku, bo
  komunikat błędu bazy niesie parametry zapytania (nazwę, NIP).

## Próba na stagingu z laptopa

`backend/scripts/sales_registry_trial.py`: bierze N kart w kolejności nocy z bazy
z `DATABASE_URL` (staging na laptopie, port 5433), pyta rejestry z hosta i pokazuje
liczby. Domyślnie na sucho (wycofanie), nazwy i różnice idą do pliku poza
repozytorium (`--list-out`). `--apply` zapisuje wynik w tej bazie; skrypt odmawia bazy
spoza localhost, więc produkcji nie dotyka.

Próba 13.11.2026 (kopia produkcji z 13.11): paczka 30 kart na sucho — 30 aktywnych,
33 pola do uzupełnienia (12 nazw prawnych, 7 KRS, 7 REGON, 6 miast, 1 kraj), 145
zgodnych, 1 różnica miasta (zostaje), 0 dubli i błędów, 1 zapytanie MF i 29 KRS w ok. 5 s.
Zapis na 3 kartach: 4 pola, 2 wpisy historii, trzecia karta bez zmian bez wpisu.
