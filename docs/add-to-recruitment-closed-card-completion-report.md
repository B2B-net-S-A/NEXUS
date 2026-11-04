# „Dodaj do rekrutacji”: powód pominięcia i „Przywróć” — raport (12.10.2026)

## Zgłoszenie

Rekruterka i Delivery Lead nie mogły dodać osoby do otwartej rekrutacji. Okno
znikało, ekran pokazywał zielone „Nikogo nie dodano… Pominięto: 1”.

## Przyczyna (produkcja, tylko odczyt)

- Osoba miała w tej rekrutacji kartę „Odrzucony” sprzed czterech dni (historia
  z Traffita), a dodanie pomijało jako „już w rekrutacji” każdego, kto ma tam
  jakikolwiek wiersz etapu.
- Request istniał w dwóch rekrutacjach (założona w NEXUSIE i kopia z Traffita
  o innym tytule). Delivery Lead zamknął tę, w której rekruterka pracowała od
  rana; jej pięć kart zostało w zamkniętej rekrutacji.
- Skala: 6 596 par osoba–rekrutacja z samą zamkniętą historią w 185 otwartych
  rekrutacjach.

## Co się zmieniło

- Serwer (`api/proposals_bulk.py`): powód `closed_in_job` dla osoby, której
  karta stoi w „Zamkniętych”, z etykietą (etap, dzień, kto zamknął) i celem
  ruchu, który kartę przywraca. Tylko dla dodania przez człowieka; bez nowej
  ścieżki zapisu.
- Okno (`AddToRecruitmentDialog`): zostaje otwarte, gdy nikogo nie dodano albo
  jest zamknięta karta; „Przywróć” idzie ruchem karty (`usePipelineMoveCore`).
- Toast po dodaniu wymienia powody pominięcia.
- Reguła: `docs/claude/rekrutacja-tablica/dodaj-do-rekrutacji-zamknieta-karta.md`.

## Weryfikacja przed scaleniem

| Co | Wynik |
|---|---|
| Pełny bieg CI na gałęzi (12 shardów pytest, Vitest z pokryciem, build) | zielony |
| Trzy nowe testy z bazą (`test_process_entry_and_screening_attempt.py`): odrzucony → `closed_in_job` i ruch przywraca; zatrudniony → `already_in_job`; rekrutacja bez własnego szablonu | przeszły w CI |
| Testy bez bazy i strażnicy źródeł (kolejność blokad, zapis etapów, migawka CV, telemetria) | zielone lokalnie i w CI |
| Vitest okna, podsumowania, harnessów; `type-check` | zielone |
| Okno w harnessie `/preview/my-people` przy szerokości 1280 (zamknięta karta, jedna przywrócona, inny powód) | obejrzane, bez poziomego przewijania |
| Przegląd kodu (tylko blokery) | bez blokerów |

Niesprawdzone w przeglądarce: prawdziwy ruch „Przywróć” z oknem „Przenieś mimo
to” wewnątrz okna dodawania — test okna zastępuje hak ruchu atrapą, a układ
okien jest taki sam jak w kolejce Cpro.

## Poza zakresem

- Scalanie requestów otwartych podwójnie — osobna sesja.
- Inne wejścia z regułą „jakikolwiek wiersz = już w rekrutacji”:
  „Przypisz do rekrutacji” (`POST /api/candidates/{id}/assign-to-job/{job_id}`
  odpowiada `already_in_pipeline` także przy zamkniętej karcie, a ekrany
  pokazują sukces), promocja z shortlisty, „Dodaj championa”, wtyczka LinkedIn,
  filtry chowające takie osoby w wyszukiwaniu w rekrutacji.
- Ostrzeżenie przy zamykaniu rekrutacji z aktywnymi kartami.
