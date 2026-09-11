# M03 — Rekrutacje i pipeline

| Pole | Wartość |
|---|---|
| Tryb | **R** (ruchy kandydatów, notatki, werdykty → przepływ P1) |
| Persony | recruiter (w zespole D3), tac, delivery_lead, head_of_recruitment, finance (podgląd); admin |
| Zależności | Fala 0 (D3, D4, D10); najlepiej PO P1 (wtedy D3 ma kandydatów na etapach) — jeśli przed, scenariusze S10–S18 na PRAWDZIWEJ rekrutacji tylko do odczytu |
| Czas | ~3 h |
| Głębokość | pełna |
| Akcje AI | nie (poza odczytem gotowych opisów) |

## Zakres

- `/jobs` — lista rekrutacji: filtry (Wszystkie / Body leasing / Sales / Przetargi; termin;
  Priority Work), sortowanie (Wg terminu, Od najnowszej/najstarszej), badge liczby.
- `/jobs/[id]` — szczegóły: dock gotowości (**Gotowość · Pipeline · Zespół · Wyszukiwania · Historia**),
  kanban etapów, shortlista, dock kandydata (**W procesie · Screening · CV · Dopasowanie · Notatki**),
  dock decyzji po rozmowie (**Decyzja · Oferta · Notatki · Historia**), przekazanie CV
  (**Przekazanie · Linki i historia**), zakładka kontraktu (**Po podpisie · Zamówienie · Alerty DL**),
  czat rekrutacji, ogłoszenia (Pracuj.pl / JustJoinIT / LinkedIn / NoFluffJobs / BulldogJob).
- `/jobs/[id]/prep/[candidateId]` — zestaw przygotowawczy do rozmowy.
- `/calendar` — kalendarz.
- `/pending-verifications` — oczekujące weryfikacje.

## Przed startem

ID D3, D4. ID jednej PRAWDZIWEJ, otwartej rekrutacji z ≥ 5 kandydatami na różnych etapach
(zapisz tylko ID). ID persony recruiter, która JEST w zespole D3 (dodaj ją w Fali 0) i
persony tac, która NIE jest.

## NIE KLIKAJ

Przeciąganie kart na kanbanie prawdziwej rekrutacji, „Odrzuć” (mail!), „Wyślij CV klientowi”,
„Utwórz link”, „Zapisz werdykt”, „Zaproś na rozmowę” (kalendarz → mail), „Publikuj ogłoszenie”,
„Zamknij rekrutację”, odpowiedzi w czacie.

## Scenariusze — lista `/jobs`

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S01 | recruiter | otwórz `/jobs` | nagłówek i menu mówią „Rekrutacje” (nie „Oferty”); lista < 5 s | P1 |
| S02 | recruiter | filtr typu: Body leasing / Sales / Przetargi; termin: Najbliższe 7/30 dni, Po terminie, Bez terminu | wyniki zmieniają się; licznik = wiersze; URL niesie filtr; F5 odtwarza | P2 |
| S03 | recruiter | sortowanie „Wg terminu” → rekrutacje po terminie na górze z oznaczeniem | oznaczenie czerwone/„Po terminie” | P2 |
| S04 | recruiter | wyszukaj „QA-E2E” | D3 i D4 | P1 |
| S05 | recruiter | karta rekrutacji: klient, DL, liczba kandydatów per etap, gotowość | dane zgodne ze szczegółami (wejdź i porównaj liczby) | P1 |
| S06 | head_of_recruitment | `/jobs` | wszystkie rekrutacje org-wide; BEZ kwot | P2 |
| S07 | finance | `/jobs` i `/jobs/{{D3}}` | pełny odczyt; brak przycisków ruchu poza tymi sprzed 31.08 | P2 |

