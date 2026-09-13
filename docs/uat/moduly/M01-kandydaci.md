# M01 — Kandydaci

| Pole | Wartość |
|---|---|
| Tryb | **R** |
| Persony | recruiter, sourcer, tac, talent_community_manager (podgląd); admin do porównania |
| Zależności | Fala 0 (kandydaci D5–D9) |
| Czas | ~3 h |
| Głębokość | pełna (główny moduł pracy rekrutera) |
| Akcje AI | tak, tylko odczyt cache (S22 „Podsumowanie aktywności” — NIE klikaj „Odśwież”) |

## Zakres

- `/candidates` — lista: filtry, sortowanie, kolumny, zapisane wyszukiwania, zaznaczanie, eksport, quick view.
- `/candidates/[id]` — profil: zakładki **Podsumowanie · Aktywność · Dopasowanie · Pliki i umowy · Maile** (+ zakładka Rozmowy jeśli CloudTalk włączony — nie jest).
- `/candidates/compare` — porównanie kilku kandydatów.
- `/candidates/bulk-import` — import CSV (tylko podgląd formularza; import w P1).
- `/candidates/contact-queue` — „Do przedzwonienia”.
- `/applications` — Zgłoszenia (publiczne formularze aplikacyjne).
- `/talents` — Talenty (pule talentów).
- `/sourcing/marketplace` (+ `?tab=seeking`), `/sourcing/seeking-contractors`, `/marketplace`, `/seeking` — Targ / Dostępni.

## Przed startem

ID kandydatów D5–D9. Jeden kandydat PRAWDZIWY z długą historią (wybrany losowo z listy,
zapisz tylko ID) — do testu wydajności zakładek; nie zapisuj o nim nic poza ID.

## NIE KLIKAJ

„Usuń kandydata”, „Wyślij mail”, „Odrzuć z mailem”, „Odśwież podsumowanie” (koszt AI),
„Anonimizuj/RODO”, „Scal duplikaty”, „Wrzuć na targ” (to P1), „Dodaj do rekrutacji” (P1).

