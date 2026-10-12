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
  nazwa klienta (także wyświetlana i prawna), kontakt, nazwisko, kwota
  z walutą albo stawką. Doradzają: nagłówki wewnętrznego formularza, liczby
  MD, numer zlecenia, wymaganie w jednym–dwóch słowach, braki.
- **Ręczne poprawki** każdego pola, warunków i poziomu technologii; zapis
  odświeża kontrolę i teksty do skopiowania.
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

## Weryfikacja

| Co | Wynik |
|---|---|
| Testy logiki backendu bez bazy (`test_job_ad_render`, `_lint`, `_generate`, lustro migracji) | 104 zielone lokalnie (Python 3.12) |
| Strażnicy repo bez bazy (sekcje tras, macierz uprawnień, inwentarz schematu, DDL entrypointu, rejestr modeli, stemple, indeks CLAUDE.md) | zielone lokalnie |
| Wzorzec uprawnień `tests/data/authz_golden/job_ads.json` | ogłoszenie: każda rola wewnętrzna; stałe bloki: admin i Head of Recruitment |
| Trasy z bazą (`test_job_ads_api.py`, 16 testów) | lokalnie padają wyłącznie na braku Postgresa — sprawdza CI |
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
- **Link aplikacyjny** `/r/<slug>` z UTM nie jest podawany w oknie — zgłoszenia
  z portali wpadają jak dotąd przez import.
- **Dwie treści:** publikacja przez API (za flagami) bierze zatwierdzony opis
  publiczny, okno — własną treść. Połączenie przy etapie 3.
