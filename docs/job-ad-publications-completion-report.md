# Ogłoszenie na portale — „Oznacz jako opublikowane” i kolumna „Ogłoszenia” (etap 2)

Data: 13.10.2026 · Migracja: 0432 · Reguły: `docs/claude/rekrutacja-tworzenie/ogloszenie-na-portale-kopiuj-wklej.md`
· Etap 1: `docs/job-ad-generator-completion-report.md` (PR #2158)

## Po co

Po etapie 1 rekruter ma treść do wklejenia, ale NEXUS nie wiedział, czy i gdzie
ogłoszenie wisi. Nie było widać, które rekrutacje mają ogłoszenie, które
ogłoszenie ma już nieaktualną treść i które wisi mimo zamkniętej rekrutacji.

## Co powstało

- **„Oznacz jako opublikowane”** w oknie „Ogłoszenie na portale” (nad polami
  zakładki) i w zakładce „Zespół i ogłoszenie” Profilu Championa: osobno dla
  Pracuj.pl i JustJoin.IT, z opcjonalnym linkiem do ogłoszenia. Widać, kto
  i kiedy oznaczył.
- **„Do aktualizacji”**: gdy zapisana treść ogłoszenia zmieni się po
  oznaczeniu, portal dostaje plakietkę i przycisk „Zaktualizowane na portalu”.
- **„Zdjęte z portalu”** z potwierdzeniem; ślad zostaje („Zdjęte z portalu
  13.10.2026”), a ogłoszenie można oznaczyć ponownie.
- **Kolumna „Ogłoszenia” na liście rekrutacji**: plakietki „Pracuj” i „JJIT”,
  z linkiem otwierającym ogłoszenie w nowej karcie. Żółta plakietka = treść
  do aktualizacji albo rekrutacja zamknięta, a ogłoszenie nadal wisi.
- **Zamknięta rekrutacja** z wiszącym ogłoszeniem: okno, sekcja i lista
  przypominają o zdjęciu. NEXUS sam niczego na portalu nie zmienia.

## Decyzje w trakcie

| Decyzja | Powód |
|---|---|
| Własna tabela `job_ad_publications`, nie `job_postings` | `job_postings` to kolejka workera publikacji przez API — ręczny wiersz dostałby zlecenie wysyłki, a przy Pracuj.pl blokował usunięcie rekrutacji |
| Link tylko z domeny portalu (`pracuj.pl`, `justjoin.it`) i opcjonalny | Odnośnik z listy prowadzi na zewnątrz; ogłoszenie na Pracuj.pl bywa widoczne dopiero po moderacji |
| „Do aktualizacji” liczy się z zapisanej treści ogłoszenia, nie z danych rekrutacji | Lista liczy to jednym zapytaniem na stronę; o zmianie rekrutacji mówi baner w oknie |
| Treści z fragmentem blokującym nie da się oznaczyć | Takiej treści nie wolno było wkleić |
| Stan ogłoszeń w sekcji widzi rola, która przygotowuje ogłoszenia | Pozostałe role nie mają tam żadnej akcji |
| Przewodnik Jarvisa: tylko jedno zdanie w opisie listy | Oba ekrany mają komplet zadań (5) i pułapek (4) — limit schematu |

## Poprawki po przeglądzie kodu i bezpieczeństwa (przed otwarciem PR-a)

| Znalezisko | Poprawka | Dowód |
|---|---|---|
| Link „https://obca.strona\.pracuj.pl/…” przechodził walidację: `urlsplit` widzi host z domeny portalu, przeglądarka czyta „\” jak „/” i otwiera obcą stronę | Serwer odrzuca ukośnik wsteczny, port, dane logowania i host spoza ASCII; front sprawdza adres parserem przeglądarki przy samym odnośniku (`portalAdHref`) | `test_anything_else_is_refused_in_polish` (+10 przypadków), `job-ad-portal-href.test.ts`, test komórki listy; porównanie różnicowe z parserem WHATWG: 260 460 kandydatów, 12 139 przyjętych, 0 prowadzących poza portal |
| Błąd `urlsplit` (np. nawiasy w hoście) wracał w 422 po angielsku | Jeden komunikat po polsku | ten sam test |
| „Dodaj link” / „Zmień link” po cichu gasiło „do aktualizacji” i nadpisywało, kto i kiedy opublikował — to samo wywołanie co „Zaktualizowane na portalu” | Zmiana linku przy aktywnym oznaczeniu zmienia tylko link; potwierdzenie treści to osobna flaga `content_updated`; data publikacji zostaje | `test_adding_a_link_does_not_confirm_the_content_or_change_who_published`, `test_blocked_content_cannot_be_confirmed_but_the_link_can_change` (CI), test „dopisanie linku nie potwierdza treści” |
| Odpowiedź po ponownym oznaczeniu zależała od tego, czy sesja nie trzyma starego obiektu | Odczyt z `populate_existing` | testy tras (CI) |
| Zmiana treści w oknie nie odświeżała kolumny „Ogłoszenia” (do 30 s) | Okno odświeża listę, gdy rekrutacja ma aktywne ogłoszenie | — |

## Weryfikacja

| Co | Wynik |
|---|---|
| Testy bez bazy: `test_job_ad_publications.py` (odcisk, link), lustro migracji 0432 | zielone lokalnie |
| Strażnicy: sekcje tras, macierz uprawnień (dwie nowe trasy jak pozostałe trasy ogłoszenia), inwentarz schematu, DDL entrypointu, stemple przewodników | zielone lokalnie |
| Trasy z bazą (`test_job_ads_api.py`, +5 testów: oznaczenie, „do aktualizacji”, zdjęcie i powrót, odmowy, lista i szczegół) | sprawdza CI |
| Vitest: `AdPublications`, okno, komórka listy, nagłówki tabeli, harnessy, inwentarz funkcji | zielone lokalnie |
| `tsc --noEmit` | czysty |
| Harnessy w 1280 × 720: lista (`/preview/jobs-list-v3`), sekcja (`/preview/champion-workspace?ptab=team`), okno (`/preview/job-ad?state=published`: „Zaktualizowane na portalu”, oznaczenie z linkiem w zakładce JustJoin.IT) | przeklikane, bez poziomego przewijania |

## Do decyzji

- **Szerokość listy na laptopie.** Kolumna „Ogłoszenia” ma 89 px. Na ekranie
  1280 px z rozwiniętym menu kolumna „Rekrutacja” zwęża się z 293 do 204 px
  (tytuły mocniej ucinane; wysokość wierszy bez zmian, brak poziomego
  przewijania). Alternatywa bez kosztu szerokości: plakietki portali pod
  nazwą stanowiska, obok kategorii i klienta, bez osobnej kolumny.

## Poza zakresem

- Publikacja przez API i publikowanie przez Delivery Leada przy tworzeniu
  rekrutacji (etap 3).
- Filtr listy „ma ogłoszenie / do aktualizacji”.
- Powiadomienie o ogłoszeniu wiszącym po zamknięciu rekrutacji (dziś samo
  przypomnienie w oknie, sekcji i na liście).
