# Kontrola treści strony kariery — domknięte luki

Data: 13.10.2026 · Bez migracji · Reguły: `docs/claude/rekrutacja-tworzenie/strona-kariery-dla-kandydatow.md`

## Po co

Przegląd bezpieczeństwa ogłoszeń na portale (PR #2158) pokazał, że
deterministyczna kontrola opisu publicznego (`services/public_profile_lint.py`)
przepuszcza treści, których na publicznej stronie być nie powinno. W ogłoszeniach
załatałem to dopiskami działającymi tylko tam; strona kariery — z tej samej
funkcji — miała te luki dalej.

## Co się zmieniło

Reguły przeniesione do wspólnej kontroli (strona kariery i ogłoszenia czytają
jedno źródło):

| Grupa | Przykłady, które teraz odmawiają zatwierdzenia |
|---|---|
| Kwoty słownie i bez symbolu waluty | „200 złotych za godzinę”, „150 dolarów”, „3000 CZK”, „2 mln PLN”, „do 30 tys. netto”, „180 netto/h” |
| Kwota po skrócie przed wielką literą | „do 30 tys. PLN”, „15 tys. EUR” — zdanie było cięte po „tys.” i żaden wzorzec nie widział kwoty (luka sprzed tej zmiany, także w ogłoszeniach) |
| Linki i kontakt | `https://…`, `www.…`, „jan [at] firma”, „22 555 12 34”, „+48 22 555 12 34”, „+49 170 1234567” |
| Znaki niewidoczne i pełnej szerokości | nazwa klienta, kwota, telefon albo e-mail z miękkim łącznikiem, spacją zerowej szerokości, selektorem wariantu albo wypełniaczem hangul w środku (tekst z Worda/PDF-a); „180 ＰＬＮ”, „jan＠example.com” |

W `services/job_ad/lint.py` zostało tylko to, czego strona kariery nie ma:
poziom „uwaga” (liczba przy słowie „stawka”, adres bez „www”, nagłówki
wewnętrznego formularza, MD, numer zlecenia, braki).

## Czego świadomie nie zmieniłem

- **Adres bez „http” i „www”** („firma.pl”) nie jest regułą na stronie kariery:
  końcówki „.net”, „.io”, „.js” to nazwy technologii, a strona kariery nie ma
  poziomu „uwaga” — każde znalezisko odmawia zatwierdzenia.
- **Nazwa wyświetlana i prawna klienta** nadal działa tylko w ogłoszeniach: na
  stronie kariery obróciłaby adresy `/r/<slug>` rozesłanych linków.
- **Litery z innego alfabetu** podstawione w nazwie klienta (cyrylica zamiast
  łacińskiego „A”) kontrola nadal przepuszcza.
- **Pełna lista tego, czego kontrola nie łapie**, jest w regułach strony
  kariery („Czego kontrola nadal nie łapie”) — m.in. kwoty w całości słownie,
  waluta oddzielona od liczby słowem, adresy bez „http”/„www”, telefony
  z kropkami.
- **Fałszywe alarmy, które zostają:** „3 złote zasady”, „10 złotych praktyk”
  (liczba + forma waluty), ciąg cyfr w układzie 2-3-2-2 („REGON 12 345 67 89”).

## Skutek dla istniejących opisów

- **Opublikowane strony nie znikają.** Kontrola biegnie w podglądzie edytora
  i przy zatwierdzeniu; opublikowany opis zostaje, dopóki ktoś go nie zmieni.
  Nowe reguły dotkną dopiero kolejnego zatwierdzenia.
- **Adresy linków rekrutacji: naprawiony stary błąd.** Slug `/r/<slug>`
  przechodzi tę samą kontrolę, a adres ze znaleziskiem jest przy zatwierdzeniu
  wymieniany (stary daje 404). Losowa końcówka sluga trafiała we wzorzec kwoty
  („…-zl1v”) od początku istnienia kontroli — raz na ok. 1800 linków
  zatwierdzenie opisu wymieniało rozesłany adres bez powodu. Wymiana czyta
  teraz tylko część sluga pochodzącą z tytułu.
- **Niezmierzone:** ile dziś zatwierdzonych opisów dostałoby nowe znalezisko
  przy ponownym zatwierdzeniu. Wymaga odczytu produkcji (zgoda Artura), a strona
  kariery nie ma publicznej listy ofert, z której dałoby się to policzyć.

## Poprawki po przeglądzie bezpieczeństwa (przed otwarciem PR-a)

| Znalezisko | Poprawka | Dowód |
|---|---|---|
| Losowa końcówka sluga („…-1czk”, 50 z 1,68 mln; „…-zl1v” już wcześniej, 930) trafiała we wzorce kwot → wymiana rozesłanego adresu | Wymiana czyta `job_slug_content(slug)` | `test_random_suffix_of_a_job_slug_is_not_content`; z bazą: `test_approval_keeps_a_link_whose_random_suffix_looks_like_money`, `test_approval_still_replaces_a_link_whose_slug_names_the_client` (CI) |
| Kontrola ogłoszeń przestała blokować „30 tys. Netto” i „tel22 555 12 34” | Skróty nie kończą zdania; numer stacjonarny znów może stać po literze | przypadki w testach kwot i kontaktu; porównanie starej i nowej kontroli ogłoszeń na 4557 przypadkach |
| Fałszywe alarmy: „Austria (AT) i …”, „przepisy 2024 brutto/netto”, „00-120 Złota 59”, „2 zloty firmowe” | Zawężone wzorce (małe „at”, formy waluty, nie rok i nie jedna cyfra) | `test_new_rules_leave_ordinary_text_alone` |
| Normalizacja wydłuża tekst („⒛” → „20.”) i wzorce kwot liczyły się do 0,27 s na 4000 znaków, ponad 2 s po mojej pierwszej poprawce z mnożnikiem | Liczba startuje tylko od początku ciągu cyfr; najgorszy znaleziony przypadek 0,04 s | test czasu; test równoważności na 20 tys. losowych ciągów |

Porównanie starej (z `main`) i nowej kontroli ogłoszeń po poprawkach: decyzja
„blokuje / nie blokuje” różni się tylko tam, gdzie miała się różnić — trzy
klasy zdjętych fałszywych alarmów i jedna nowa blokada („100 tys. EUR”).
Wyjątek: liczba i waluta rozdzielone nową linią w jednym polu („200⏎złotych”)
— stara kontrola ogłoszeń czytała całe pole, wspólna tnie na liniach. Zapis
ogłoszenia skleja linie w polu (`clean_content`), więc w zapisanej treści taki
przypadek nie występuje; na stronie kariery nie był łapany nigdy.

## Weryfikacja

| Co | Wynik |
|---|---|
| Nowe testy `test_public_profile_lint.py` (kwoty, kontakt, znaki niewidoczne, zwykły tekst bez alarmu, slugi, równoważność i czas wzorców) | 21 padało przed zmianą, wszystkie zielone po |
| `test_job_ad_lint.py`, `_generate`, `_render` — bez zmiany oczekiwań | zielone |
| Stara i nowa kontrola na 1969 literałach z 11 plików testów strony kariery i ogłoszeń | wynik zmienia się dla 22 — wszystkie to adresy URL spoza kontrolowanych pól (adresy bazowe testów, profile LinkedIn, nagłówki botów, linki do portali) |
| Pola, które kontrola czyta (`_payload_texts`): tytuł, podtytuł, opis, wymagania, mile widziane, miasto, start, długość | żadne nie niesie linku z systemu |
| Czas całej kontroli na 4000 znaków ciągów „prawie pasujących”, także wydłużanych przez normalizację | do 0,04 s |
| Trasy z bazą (`test_career_links_api.py` i pokrewne) | sprawdza CI |
