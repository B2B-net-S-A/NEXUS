# Faza 0 — pomiary produkcji (2026-07-27)

Cztery pomiary bramkujące decyzje z planu domknięcia audytu gotowości.
Tryb: **read-only** (`SELECT` + endpointy raportowe). Zero zapisów, zero mutacji.

Kod produkcyjny w czasie pomiaru: `8139496b` → `2d6c3563` (redeploy w trakcie).
Dostęp: SSH kluczem roota z Coolify API + `X-Snapshot-Token` do `/api/admin/schema-drift`.

---

## 1. Pokrycie faktów Cortex — **56,8%** (poniżej progu)

| Metryka | Wartość |
|---|---|
| Kandydaci ogółem | 55 217 |
| Kandydaci aktywni (`status <> 'blacklisted'`) | 55 217 |
| Kandydaci z ≥1 wpisem w `cortex_skill_facts` | **31 337** |
| Wiersze faktów | 273 804 |
| Kanoniczne skille / aliasy | 196 / 458 |

**Pokrycie: 31 337 / 55 217 = 56,8%.**

**Decyzja:** próg z planu to 60%, więc **twardy filtr skilli (2.1) czeka na backfill Cortex**.
Uruchomienie go dziś odcięłoby 43% bazy od wyników. Krok 1.3 (przeetykietowanie na
„preferowane") zostaje bez zmian i jest tym pilniejszy — obietnica w UI jest dziś nieprawdziwa
dla ponad połowy bazy.

---

## 2. `traffit=degraded` — trzy przyczyny, jedna już naprawiona

Sync **działa** — ostatni run zakończył się 2026-07-27 08:25 UTC. Status `degraded` nie oznacza
zatrzymania importu, tylko że jakaś faza zgłosiła błędy wierszowe.

| Faza | Status | Błędy | Przetworzone |
|---|---|---|---|
| `pipelines` | errors | **324** | 179 288 |
| `candidates` | errors | 1 | 873 |
| `candidates_enrich_names` | errors | 1 | 29 |
| pozostałe 11 faz | ok | 0 | — |

### 2a. `pipelines` — 324 błędy, przyczyna już usunięta

Jedyny CHECK na `candidate_stages`:

```
ck_candidate_stages_withdrawn_requires_reason
CHECK ((stage <> 'withdrawn') OR (rejection_reason_id IS NOT NULL))
```

Importer wstawiał etapy `withdrawn` bez `rejection_reason_id` → `CheckViolationError` na każdym
z 324 etapów, przy każdym syncu.

**To jest już naprawione** — warstwowy fallback (`WithdrawnReasonFallback`: `by_job` →
`by_stage_def` → `default_id`) wszedł w `1e08bf16` (#921) **2026-07-27 13:32**, a ostatni run
fazy `pipelines` ruszył o **05:57 UTC** — czyli ~5,5 h przed istnieniem poprawki. Fix jest
przodkiem wdrożonego SHA. **Liczba 324 to nieaktualny odczyt sprzed poprawki**; pierwszym
runem z fixem będzie najbliższy sync o 02:00 UTC.

### 2b. `candidates` — 1 zatruty rekord (kolizja tożsamości e-mail)

`upsert candidate ext=48895: UniqueViolationError`. Rekord istnieje w NEXUS
(`candidates.id=128105`, `external_source=traffit`, utworzony 2026-05-28, `email IS NULL`).

Indeksy unikalne na `candidates`:
- `ux_candidates_external_source_id` — **partial**, `(external_source, external_id) WHERE external_id IS NOT NULL`; klauzula `ON CONFLICT` importera pasuje do niego dokładnie, więc to nie tu;
- `ix_candidates_email` — **UNIQUE bez predykatu** na `email`.

Czyli: UPDATE próbuje ustawić rekordowi 128105 e-mail, który w NEXUS należy już do **innego**
kandydata. Zapytanie o duplikaty zwraca 0 grup właśnie dlatego, że update pada i duplikat nigdy
nie powstaje. To pojedyncza kolizja tożsamości do rozstrzygnięcia scaleniem
(`scripts/merge_duplicate_candidates.py` już istnieje).

### 2c. Konsekwencja, której audyt nie opisał: **watermark zamrożony od 7 dni**

`app/tasks/traffit_sync.py:347,372` — `status = "errors" if any_error else "ok"`, a watermark
`last_synced_at` przesuwa się **wyłącznie po czystym runie** (świadoma decyzja: nieudany rekord
nie ma wypaść z okna lookbacku).

| Marker | `last_synced_at` | Wiek |
|---|---|---|
| `__daily__` | 2026-07-20 05:13 UTC | **7 dni 14 h** |
| `__full__` | 2026-07-19 04:01 UTC | **8 dni 16 h** |

Skutki:
1. okno delty rośnie każdej nocy — „delta" zmierza do pełnego skanu;
2. `traffit=degraded` jest **permanentne**, dopóki istnieje choć jeden nieusuwalny błąd wierszowy;
3. status już jest `errors`, więc **nowy** błąd nie zmienia sygnału i przechodzi niezauważony.

Intencja projektowa jest słuszna, ale brakuje zaworu: jeden trwale niemożliwy do zaimportowania
rekord blokuje watermark w nieskończoność. Potrzebna kwarantanna / ograniczona liczba prób, żeby
zatruty wiersz nie zamrażał całego potoku.

**Zakres zadania 1.8 (doprecyzowany):** (a) potwierdzić czysty przebieg `pipelines` po najbliższym
syncu; (b) scalić kolizję ext=48895; (c) zdiagnozować 1 błąd `enrich_names`; (d) dodać kwarantannę
zatrutych rekordów; (e) karta Traffit w Ustawieniach.

---

## 3. Schema drift — **schemat spełnia ORM w całości**

`GET /api/admin/schema-drift` (`auth_mode: token`, `drift-v1`, 2,3 s):

| Sprawdzenie | Wynik |
|---|---|
| `missing_tables` | **0** |
| `missing_columns` | **0** |
| `missing_indexes` | **0** |
| `missing_foreign_keys` | **0** |
| `missing_enum_types` / `missing_enum_values` | **0** / **0** |
| `nullability_mismatch` | 78 |
| `extra_tables` | 72 |
| **`schema_satisfies_orm`** | **`true`** |
| `singular_head_resolves` | `true` (225 rewizji, 1 głowa) |

**To rozstrzyga P0-13 z audytu.** Zakładka Alembica (`0152`) vs głowa kodu (`0198`) jest wyłącznie
rozjazdem księgowym — lustro DDL w `entrypoint.sh` (154 × `ADD COLUMN IF NOT EXISTS`, 45 ×
`CREATE TABLE IF NOT EXISTS`) utrzymało schemat kompletny. Teza audytu o „nieodtwarzalnym stanie
schematu" **nie potwierdza się**.

Realna pozostałość, mniejsza i innego rodzaju:
- **78 rozjazdów nullability** — ORM zakłada `NOT NULL`, DB pozwala na `NULL` (baza jest
  *luźniejsza*, nie uboższa). Większość w tabelach `dr_*` (dynareporter). Ryzyko jest latentne:
  zapis, który ORM by odrzucił, baza przyjmie.
- **72 nadmiarowe tabele**, w tym `_alembic_backup_pre_heal` — pozostałości po wcześniejszych
  naprawach.
- `singular_head_resolves: true` → `alembic upgrade head` w `backup-drill.yml` zadziała.

Uporządkowanie zakładki zostaje w M5 (na odtworzonej kopii), zgodnie z planem. Nie jest to bloker
Fazy 1.

---

## 4. Pokrycie indeksu — **85,0% kandydatów**

| Kolekcja | Punkty | Status |
|---|---|---|
| `nexus_candidates` | **46 945** | green |
| `nexus_jobs` | 3 862 | green |
| `nexus_pool_centroids` | 84 | green |
| `nexus_cc_centroids` | 5 | green |

**Kandydaci: 46 945 / 55 217 = 85,0% → luka 8 272 osób.**
**Oferty: 3 862 / ~4 075 = 94,8% → luka ~213 ofert.**

To kwantyfikuje P0-04: ponad 8 tys. kandydatów jest w bazie i na liście, ale **nie istnieje**
w rekomendacjach, hybrid searchu ani w dopasowaniach Marketplace. Zadanie 1.7 potrzebuje więc
zarówno dopięcia czterech ścieżek zapisu, jak i jednorazowego backfillu tej luki.

---

## Wpływ na plan

| Ustalenie | Zmiana |
|---|---|
| Cortex 56,8% < 60% | **2.1 (twardy filtr skilli) zablokowany** do czasu backfillu Cortex. 1.3 bez zmian. |
| `pipelines` naprawione przed pomiarem | **1.8 znacznie mniejsze**, niż zakładano — zostaje 1 scalenie + 1 diagnoza + kwarantanna + karta UI |
| Watermark zamrożony 7 dni | **Nowa pozycja w 1.8**: kwarantanna zatrutych rekordów (jeden wiersz nie może blokować potoku) |
| `schema_satisfies_orm: true` | **P0-13 potwierdzony jako przeszacowany.** Zostaje w M5, nie w Fazie 1. Doszła drobna pozycja: 78 rozjazdów nullability |
| Indeks 85% | **1.7 rośnie o backfill** 8 272 kandydatów + ~213 ofert |
