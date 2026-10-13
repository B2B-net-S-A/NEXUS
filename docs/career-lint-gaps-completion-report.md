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
| Linki i kontakt | `https://…`, `www.…`, „jan [at] firma”, „22 555 12 34”, „+48 22 555 12 34”, „+49 170 1234567” |
| Znaki niewidoczne i pełnej szerokości | nazwa klienta, kwota, telefon albo e-mail z miękkim łącznikiem lub spacją zerowej szerokości w środku (tekst z Worda/PDF-a); „180 ＰＬＮ”, „jan＠example.com” |

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

## Skutek dla istniejących opisów

- **Opublikowane strony nie znikają.** Kontrola biegnie w podglądzie edytora
  i przy zatwierdzeniu; opublikowany opis zostaje, dopóki ktoś go nie zmieni.
  Nowe reguły dotkną dopiero kolejnego zatwierdzenia.
- **Adresy linków rekrutacji są bezpieczne.** Slug `/r/<slug>` przechodzi tę
  samą kontrolę, a adres ze znaleziskiem jest przy zatwierdzeniu wymieniany
  (stary daje 404). Nowe wzorce nie pasują do ciągów z łącznikami — numer
  stacjonarny nie może stać po łączniku ani literze; test trzyma przykłady.
- **Niezmierzone:** ile dziś zatwierdzonych opisów dostałoby nowe znalezisko
  przy ponownym zatwierdzeniu. Wymaga odczytu produkcji (zgoda Artura), a strona
  kariery nie ma publicznej listy ofert, z której dałoby się to policzyć.

## Weryfikacja

| Co | Wynik |
|---|---|
| Nowe testy `test_public_profile_lint.py` (kwoty, kontakt, znaki niewidoczne, zwykły tekst bez alarmu, slugi) | 21 padało przed zmianą, wszystkie zielone po |
| `test_job_ad_lint.py`, `_generate`, `_render` — bez zmiany oczekiwań | zielone |
| Stara i nowa kontrola na 1969 literałach z 11 plików testów strony kariery i ogłoszeń | wynik zmienia się dla 22 — wszystkie to adresy URL spoza kontrolowanych pól (adresy bazowe testów, profile LinkedIn, nagłówki botów, linki do portali) |
| Pola, które kontrola czyta (`_payload_texts`): tytuł, podtytuł, opis, wymagania, mile widziane, miasto, start, długość | żadne nie niesie linku z systemu |
| Czas nowych wzorców na 4000 znaków ciągów „prawie pasujących” | do 0,05 s |
| Trasy z bazą (`test_career_links_api.py` i pokrewne) | sprawdza CI |
