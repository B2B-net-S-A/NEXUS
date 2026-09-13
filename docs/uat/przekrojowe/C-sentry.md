# C — Kontrola przekrojowa: Sentry, logi, konsola

| Pole | Wartość |
|---|---|
| Tryb | **R** (Sentry MCP / API tylko odczyt) |
| Persony | — (narzędzia) |
| Zależności | Fala 0 §2.3 baseline; działa RÓWNOLEGLE z kartami modułów przez całą Falę 1 i 2 |
| Czas | 30 min na start + 15 min po każdym zakończonym module + 30 min na koniec fali |
| Głębokość | pełna |
| Akcje AI | nie |

## Cel

Karty modułów widzą to, co na ekranie. Sentry widzi to, co padło po stronie serwera i w
przeglądarkach PRAWDZIWYCH użytkowników. Ta karta wiąże jedno z drugim: każdy nowy issue
w oknie testów dostaje przypisanie „który moduł / scenariusz go wywołał” albo „użytkownik
produkcyjny” (co jest jeszcze ważniejsze).

## Narzędzia

- `mcp__sentry__search_issues` / `get_sentry_resource` (jeśli MCP dostępny) albo panel Sentry.
- Filtry: projekt `nexus-be` i `nexus-fe`; `release:{{tested_sha}}` (pełny SHA); `is:unresolved`.
- Grafana Loki (jeśli MCP): `{app="nexus"} |= "ERROR"` w oknie modułu.
- `/api/health` co godzinę (skrypt) → `wyniki/C/health-log.jsonl`.

## Procedura

### C0 — start fali (30 min)

1. Zapisz baseline: wszystkie `is:unresolved` z `lastSeen:-7d` dla obu projektów →
   `wyniki/C/baseline.json` (id, title, count, users, lastSeen, release).
2. Zapisz `firstSeen` najnowszego issue — od tej chwili każdy nowszy jest „w oknie UAT”.
3. Sprawdź alert rules (`docs/sentry-alerts-runbook.md`) — istnieją? Jeśli nie → obserwacja P2 do Fali 3.

### C1 — po każdym zakończonym module (15 min)

1. `firstSeen:-{{czas modułu}}` dla `release:{{sha}}` → nowe issue.
2. Dla każdego: stacktrace → endpoint/komponent → dopasuj do scenariusza z raportu modułu
   (czas + trasa). Dopisz do zgłoszenia modułu `Sentry: <id>` ALBO utwórz nowe zgłoszenie
   `C-Bnn` z priorytetem wg wpływu:
   - `users ≥ 2` spoza testerów → **P1** (pada ludziom),
   - 5xx z naszego scenariusza → P1 (jeśli scenariusz był PASS na ekranie — „awaria udająca sukces”, podnieś do P1 i wróć do modułu),
   - `warning`/`info` → P3.
3. Sprawdź, czy issue z baseline NIE eskalują (`count` × 2 w oknie) — jeśli tak, P1.

### C2 — konsola i sieć (dla agentów modułów — przypomnienie)

Każdy agent modułu zapisuje `console.error` i żądania 4xx/5xx per trasa. Karta C zbiera te
pliki (`wyniki/M*/konsola.jsonl`) i grupuje po komunikacie. Powtarzalny `console.error`
na ≥ 3 trasach = jedno zgłoszenie P2 (nie 3).

### C3 — koniec fali (30 min)

1. Tabela: `issue → moduł/scenariusz → zgłoszenie → priorytet`.
2. Issue bez dopasowania do żadnego scenariusza i bez użytkowników produkcyjnych → „szum tła” (P3, lista).
3. Issue z użytkownikami produkcyjnymi w oknie → osobna sekcja „pada ludziom teraz” — na górę raportu Fali 3.
4. `health-log.jsonl`: każde odejście od `healthy` z czasem → dopasuj do deployów (`gh run list --workflow deploy.yml`).

## Wynik — `wyniki/C/raport.md`

```markdown
## Pada ludziom teraz (users ≥ 2, okno UAT)
| Sentry ID | Projekt | Tytuł (skrót) | users | count | endpoint | Zgłoszenie |

## Wywołane przez UAT
| Sentry ID | Moduł/Scenariusz | Tytuł | Zgłoszenie |

## Baseline — eskalacje
| Sentry ID | count przed | count po | Zgłoszenie |

## Szum tła (P3)
…

## Health w czasie
| czas | status | pozycje ≠ healthy | deploy w pobliżu? |
```

## Znane pułapki

- Sentry ma ~5 min opóźnienia — po scenariuszu poczekaj przed C1.
- Replay jest zamaskowany (RODO) — nie oczekuj tekstu w nagraniach.
- `release` = pełny 40-znakowy SHA (`GIT_SHA`), health pokazuje pełny; porównuj po prefiksie 7.
- Wygasła sesja (401) generuje w `nexus-fe` breadcrumby, nie issue — nie zgłaszaj.