## Scenariusze — lista `/candidates`

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S01 | recruiter | otwórz listę | ładuje się < 5 s; licznik łączny > 0; pierwszy ekran wierszy widoczny bez scrolla | P1 |
| S02 | recruiter | wyszukaj „Testowa”, „testowa”, „TESTOWA”, „Probny” | wszystkie znajdują odpowiednich kandydatów D5/D6 (bez rozróżnienia wielkości i diakrytyków) | P1 |
| S03 | recruiter | wyszukaj po e-mailu `anna.testowa@example.com` i po telefonie `000000001` | znajduje D5; telefon działa po ostatnich 9 cyfrach | P1 |
| S04 | recruiter | filtr „Status i dostępność” → każda wartość po kolei | wyniki się zmieniają; licznik = liczba wierszy; URL zawiera filtr; F5 odtwarza | P1 |
| S05 | recruiter | filtr etapu / rekrutacji → wybierz D3 | tylko kandydaci w D3 (po P1 będzie ≥ 1; przed — pusta lista z komunikatem „brak kandydatów spełniających filtry”, nie „brak kandydatów”) | P1 |
| S06 | recruiter | filtr „Kategoria kompetencji” → `software_development` | wyniki zawężone; chip filtra widoczny; „×” na chipie zdejmuje filtr | P2 |
| S07 | recruiter | filtr „Poprzednia firma” / firma z historii → wpisz nazwę firmy z CV D5 | D5 na liście | P2 |
| S08 | recruiter | tryb pracy: Zdalnie / Hybryda / Stacjonarnie; dostępność: 1/2/3 mies. | filtry łączą się AND; brak 500 przy każdej kombinacji | P2 |
| S09 | recruiter | sortowanie: Najnowsi, Najstarsi, A–Z, Trafność | porządek zmienia się widocznie; „Trafność” bez wyszukiwania nie wywala błędu | P2 |
| S10 | recruiter | kolumny: ukryj „Kontakt i CV”, dodaj „Ostatnia notatka”, „Skills”, „Powód odrzucenia”; F5 | ustawienie kolumn przeżywa odświeżenie (localStorage); tabela nie ma poziomego scrolla strony | P2 |
| S11 | recruiter | paginacja: strona 2, 3, ostatnia; zmiana rozmiaru strony | brak duplikatów między stronami (porównaj 3 ID); ostatnia strona niepusta | P2 |
| S12 | recruiter | zaznacz 3 kandydatów → „Eksport” | plik CSV/XLSX z DOKŁADNIE 3 wierszami; bez kolumn finansowych dla roli bez finansów | P1 |
| S13 | recruiter | zaznacz 2 → „Porównaj” | `/candidates/compare` z 2 kolumnami; kolumna „Dopasowanie” do wybranej rekrutacji renderuje liczbę lub „Ocena niepełna”/„nie policzono — ponów”, **nigdy 0 ani puste** | P1 |
| S14 | recruiter | quick view (klik w wiersz) → strzałki następny/poprzedni → Esc | quick view ma jedno „Zamknij”; nawigacja przechodzi granicę strony; po Esc fokus wraca na wiersz | P2 |
| S15 | recruiter | zapisane wyszukiwanie: „Filtry” → zapisz bieżące jako `[QA-E2E] filtr` — **tylko jeśli zapis nie wymaga mutacji w podglądzie; jeśli 403 → SKIP** | pojawia się w pickerze; wybór odtwarza filtry | P3 |
| S16 | admin | kolumna „Stawka” | admin widzi stawkę; recruiter w podglądzie — sprawdź [03-macierz-rol.md §4](../03-macierz-rol.md) (stawka kandydata to dane kandydackie, nie finansowe klienta — powinna być widoczna) | P2 |
| S17 | recruiter | kolumna „Ostatnia notatka” dla kandydata z notatką zawierającą @wzmiankę | tekst bez surowego JSON (Tiptap); wzmianka jako `@Imię` | P2 |

## Scenariusze — profil `/candidates/[id]`

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S18 | recruiter | otwórz D5 → każda z 5 zakładek | każda ładuje się; puste sekcje mają pusty stan PL, nie błąd | P1 |
| S19 | recruiter | nagłówek: badge kategorii kompetencji, status, dostępność, tagi | badge ma nazwę PL (nie slug `software_development`) | P2 |
| S20 | recruiter | Podsumowanie: doświadczenie, skille, edukacja z CV D5 | 3 role z CV; daty `MM.RRRR`; „obecnie” dla bieżącej roli; skille rozpoznane (Python, PostgreSQL, Docker) | P1 |
| S21 | recruiter | Pliki i umowy: podgląd CV (PDF w iframe), pobranie | podgląd renderuje; pobranie idzie z Bearer (nie goły URL → 401); D9 (bez CV) pokazuje pusty stan | P1 |
| S22 | recruiter | Podsumowanie → karta „Podsumowanie aktywności” | dla D5 pusty stan „brak podsumowania — kliknij Odśwież” (**nie klikaj**); dla kandydata prawdziwego z cache — tekst, data, bez JSON | P2 |
| S23 | recruiter | Aktywność: oś czasu | zdarzenia chronologicznie; import z Traffita opisany PL; notatki renderują format (nie surowy JSON) | P2 |
| S24 | recruiter | Dopasowanie: wybierz rekrutację D3 | pierścień z liczbą LUB „Ocena niepełna”; opis AI (jeśli jest) bez liczby punktów w tekście; brak 500 | P1 |
| S25 | recruiter | Maile | lista wątków lub pusty stan; **nie klikaj „Napisz”** | P3 |
| S26 | recruiter | kandydat prawdziwy z długą historią: każda zakładka | ładuje się < 8 s; brak `MissingGreenlet`/500 w sieci | P1 |
| S27 | recruiter | edycja pola (np. „Lokalizacja”) → Zapisz | w podglądzie 403 read-only → to oczekiwane; zapisz w raporcie, że formularz nie zgubił wpisanego tekstu po 403 | P2 |
| S28 | tac / tcm / sourcer | S18 + S21 dla D5 | identyczny zakres co recruiter; brak różnic w widocznych danych kandydata | P2 |
| S29 | finance (podgląd) | `/candidates` i profil D5 | pełny odczyt (decyzja 19.08); brak przycisków mutujących ruch kandydata poza tym, co miał przed 31.08 — zapisz, jakie przyciski są widoczne | P2 |

