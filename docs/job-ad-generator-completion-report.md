# Ogłoszenie na portale (Pracuj.pl, JustJoin.IT) — raport, etap 1

Data: 12.10.2026 · Migracja: 0430 · Reguły: `docs/claude/rekrutacja-tworzenie/ogloszenie-na-portale-kopiuj-wklej.md`
· Makiety: https://claude.ai/artifact/NK7tLYnrh1mNgH7MQ8MhtX

## Po co

Rekruterzy zbierali dane rekrutacji ręcznie i układali ogłoszenie w ChatGPT.
Pomiar naszych publicznych ogłoszeń z 12.10.2026:

| Co | JustJoin.IT (50 z 189) | Pracuj.pl (15 z 304) |
|---|---|---|
| Sekcja „co oferujemy” | 4 z 50 | 5 z 15 (u 6 firm konkurencji 6 z 6) |
| Etapy procesu | 0 z 50 | — |
| Start albo długość projektu | 12 z 50 | — |
| Wklejony wewnętrzny formularz albo kwota w treści | 5 z 50 | 1 (widełki w treści inne niż w nagłówku) |
| Zapis płci w tytule | 6 różnych konwencji | — |

Przycisk „Napisz ogłoszenie z AI” nie używał modelu: był szablonem, który
sklejał tytuł z wymaganiami i dopisywał „Klient: …”.

## Co powstało

- **Okno „Ogłoszenie na portale”** (menu „⋯” rekrutacji i zakładka „Zespół
  i ogłoszenie” Profilu Championa): jedna treść rekrutacji w dwóch formatach —
  pola formularza Pracuj.pl (każde z własnym „Kopiuj”) i opis JustJoin.IT
  z polami formularza oraz tech stackiem z poziomem.
- **Treść układa model wyłącznie z materiału rekrutacji** (bez klienta,
  stawek, notatek „Tylko zespół”); tytuł, warunki, „co oferujemy” firmy
  i etapy procesu dokleja kod. Wersja angielska: model tłumaczy start, długość
  i język pracy.
- **Kontrola przed skopiowaniem** na wszystkim, co idzie do schowka. Blokują:
  nazwa klienta (także wyświetlana i prawna), kontakt (e-mail, telefon,
  link), nazwisko, kwota z walutą albo stawką — także słownie („200
  złotych”, „30 tys. netto”). Doradzają: nagłówki wewnętrznego formularza,
  liczby MD, numer zlecenia, adres strony bez „www”, wymaganie
  w jednym–dwóch słowach, braki. Znaki niewidoczne z Worda i PDF-a nie
  chowają znaleziska.
- **Ręczne poprawki** każdego pola, warunków i poziomu technologii; zapis
  odświeża kontrolę i teksty do skopiowania. Niezapisany tekst przechodzi
  między zakładkami i zostaje po odrzuconym zapisie; cudza zmiana w tym
  samym czasie kończy się odmową (409), nie cichym nadpisaniem.
- **Stałe części ogłoszenia** w Ustawienia → Rekrutacja (admin, Head of
  Recruitment): dopisek do tytułu, „co oferujemy”, etapy procesu, zdanie
  o firmie — po polsku i po angielsku.
- **Stary „Szkic ogłoszenia” usunięty** razem z `api/ai_writer.py`
  (dwie trasy) i klientem `aiWriterApi`.

## Odstępstwa od planu i makiet

| Zmiana | Powód |
|---|---|
| „Przygotuj ponownie” przy niedostępnym modelu = 503 bez zapisu; złożenie bez modelu tylko jako pierwsza wersja i tylko po polsku | Chwilowa awaria nadpisałaby treść, którą rekruter już poprawił; materiał rekrutacji jest po polsku |
| Szersza lista nazw klienta (wyświetlana, prawna) działa tylko w ogłoszeniu, nie na stronie kariery | Na stronie kariery przy najbliższym zatwierdzeniu obróciłaby adresy `/r/<slug>` rozesłanych linków — to osobna decyzja |
| Kwota bez waluty przy słowie „stawka”/„rate” doradza zamiast blokować | „rate limiting … Java 17” blokowałoby kopiowanie zwykłych wymagań |
| Start, długość i język pracy zapisują się w ogłoszeniu, nie w Profilu Championa | Zapis Championa ma własne skutki (bramki, weryfikacja, migawka opisu publicznego) |
| Dopisek do tytułu: „(k/m/x) · (f/m/x)”, „(k/m) · (f/m)” albo brak | Forma żeńska po ukośniku wymagałaby odmiany przez model |
| Kategoria JustJoin.IT bez podpowiedzi | Słownik dostawcy jest dostępny dopiero po połączeniu konta |
| Sekcja „Zespół i ogłoszenie” ma sam przycisk; wiersze stanu per portal przychodzą z etapem 2 | Dopiero „oznacz jako opublikowane” daje im treść; sekcja nie odpytuje serwera w harnessie |
| Ustawienia w obszarze Rekrutacja (admin i HoR), nie pod „Portale ogłoszeniowe” | Tamta pozycja to połączenie konta, tylko dla admina |

