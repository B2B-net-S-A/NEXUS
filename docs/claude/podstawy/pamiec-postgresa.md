# Pamięć Postgresa: bufor, pule połączeń i autovacuum w jednym limicie

25.11.2026 o 10:19 jądro zabiło proces bazy, bo kontener Postgresa doszedł do `mem_limit`
(OOM cgroupa, `memory.events`: `oom_kill 1`). Baza przeszła crash recovery w ok. 3 s,
a 38 żądań dostało 500, w tym zapisy screeningu i ruch kart. Kontener nie ma swapu,
więc pamięci, której nie da się odzyskać, nie może być więcej niż limit.

## Co liczy się w limicie

- **Cały `shared_buffers` jako shmem.** Pamięć współdzielona to `shared_memory_size`
  (8409 MB przy 8 GB). Baza restartuje się przy każdym wdrożeniu compose, a bufor
  zapełnia się przez kilka godzin pracy, więc szczyt przypada w dzień, nie po wdrożeniu.
- **Każde trzymane połączenie, ok. 35 MB.** Pamięć prywatna backendu (RssAnon: mediana
  28 MB, cache katalogu i planów) plus tablice stron. Shmem jest mapowany stronami 4 kB
  (`huge_pages=try` na tym hoście nie działa), więc backend płaci 2 MB tablic za każdy
  GiB bufora, którego dotknął. Bezczynne połączenie w puli nie jest darmowe.
- **Autovacuum**: do `autovacuum_work_mem` na każdy z 3 workerów. Domyślne `-1`
  oznaczało `maintenance_work_mem`, czyli 1 GB na worker.
- **Zapytania**: `work_mem` na każdy węzeł sortowania i hasha (hash × 2), osobno w każdym
  workerze zapytania równoległego, plus segmenty `/dev/shm`. Na to zostaje zapas.
- Page cache plików bazy w tym samym limicie da się odzyskać, więc go nie liczymy.

## Pomiar 25.11.2026 i decyzja

`memory.stat` o 14:01, przy 110 połączeniach (95 z pul NEXUSA, pule web pełne: 2 × 40):

| | GiB |
|---|---:|
| anon | 2,58 |
| shmem (bufor prawie pełny) | 7,27 |
| jądro (w tym tablice stron 0,79) | 0,89 |
| page cache poza shmem (do odzyskania) | 1,31 |
| `memory.current` / `memory.max` | 11,97 / 12 |

Przy pełnym buforze zostawało ok. 0,22 GiB. Decyzja Artura z 25.11.2026: trzy zmiany
naraz, wdrożone wieczorem tego dnia.

| | zapas przy pełnym buforze | gdy każde połączenie dotknie całego bufora |
|---|---:|---:|
| przed (8GB, pula web 40+10) | 0,22 GiB | −0,66 GiB |
| po (6GB, pula web 20+30, autovacuum 256MB) | 3,67 GiB | 3,26 GiB |

Autovacuum w najgorszym razie bierze 0,75 GiB zamiast 3 GiB.

- **Pula web 20+30 zamiast 40+10.** Szczyt 50 na proces bez zmian, więc budżet
  `max_connections` też. Proces web używał w minucie mediany 11 połączeń, p90 18–20,
  ponad 20 w 6–8% minut (`runtime_metrics` 25.11, 05:46–12:17 UTC). Pula trzyma
  `pool_size` połączeń przez cały dzień, a w tych minutach otwiera i zamyka nadmiar,
  co najmniej ok. 1,4 połączenia na minutę. Liczba ok. 95 na minutę z 27.10.2026
  (`database.py`) dotyczyła jednego procesu z HTTP i wszystkimi pętlami.
- **`shared_buffers` 6GB.** Baza ma 24 GB. Do 14:11 bufor zebrał 7,5 GiB bez wyrzuceń
  (`pg_stat_io`). Przy 6 GB wyrzucenia zaczną się wcześniej, ale odzyskane 2 GiB zostaje
  w limicie jako page cache, więc ponowny odczyt to kopia z pamięci, nie dysk.
- **Bez podnoszenia `mem_limit`.** 14g dawało 2,22 GiB zapasu, ale suma limitów
  kontenerów rosła do 30,5 GiB przy 31,3 GiB hosta bez swapu, a Coolify, system
  i budowanie obrazów przy wdrożeniu limitu nie mają. Ryzyko przeszłoby na globalny
  OOM hosta, w którym jądro wybiera ofiarę samo.

## Budżet przy zmianie

`test_prod_postgres_memory_leaves_headroom` w `backend/tests/test_process_roles.py` liczy:
bufor × 8409/8192 + trzymane połączenia × 35 MiB (pule web × `WEB_PROCESSES_MAX`,
pula workera, 16 pozostałych) + 3 × `autovacuum_work_mem` + 0,1 GiB jądra. Wynik
musi zostawić 2 GiB pod `mem_limit`. Więcej procesów web, większa pula albo większy
bufor muszą się w tym zmieścić. Stałe pochodzą z pomiaru 25.11 i zmieniają się tylko
po nowym pomiarze.

Huge pages zdjęłyby tablice stron, ale wymagają `vm.nr_hugepages` na hoście i zmieniają
rozliczanie tej pamięci w cgroupie. To osobna decyzja, nie poprawka w compose.

## Jak sprawdzić

`~/.claude/nexus-rutyny/bin/prod_readonly.py pg-memory` wypisuje `memory.stat`,
`memory.events`, `memory.current`, `memory.max` i `memory.peak` cgroupa Postgresa.
Zapas = `memory.max` − (`anon` + `shmem` + `kernel`). Licz go w dzień roboczy ok. 12:00,
kiedy bufor jest pełny, nie zaraz po wdrożeniu. `oom_kill` większe od 0 to OOM od startu
kontenera. W SQL ślad po awarii to `stats_reset` w `pg_stat_bgwriter` późniejszy niż
`pg_postmaster_start_time()`.