## Scenariusze — szczegóły `/jobs/[id]` na D3

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S08 | recruiter | nagłówek: tytuł, klient D1, status, widełki 120–160 PLN/h, typ Body Leasing, DL | wszystko z Fali 0; „Rekrutacja” w breadcrumbach | P1 |
| S09 | recruiter | dock „Gotowość” | ✓ must-have, ✓ Champion, ✓ widełki, ✓ zespół; wskazówki po polsku | P1 |
| S10 | recruiter | dock „Zespół” | lista członków z rolami; recruiter widzi siebie; przycisk „Dodaj” widoczny dla ról z prawem (w podglądzie zapis 403) | P2 |
| S11 | recruiter | dock „Historia” | zdarzenia rekrutacji chronologicznie; utworzenie z Fali 0 obecne | P2 |
| S12 | recruiter | kanban: kolumny etapów szablonu (Default B2B) | wszystkie etapy widoczne; liczby w nagłówkach kolumn = liczba kart; **żadna karta nie ginie** (suma kart = liczba kandydatów w rekrutacji z nagłówka) | P1 |
| S13 | recruiter | najedź na kartę kandydata → dock kandydata → 5 zakładek | „W procesie”: etap, daty; „CV”: podgląd; „Dopasowanie”: pierścień; „Notatki”: lista; „Screening”: pytania z Championa (sekcja 5) | P1 |
| S14 | recruiter | dock kandydata → przycisk „dalej” (główny ruch) — **tylko sprawdź stan przycisku, nie klikaj** | dla kandydata z wetem HM: zatrzymuje się na „CV Wysłane” z powodem; dla karty „Oczekuje”: wszystkie ruchy zablokowane z powodem (`moveBlockedReason`) | P1 |
| S15 | recruiter | dock kandydata → stawka kandydata vs widełki | porównanie po przeliczeniu na miesięczną; waluta ≠ PLN → „nie do porównania”, nie „powyżej widełek” | P2 |
| S16 | recruiter | shortlista: pola tekstowe | **tylko czytaj**; wpisany tekst w podglądzie → 403 → tekst zostaje w polu | P2 |
| S17 | recruiter | „Przekazanie CV” → zakładka „Linki i historia” | historia linków (po P1 ≥ 1); URL jednorazowy w `OneTimeLinkField` z „Kopiuj”; **nie kopiuj do nikogo** | P2 |
| S18 | recruiter | werdykt HM (dock decyzji → „Decyzja”) | GET zwraca `{can_record, items}`; formularz renderuje się TYLKO gdy `can_record === true`; wiersze mają autora (rola+ID), `can_edit` | P1 |
| S19 | finance (spoza zespołu) | dock decyzji | werdykt tylko do odczytu, BEZ formularza (nie przycisk kończący się 403) | P1 |
| S20 | tac spoza zespołu D3 | `/jobs/{{D3}}` | odczyt rekrutacji; ruch kandydatów zablokowany z powodem „nie jesteś w zespole” | P1 |
| S21 | recruiter | zakładka kontraktu → „Po podpisie · Zamówienie · Alerty DL” | pusta lub z danymi po P2; alerty DL ładują się | P2 |
| S22 | recruiter | Champion (skrót do M04) | 6 sekcji renderuje się; sekcja 6 „O kliencie” ma link „Pełna karta klienta →” do Pomocy | P2 |
| S23 | recruiter | ogłoszenia | lista portali z statusami (Szkic/Aktywne/Wygasłe/Usunięte); **nie publikuj** | P3 |
| S24 | recruiter | czat rekrutacji | historia; **nie pisz** | P3 |
| S25 | recruiter | `/jobs/{{D3}}/prep/{{D5}}` | zestaw pytań/faktów; brak 500; powrót do rekrutacji działa | P2 |

## Scenariusze — prawdziwa rekrutacja (tylko odczyt)

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S26 | recruiter | kanban prawdziwej rekrutacji z ≥ 5 kandydatami | suma kart = liczba kandydatów; kandydaci na etapach nieznanych szablonowi NIE giną (mają kolumnę „Inne”/są widoczni) | P1 |
| S27 | recruiter | przewiń kanban w poziomie (wiele kolumn) | poziomy scroll w obrębie kanbanu; nagłówki kolumn przypięte | P2 |
| S28 | recruiter | dock kandydata prawdziwego → „Dopasowanie” | pierścień; w sieci brak 500 `MissingGreenlet`; sesja nie pada (zakładka nie wywala 500 po tym) | P1 |
| S29 | delivery_lead | ta sama rekrutacja | DL widzi werdykty HM i może je nadpisywać (przycisk „Edytuj” widoczny na cudzym werdykcie — w podglądzie zapis 403) | P2 |

## Scenariusze — kalendarz i weryfikacje

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S30 | recruiter | `/calendar` widok tygodnia/miesiąca | wydarzenia ładują się; klik w wydarzenie → szczegóły; **nie twórz** | P2 |
| S31 | recruiter | `/pending-verifications` | lista lub pusty stan PL; brak wpisów `[E2E-PendingVerif] DELETE ME` sprzed 27.05 (jeśli są — zgłoś jako śmieci do sprzątania, P3) | P3 |

## Kontrole API

```js
const tok=localStorage.getItem('access_token'); const h={Authorization:`Bearer ${tok}`};
const j = await fetch('https://api.nexus.dynaminds.pl/api/jobs/{{D3}}',{headers:h}).then(r=>r.json());
console.log(j.title, j.client_id, j.must_skills, j.nice_skills, j.rate_budget_hourly);
const k = await fetch('https://api.nexus.dynaminds.pl/api/pipeline/{{D3}}/kanban',{headers:h}); console.log('kanban', k.status);
const hm = await fetch('https://api.nexus.dynaminds.pl/api/jobs/{{D3}}/hiring-manager-feedback',{headers:h}).then(r=>r.json());
console.log('can_record', hm.can_record, 'items', hm.items?.length);
```
(Jeśli ścieżka kanbanu jest inna — odczytaj ją z zakładki sieci przy otwieraniu rekrutacji i zapisz w raporcie.)

## Znane pułapki

- Szablon „Default B2B” ma etapy, których legacy enum nie zna (np. „Preparation Meeting”) —
  serwerowe weto HM ich nie obejmuje; frontendowa bramka zatrzymuje się na „CV Wysłane”.
  Rozjazd między dockiem a serwerem = P1.
- Edycja rekrutacji (tytuł, rubryki) nie unieważnia cache gotowości — po edycji trzeba F5.
  Znany dług; zapisz jako obserwację, jeśli wystąpi.
- Kanban D&D w Chrome MCP nie zawsze działa (limit automatyzacji) — ruchy robimy w P1 przez API + weryfikacja UI.

## Do raportu

Zrzut kanbanu D3 i prawdziwej rekrutacji (1366 px), tabela „etap → liczba kart vs liczba
w nagłówku”, stany przycisku „dalej” (S14), wynik S18/S19.