## Poprawki po przeglądzie kodu i bezpieczeństwa (przed otwarciem PR-a)

| Znalezisko | Poprawka | Dowód |
|---|---|---|
| Kwoty „15 tysięcy zł”, „180/godzinę”, „25 000 / miesiąc” były tylko uwagą — własny wzorzec był węższy niż wzorce strony kariery | O blokadzie decydują wzorce strony kariery (`CERTAIN_MONEY_PATTERNS`); dopisane kwoty słownie | `test_amount_with_a_currency_or_a_rate_unit_blocks` (19 zapisów), `test_a_certain_amount_far_from_the_pay_word_still_blocks` |
| Link, telefon „22 555 12 34”, „+48 …”, „jan [at] firma” przechodziły bez znaleziska | Dopiski kontroli tylko dla ogłoszenia | `test_links_and_contact_written_around_the_rules_block` (9 zapisów), `test_ordinary_technical_sentences_raise_no_alarm` |
| Miękki łącznik albo spacja zerowej szerokości w nazwie klienta, kwocie, telefonie omijały każdą regułę | Kontrola po NFKC i bez znaków formatujących; zapis i render je wycinają | `test_invisible_characters_do_not_hide_a_finding`, `test_saved_content_drops_invisible_characters_but_keeps_emoji` |
| Ponowne przygotowanie zapisywało bezwarunkowo po odpowiedzi modelu | Zapis warunkowy, 409 przy zmianie w trakcie | `test_regenerate_keeps_an_edit_saved_while_the_model_was_working`, `test_template_never_replaces_an_ad_created_while_the_model_was_failing` (CI) |
| Odświeżenie w tle pod otwartą poprawką przepuszczało stary tekst przez kontrolę wersji | Wersja bazowa z początku edycji | „odświeżenie w tle pod otwartą poprawką…” w `JobAdWindow.test.tsx` |
| Zmiana zakładki i odrzucony zapis warunków gubiły niezapisany tekst | Niezapisany tekst w stanie okna | trzy testy „niezapisany tekst” + przeklikane w harnessie |
| Wzorzec kwoty strony kariery liczył się sześciennie („1” + 800 spacji = kilkanaście sekund na pętli zdarzeń; opis publiczny przyjmuje 4000 znaków) | Kwantyfikator zaborczy w `public_profile_lint._NUMBER`, te same dopasowania | `test_money_patterns_stay_linear_on_long_whitespace` |

## Weryfikacja

| Co | Wynik |
|---|---|
| Testy logiki backendu bez bazy (`test_job_ad_render`, `_lint`, `_generate`, lustro migracji, `test_public_profile_lint`) | zielone lokalnie (Python 3.12) |
| Strażnicy repo bez bazy (sekcje tras, macierz uprawnień, inwentarz schematu, DDL entrypointu, rejestr modeli, stemple, indeks CLAUDE.md) | zielone lokalnie |
| Wzorzec uprawnień `tests/data/authz_golden/job_ads.json` | ogłoszenie: każda rola wewnętrzna; stałe bloki: admin i Head of Recruitment |
| Trasy z bazą (`test_job_ads_api.py`, 19 testów) | lokalnie padają wyłącznie na braku Postgresa — sprawdza CI |
| Vitest: okno, edycja, schowek, karta ustawień, harnessy, inwentarz, rejestr ustawień, middleware | zielone lokalnie |
| `tsc --noEmit`, ESLint zmienionych plików, strażnik nieosiągalnych modułów | czyste |
| Harness `/preview/job-ad` w 1280 × 720: obie zakładki, blokada, „Usuń fragment”, edycja pola, pusty stan i przygotowanie, stan bez modelu | przeklikane, bez poziomego przewijania |

## Poza zakresem / do decyzji

- **Etap 2:** „Oznacz jako opublikowane” z linkiem (własna tabela, nie
  `job_postings`), kolumna „Ogłoszenia” na liście rekrutacji, plakietka
  „do aktualizacji”.
- **Odmienione nazwy klienta** („w Kwarcowym Banku”) kontrola łapie dopiero
  przez alias — tak samo jak strona kariery.
- **Strona kariery** nie zna nazwy wyświetlanej i prawnej klienta w kontroli
  treści; włączenie tego obróci część adresów linków.
- **Strona kariery nie dostała dopisków kontroli** (kwoty słownie, linki,
  telefon stacjonarny, znaki niewidoczne) — jej reguły zmieniłem tylko
  o wydajność wzorca. Te same luki są tam otwarte; to osobna decyzja, bo
  zaostrzenie odmówi zatwierdzenia części dziś przyjmowanych opisów.
- **Litery z innego alfabetu** podstawione w nazwie klienta (cyrylica
  zamiast łacińskiego „A”) kontrola przepuszcza.
- **Link aplikacyjny** `/r/<slug>` z UTM nie jest podawany w oknie — zgłoszenia
  z portali wpadają jak dotąd przez import.
- **Dwie treści:** publikacja przez API (za flagami) bierze zatwierdzony opis
  publiczny, okno — własną treść. Połączenie przy etapie 3.
