# Dealbreaker-switche: twarde ukrywanie zamiast punktów (2026-08-18)

> Pomysł Artura: „switch, nie punkty, za elementy które mogą wykluczać osobę
> z rekrutacji — jak stawka". Punkty degradują, ale nie usuwają; kandydat za
> 250 PLN/h przy budżecie 120 nadal wypływa na listę. Te switche są twardą,
> ŚWIADOMIE włączaną wersją tych samych porównań, które scoring robi miękko.

## Trzy żelazne zasady (każda okupiona zmierzonym wypadkiem)

1. **Nieznany PRZECHODZI.** Wycinamy wyłącznie na POZYTYWNEJ wiedzy. Filtr
   stażu przy pokryciu 1,2% zredukował kiedyś lejek 11 091 → 45.
2. **Margines na negocjacje, zmierzony.** GT-loss na zamrożonych A+B (2 212
   par z historii decyzji): margines 0% ukryłby **44%** realnie dowiezionych
   kandydatów, +15% → 27%, **+30% → 14%**, +50% → 5%. Stawki są negocjowane
   w dół rutynowo — stąd default +30%, katalog zamknięty {0,15,30,50},
   switch domyślnie WYŁĄCZONY.
3. **Ukrywanie nigdy nie jest ciche.** `meta.hidden` z licznikami per powód
   → chipy „Ukryto N poza budżetem / N tylko-zdalnych" (reguła „awaria ≠
   pustka").

## Co weszło

**Switch budżetowy** (`exclude_over_budget` + `budget_margin_pct`).
Porównanie wyłącznie w jednej jednostce: `candidate.expected_rate_hourly`
(PLN/h, kanoniczna waluta; 8 673 kandydatów) vs budżet oferty PLN/h.
Budżet oferty = **nowe pole `jobs.rate_budget_hourly`** (migracja 0235 +
lustro w entrypoint; formularz oferty) z fallbackiem na stawkę Championa
(`rate_value`, 860 ofert). Legacy `salary_min/max` jest ignorowane — kolumna
ma NIEJEDNOZNACZNĄ jednostkę zależną od pochodzenia rekordu (formularz
podpisuje ją „PLN/h" z placeholderami 90/150, importy i seedy trzymają
PLN/mies. 12 000–35 000) — dokładnie dlatego warstwa salary jej odmawia
i dlatego nowe pole musiało powstać.

**Switch lokalizacji z wyborem źródła** (`location_source`: `all`/`cv`/`notes`)
— rozszerzenie ISTNIEJĄCEGO filtra lokalizacji rekomendacji, nie równoległy
mechanizm. Źródła: CV = kolumny `city`/`location` (81% pokrycia po backfillu
Fali 3); notatki = `preferences.locations[]` (8 145 kandydatów) + kierunki
relokacji `relocation.targets[]` — te drugie tylko gdy `willing` nie jest
False (kierunek, na który kandydat się NIE godzi, nie jest jego lokalizacją).

**Switch „praca z biura"** (`exclude_remote_only`). Źródło: strukturalne pole
`preferences.remote_only` z ekstrakcji rozmów (True u 1 382 — ci odmawiają
biura; False u 5 893; reszta nieznana i przechodzi). Zero nowych kosztów AI —
pole już istniało. Świadomie nie zgadujemy z wolnego tekstu.

## Powierzchnie

- **Rekomendacje na ofercie** (`/api/jobs/{id}/recommendations` +
  `SuggestedCandidatesWidget`): panel przełączników obok filtra lokalizacji,
  select źródła, select marginesu, chipy ukrytych. Switche wymuszają ścieżkę
  live (jak filtr lokalizacji — snapshot nie zna parametrów).
- **Talent Radar**: radar nie ma oferty, więc budżet PLN/h wpisuje rekruter
  wprost (pole + margines + checkbox „ukryj wyłącznie-zdalnych"); liczniki
  w pasku wyników.
- **Formularz oferty**: pole „Budżet PLN/h dla kandydata" (create + edit).

## Decyzje graniczne

- `budget_margin_pct` spoza katalogu → 422 (a nie ciche przycięcie).
- Switch budżetowy przy ofercie BEZ budżetu = no-op (brak budżetu to też
  „nie wiemy").
- Kandydat łapiący oba powody liczy się deterministycznie jako budżetowy
  (kolejność zamrożona testem — liczniki nie migrują między odczytami).
- Granica finansowa: budżet kandydacki PLN/h jest operacyjny (rekruter
  rozmawia o stawce z kandydatem; stawka Championa jest widoczna na karcie
  oferty). Cennik klienta pozostaje za VIEW_FINANCE — nietknięty.
- Filtr dopuszczalności (blacklisty/NDA/weta) idzie PRZED switchami —
  „recommended ⟹ assignable" zostaje; switche tylko zawężają dalej.

## Testy

24 nowe (`test_dealbreaker_filters.py`): nieznany-przechodzi dla każdej
ścieżki (brak stawki, obca waluta, brak notatek, `remote_only` null,
`cv_extracted_data` jako lista), matematyka marginesów na brzegach,
precedencja jawnego pola nad Championem, no-op bez budżetu, determinizm
liczników, źródła lokalizacji (cv/notes/all, relokacja-unwilling odpada),
katalog marginesów w schemacie radaru. Razem z powierzchniami: 139 zielonych.
