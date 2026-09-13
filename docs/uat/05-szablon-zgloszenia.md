# 05 — Szablon raportu z karty i zgłoszenia błędu

> Pliki lądują w `docs/uat/wyniki/<ID karty>/` (katalog poza gitem). Format jest stały,
> żeby agent Fali 3 mógł je zaczytać maszynowo (nagłówki i tabele niżej są kontraktem).

## A. `raport.md`

```markdown
# Raport UAT — {{ID karty}} {{nazwa}}

- **SHA testowany:** {{7 znaków}} (health w chwili startu: {{7 znaków}})
- **Tryb:** R | W
- **Data / czas:** {{YYYY-MM-DD HH:MM}} – {{HH:MM}} ({{minuty}} min)
- **Wykonawca:** {{agent/model | człowiek — rola}}
- **Persony (rola → ID użytkownika):** admin → 1, delivery_lead → 42, …
- **Sesja:** state.json | Chrome
- **Zużycie AI:** {{funkcja: przed → po}} (tylko karty z ai_actions)

## Podsumowanie

| Status | Liczba |
|---|---|
| PASS | n |
| FAIL | n |
| SKIP | n |

Zgłoszenia: P0 = n, P1 = n, P2 = n, P3 = n.

## Scenariusze

| ID | Persona | Status | Zgłoszenie | Uwagi (prawdziwa nazwa zakładki, odstępstwa od karty) |
|---|---|---|---|---|
| M07-S01 | delivery_lead | PASS | — | zakładka nazywa się „Zamówienia” |
| M07-S02 | finance | FAIL | M07-B01 | |
| M07-S09 | admin | SKIP | — | stop-lista: „Zakończ zamówienie” |

## Lista kontrolna E1–E10 — odstępstwa

| Ekran (trasa) | E# | Opis | Zgłoszenie |
|---|---|---|---|
| /clients/123?tab=zamowienia | E8 | kolumna „Akcje” ucięta przy 1366 px | M07-B03 |

## Zgłoszenia

(po jednym bloku według §B)

## Pominięte i dlaczego

- …

## Obserwacje niebędące błędami (do decyzji produktowej)

- …
```

## B. Zgłoszenie błędu (blok w `raport.md` + osobny `zgloszenia/<ID>.md` dla P0/P1)

```markdown
### {{ID karty}}-B{{nn}} — {{jedno zdanie: co jest nie tak}}

- **Priorytet:** P0 | P1 | P2 | P3 (definicje: 00-zasady §8)
- **Moduł / scenariusz:** M07 / M07-S02
- **Persona:** finance (ID 17), w podglądzie: tak/nie
- **SHA:** abc1234
- **Trasa:** /clients/123?tab=zamowienia
- **Kroki odtworzenia:**
  1. …
  2. …
- **Oczekiwane:** (cytat z karty albo z CLAUDE.md)
- **Faktyczne:** …
- **Dowód:**
  - zrzut: zrzuty/M07-B02-1366.png
  - żądanie: `GET /api/clients/123/order-groups` → 500, body: `{"detail":"…"}`
  - konsola: `TypeError: Cannot read properties of undefined (reading 'lines')`
  - Sentry: nexus-fe issue #NNN (jeśli znalezione)
- **Odtworzone drugi raz:** tak (P0/P1 obowiązkowo)
- **Dane:** tylko testowe / prawdziwe (ID, bez nazw)
- **Podejrzewane miejsce w kodzie (opcjonalnie):** frontend/src/components/…
```

## C. `utworzone.json` (tryb W)

```json
[
  { "endpoint": "/api/candidates", "id": 60123, "name": "[QA-E2E-2026-09-12] kandydat-a3f7", "created_at": "2026-09-12T10:14:00Z", "cleaned": false }
]
```

## D. `LOCK` (tryb W)

```
P2-zatrudnienie-umowa-kontrakt
started: 2026-09-12T10:00:00Z
agent: {{identyfikator}}
```

## E. Zbiorczy `wyniki/INDEX.md` (prowadzi orkiestrator lub człowiek)

| Karta | Status karty | PASS/FAIL/SKIP | P0 | P1 | P2 | P3 | Raport |
|---|---|---|---|---|---|---|---|
| M00 | done | 18/2/1 | 0 | 1 | 1 | 0 | M00/raport.md |
