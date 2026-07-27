# Faza 1 — containment: raport z wykonania

**Data:** 2026-07-27 / 28
**Plan:** domknięcie audytu gotowości Sourcing/Pipeline do zastąpienia Traffit
**Punkt wyjścia:** `docs/sourcing-pipeline-traffit-replacement-readiness-audit-2026-07-27.md`
**Pomiary:** `docs/faza0-pomiary-produkcji-2026-07-27.md`

Faza 1 obejmowała pozycje, które trzeba było zamknąć **niezależnie od decyzji
o Traffit** — bronią systemu, którego zespół używa dziś. Program cutoveru
(Faza 3+) nie był w zakresie i nie został ruszony.

---

## Co weszło

| # | Zakres | PR | Stan |
|---|---|---|---|
| 1.2 | Odblokowanie E2E | [#959](https://github.com/artur-t-96/Nexus/pull/959) | ✅ wdrożone, **nightly 9/9 zielony** |
| 1.3 | Semantyka filtrów skilli | [#960](https://github.com/artur-t-96/Nexus/pull/960) | ✅ wdrożone, sprawdzone w Chrome |
| 1.4 | Resource scope na 23 trasach | [#963](https://github.com/artur-t-96/Nexus/pull/963) | ✅ wdrożone |
| 1.8 | Kwarantanna zatrutego wiersza + karta Traffit | [#968](https://github.com/artur-t-96/Nexus/pull/968) | ✅ wdrożone |
| 1.7 | Indeksowanie ścieżek zapisu + raport pokrycia | [#969](https://github.com/artur-t-96/Nexus/pull/969) | ✅ wdrożone, endpoint działa |
| — | Poprawki z review #968/#969 | [#972](https://github.com/artur-t-96/Nexus/pull/972) | ✅ wdrożone |
| 1.6 | Kolejka zgłoszeń + snapshot CV | [#970](https://github.com/artur-t-96/Nexus/pull/970) | auto-merge uzbrojony |
| 1.5 | Archiwum usuniętej rekrutacji | [#971](https://github.com/artur-t-96/Nexus/pull/971) | auto-merge uzbrojony |

---

## Najważniejsze ustalenia

### Audyt był rzetelny, ale w dwóch miejscach przeszacowany

**P0-13 (schema drift) — nie potwierdza się.** `/api/admin/schema-drift` zwraca
`schema_satisfies_orm: true`: zero brakujących tabel, kolumn, indeksów, kluczy
obcych i enumów. Zakładka Alembica (`0152` vs kod `0199`) to rozjazd księgowy —
lustro DDL w `entrypoint.sh` utrzymało schemat kompletny. Realna pozostałość
jest mniejsza i innego rodzaju: 78 rozjazdów nullability (baza **luźniejsza**
niż ORM) i 72 nadmiarowe tabele.

**§11.2 (CI ręcznie kuratorowane) — nieaktualne.** #952 zastąpił listę 285
plików auto-discovery z jawnym baseline'em `--ignore`. Pliki, które audyt
wymieniał jako „istniejące, ale niewpięte", siedzą w udokumentowanych
kategoriach (LIVE / FAILING / COLLECTION_ERRORS).

### Diagnoza `traffit=degraded` okazała się inna niż zakładano

324 błędy fazy `pipelines` to **odczyt sprzed poprawki** — fix (#921) wszedł
2026-07-27 o 13:32, a ostatni run tej fazy ruszył o 05:57.

Realny problem był głębszy i audyt go nie opisał: **jeden** kandydat
(`ext=48895`, kolizja e-maila na unikalnym `ix_candidates_email`) trzymał
`__daily__` na 2026-07-20 — siedem dni. Kod celowo nie przesuwa watermarku po
nieczystym runie (M2-IMP-01) i nie miał górnej granicy, więc:

1. okno delty rosło każdej nocy („delta" zmierzała do pełnego skanu),
2. `degraded` było permanentne, czyli sygnał stał się szumem,
3. **nowa awaria niczego by nie zmieniła** — status już mówił `errors`.

### Luka indeksu rośnie w czasie rzeczywistym

Pomiar z Fazy 0: 8 272 kandydatów poza indeksem. Pomiar tym samym endpointem
kilka godzin później: **8 477**. To nie jest statyczny dług — cztery ścieżki
zapisu produkowały nowych niewyszukiwalnych kandydatów w tempie kilkuset
dziennie. #969 to zatrzymuje.

---

## Czego review nie przepuściło

Automatyczny review złapał **trzy realne błędy**, w tym jeden, który
unieruchamiał całą wprowadzaną funkcję:

- **Kwarantanna była cicho martwa.** `total_errors - len(error_refs)` zakładało
  jeden błąd na wiersz. Wiersz padający dwa razy w jednym runie produkował
  fantomowy błąd „nieprzypisany", który blokuje zawsze — więc watermark nigdy
  by się nie zwolnił. Mechanizm wyglądałby na działający i nie robił nic.
- **Stored XSS.** `submitted_linkedin` z nieuwierzytelnionego formularza
  publicznego renderowany wprost w `<a href>`; `javascript:` wykonałby się w
  sesji rekrutera.
- **„Martwy kod", który gubił dane.** Warunek po funkcji czyszczącej listę w
  `finally` — ostatnia partia intencji reindeksu nie była commitowana.

Własne testy też się opłaciły: kontrakt zakresu z 1.4 wykrył `refresh_original_cv`
omijające choke point i nadpisujące CV dowolnego etapu, a test kolejności z 1.5
wyłapał mój błędny predykat AST łapiący dekorator trasy zamiast kasowania.

---

## Ograniczenia weryfikacji

Docker Desktop był wysycony przez równoległe sesje (28 kontenerów, `docker run`
z gołym `print` > 5 min), a systemowy Python to 3.9 przy projekcie na 3.12.
Pełny harness pytest szedł więc w CI, a lokalnie weryfikowałem:

- **wykonanie źródła funkcji w izolacji** (AST + `exec`) — nie kopii logiki,
  tego samego kodu: 15 asercji dla kwarantanny, 7 dla poprawki;
- **testy strukturalne AST** dla pokrycia ścieżek zapisu i archiwum;
- **semantykę SQL bezpośrednio na Postgresie 16** dla dopasowania skilli;
- **vitest + tsc + eslint** dla frontendu;
- **Chrome MCP** dla zmian widocznych dla użytkownika.

---

## Co zostaje otwarte

| Pozycja | Kto | Dlaczego |
|---|---|---|
| **1.1 Off-site backup** | **Artur** | Kluczy B2 nie wygeneruję. Brakuje `BACKUP_S3_ACCESS_KEY`, `BACKUP_S3_SECRET_KEY`, `BACKUP_AGE_PRIVATE_KEY`. **55 tys. kandydatów i ~136 tys. CV nadal bez kopii poza tym samym dyskiem.** |
| 1.9 RODO/DSAR | DPO/prawnik | Zakres i SLA przed implementacją. Anonymize/erase zwracają 409 — świadoma ochrona, ale nie zastępuje wykonalnego prawa podmiotu. |
| 1.4b Macierz cross-job | — | Behawioralny test 403 na żywej bazie; kontrakt strukturalny wszedł w #963. |
| Scalenie `ext=48895` | — | Kwarantanna zwolni watermark po 5 runach; scalenie ręczne zwolni go od razu. |
| Włączenie workera indeksu + backfill 8 477 | Artur | Kosztuje wywołania Voyage'a — decyzja operatorska, nie techniczna. |
| Twardy filtr skilli (2.1) | — | Zablokowany pomiarem: pokrycie Cortex 56,8% < progu 60%. |

---

## Stan produkcji na koniec fazy

```
status              healthy
database            healthy
m365                healthy
cortex              healthy
traffit             degraded   ← zwolni się po 5 runach kwarantanny
                                 albo od razu po scaleniu ext=48895
kandydaci w indeksie   46 945 / 55 422  (84,7%)
oferty w indeksie       3 862 / 4 079   (94,7%)
kolejka reindeksu      pending 0 / dead 0
nightly E2E            9/9 zielony
```