## Scenariusze — pozostałe trasy

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S30 | recruiter | `/candidates/contact-queue` | kolejka ładuje się; każdy wiersz ma akcje wyniku rozmowy; **nie loguj wyniku** | P2 |
| S31 | talent_community_manager | `/candidates/contact-queue` | dostępna (rola na liście); admin — pozycja menu NIEwidoczna (nie ma go w `roles`), ale trasa działa | P3 |
| S32 | recruiter | `/applications` | lista zgłoszeń z publicznych formularzy; filtr po rekrutacji; klik → szczegóły | P2 |
| S33 | recruiter | `/talents` | pule talentów; wejście w pulę → lista kandydatów; licznik = liczba | P2 |
| S34 | recruiter | `/sourcing/marketplace` → zakładki (w tym `?tab=seeking`) | obie zakładki ładują się; brak „no available server” (jeśli jest — infra, zapisz czas, sprawdź health) | P1 |
| S35 | recruiter | `/candidates/bulk-import` | formularz z opisem formatu CSV i przykładem; **nie wgrywaj** | P3 |
| S36 | recruiter | `/candidates/search` | patrz M02 (tu tylko: ładuje się) | P2 |
| S37 | recruiter | profil kandydata, któremu wgrano CV innej osoby (albo z innym nazwiskiem) — w Fali 0 tak było z D5 przed poprawą nazwiska | użytkownik WIDZI, że CV nie zasiliło profilu (komunikat, znacznik weryfikacji tożsamości) — nie ma cichego „CV wgrane”, a profil pusty. Brak sygnału = P2 | P2 |

## Kontrole API

```js
const tok = localStorage.getItem('access_token');
const h = {Authorization:`Bearer ${tok}`};
const q = await fetch('https://api.nexus.dynaminds.pl/api/candidates?q=QA-E2E&limit=50',{headers:h}).then(r=>r.json());
console.log('QA-E2E kandydatów:', q.total ?? q.items?.length);          // oczekiwane 5
const one = await fetch('https://api.nexus.dynaminds.pl/api/candidates/{{D5}}',{headers:h});
console.log(one.status);                                                 // 200
const cc = await fetch('https://api.nexus.dynaminds.pl/api/competence-categories',{headers:h}).then(r=>r.json());
console.log('kategorie:', cc.length);                                    // 5
```

## Znane pułapki

- Imiona z Traffita bywają „?” (brak imienia w źródle) — dla prawdziwych kandydatów to
  znany stan (faza `candidates_enrich_names`), nie błąd UI. Dla D5–D9 „?” = P1.
- Markery statusu wklejone w imiona z importu („Jan Kowalski (niedostępny)”) — znany dług,
  zapisz jako obserwację, nie P1.
- Podgląd PDF w iframe wymaga parametrów w URL — jeśli iframe pusty, sprawdź w sieci status
  żądania pliku (401 = brak Bearer = błąd; 200 + pusty = błąd renderowania).

## Do raportu

Czasy ładowania listy i profilu (S01, S26), zrzut listy przy 1366 px z domyślnymi kolumnami,
lista przycisków widocznych dla finance w profilu (S29).
