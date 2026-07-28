# Raport z sesji 2026-07-28

Dokument opisuje, co zostało zmienione, **co zmierzono** i co zostało otwarte.
Liczby pochodzą z produkcji (55 428 kandydatów), nie z oszacowań.

---

## 1. Kopia zapasowa poza serwerem — pierwsza, która naprawdę istnieje

**Stan przed:** kopia lokalna działała, ale leżała **na tym samym dysku** co baza.
Kopia off-site nigdy nie powstała — skrypt meldował sukces na wartościach
zastępczych i kończył się kodem 0. 136 tys. plików CV kandydatów nie miało
żadnej kopii poza serwerem.

**Stan po** (manifest `LATEST.json`, 12:04:35 UTC):

| artefakt | obiekty | rozmiar |
|---|---|---|
| `cv_corpus` | 139 106 | 41,16 GB |
| `postgres` | 1 | 290 MB |
| `uploads` | 1 | 411 MB |
| `qdrant` (4 kolekcje) | 4 | 334 MB |
| | | `failures: 0` |

Liczba obiektów i bajtów zgadza się **co do jednego** ze źródłem na serwerze.

**Co blokowało.** Backblaze egzekwuje limity **odmową żądania** (403), nie
rachunkiem. Objaw wygląda identycznie jak brak uprawnień klucza, a `HEAD` nie ma
ciała odpowiedzi, więc prawdziwy powód („Class B cap exceeded") widać dopiero
przy `GET`. `rclone` domyślnie robi `HEAD` po każdym wgranym obiekcie — przy 139
tys. plików wyczerpuje to dzienną pulę w kilkanaście minut. Lekarstwo:
`RCLONE_S3_NO_HEAD=true` **globalnie** (nie flagą przy `sync`, bo dotyczy też
małych `rcat` — manifest padał jako ostatni krok i kładł cały przebieg mimo
poprawnie wgranych artefaktów).

**Otwarte:** dozór świeżości kopii (`vars.BACKUP_MONITORING_ENABLED`) jest w pełni
zaimplementowany w `.github/workflows/uptime-probe.yml`, ale wyłączony — wymaga
dwóch sekretów repozytorium z kluczem B2. Klucz czeka na rotację, więc bramka
zostaje zamknięta do tego czasu.

---

## 2. Dwugodzinna cicha awaria wyszukiwania wektorowego

Podbicie `qdrant-client` 1.12.1 → 1.18.0 usunęło `QdrantClient.search()`.
Padło **siedem** wywołań: wyszukiwanie semantyczne, matching, podpowiedzi do pul,
klasyfikacja CC, retrieval historycznych ofert.

**Dlaczego nikt tego nie zobaczył — trzy rzeczy naraz:**

1. CI nie ma Qdranta, więc żaden test nie dotknął tej ścieżki,
2. `/api/health` nie miał klucza `qdrant`,
3. wyjątek na ścieżce wyszukiwania jest połykany i zwraca pustą listę —
   użytkownik widzi „brak wyników", a nie awarię.

**Naprawa:** przypięcie `qdrant-client==1.12.1` (awaryjne) + sonda w
`/api/health`, która **wykonuje to samo wywołanie, z którego żyje aplikacja**.

Sonda sprawdzająca samą łączność byłaby przez całą awarię zielona — serwer
Qdranta działał bez zarzutu, niezgodna była biblioteka po naszej stronie.
To uogólnia się poza Qdranta: **przy niezgodności klienta zdrowie serwera nic
nie mówi**.

Koszt sondy: 1,33 s na zimno, 0,02 s później (rozmiar wektora czytany raz).
Limit 5 s; przekroczenie daje `degraded`, nie `unhealthy` — mylenie „padł"
z „zamulił" produkuje fałszywe alarmy. Zmierzone na atrapach: serwer
przyjmujący połączenie i nieodpowiadający → `degraded` (2,49 s), zamknięty
port → `unhealthy` (0,02 s).

**Otwarte:** migracja siedmiu wywołań na `query_points()` i zdjęcie przypięcia.

---

## 3. Filtr umiejętności — dwie niezależne wady

Filtr „nie ma X" jest **twardy**: pominięty kandydat wygląda dokładnie tak samo
jak nieistniejący. Dlatego obie wady były z ekranu niewidoczne.

### 3a. Ślepota na kodowanie JSON i dopasowanie podłańcuchowe

Główna lista używała gołego wzorca `%go%`. Zapytanie „nie ma Go" wycinało
**196 osób, z których Go znało 15** — resztę stanowili deweloperzy Django,
MongoDB i Golang.

Do tego 303 wiersze trzymają JSON **podwójnie zakodowany**, więc granicą tokenu
jest `\"` zamiast `"`. Wzorzec sprawdzający tylko pierwszy kształt gubił
**dwie trzecie** prawdziwych trafień (5 z 15).

Rozstrzyga `strpos`, nie `LIKE` — w `LIKE` odwrotny ukośnik jest domyślnym
znakiem ucieczki, więc wzorzec na podwójne kodowanie degeneruje się po cichu do
wariantu bez ukośników. Ta sama pułapka przewróciła pomiar przy pisaniu poprawki.

### 3b. Jedna pisownia zamiast rodziny aliasów

Tabela `skill_aliases` (458 wpisów) deklaruje, że „MSSQL", „MS SQL" i
„SQL Server" to ta sama rzecz — ale **dane kandydatów nie są kanonizowane**.
Rozkład rodziny MSSQL w danych:

```
mssql=21, ms sql=18, sql server=18, microsoft sql server=9, microsoft sql=3
```

Zmierzone przez produkcyjne API (liczba wykluczonych przy „nie ma X"):

| wpisane | główna lista | wyszukiwarka |
|---|---|---|
| Microsoft SQL Server | 9 | 9 |
| MSSQL | **9** | 21 |
| SQL Server | **9** | 18 |
| MS SQL | **9** | 18 |
| HTML | 41 | 41 |
| HTML5 | **41** | 35 |
| REST API | 31 | 31 |
| REST | **31** | 35 |

Główna lista zwijała **zapytanie** do nazwy kanonicznej i szukała wyłącznie jej
dosłownego brzmienia — zwracała więc to samo niezależnie od wpisanego wariantu.
Wyszukiwarka nie normalizowała nic. **Żadna nie była nadzbiorem drugiej**: przy
„REST" znajdowała 35, lista 31.

Skala poza MSSQL: HTML gubił 35 z 76, REST API 34 z 69, Java 27 ze 152,
CSS 24 z 71, Kafka 17 z 65, dalej Azure 14, Angular 10, Sass 10, Spark 10, ELK 10.

Rozwinięcie wpięte w `_skill_match` — **jedyny punkt wspólny obu powierzchni**.
Poprawkę w miejscach wywołania da się pominąć przy dopisywaniu kolejnego
endpointu i dokładnie tak powstał poprzedni rozjazd. Efekt uboczny jest
korzystny: koniunkcja przy `skill_combine="and"` nadal działa między
umiejętnościami, a nie między pisowniami tej samej — płaska lista wariantów
zamieniłaby „ma MSSQL ORAZ Pythona" w zapytanie bez wyników.

`canonical_skill_names` celowo **zostaje zwijająca** — używa jej scoring, gdzie
porównuje się dwa zbiory umiejętności.

---

## 4. Traffit — `degraded` nie znaczy „synchronizacja stoi"

Odczyt `traffit_sync_state` na produkcji: **14 z 16 faz** synchronizuje się
codziennie o 04:31 bez błędu (`pipelines`: 178 879 aktualizacji, 703 nowe).

Blokuje **jedna** faza — `candidate_activities` — na `ReadTimeout` z API
Traffita. Przez to znacznik całego biegu (`__daily__`) nie awansuje, a
healthcheck czyta właśnie ten znacznik. Sygnał jest więc **poprawny**, tylko
myląco czytany.

Realna strata jest wąska, ale istotna: notatki powstają z promocji aktywności
(`promote_notes`), więc nie przybywają od 27.07.

Mechanizm kwarantanny z #968 jest wobec tego bezczynny — kolumny
`last_attempt_at`, `last_success_at`, `consecutive_failures`, `next_due_at`
są `NULL`/0 dla wszystkich faz.

---

## 5. Pozostałe zmiany

- **Usunięty bootstrap konta administratora** wykonywany przy każdym starcie
  kontenera — ustawiał hasło, rolę `admin` i `is_active` z wartości w
  repozytorium. Konto dezaktywowane, hasła demonstracyjne przeniesione do
  zmiennej środowiskowej, allowlisty ścieżek usunięte z `.gitleaks.toml`
  (kontrola negatywna: wstrzyknięty prodowy DSN — stara konfiguracja „no leaks
  found", nowa „leaks found: 1").
- **CloudTalk zneutralizowany** zamiast skasowany: pętla w tle kończy się przed
  startem, klucz znika z healthchecku, karta ustawień usunięta z interfejsu.
  Kod integracji zostaje.
- **Deploy przestał czerwienieć fałszywie** — smoke-test rozstrzyga pokrewieństwo
  commitów przez API GitHuba zamiast równości SHA (Coolify klonuje `main` HEAD,
  więc przy serii merge'y te dwie rzeczy rozjeżdżają się z definicji).
- **Introspekcja tras odporna na FastAPI ≥ 0.139** — od tej wersji `app.routes`
  nie jest spłaszczone, więc testy skanujące ją widziały 4 trasy zamiast 789 i
  robiły się **puste, nie czerwone**; kontrakt autoryzacji żądał usunięcia 148
  wpisów baseline'u.
- **Przywrócone 6 merge'y** cofniętych przez squash przeterminowanej gałęzi.

---

## 6. Otwarte

| co | właściciel | uwaga |
|---|---|---|
| Rotacja klucza Backblaze | Artur | blokuje dozór świeżości kopii |
| Odłączenie integracji Vercela | Artur | produkcja jej nie używa; przepalony limit kładzie czerwony check na każdym PR |
| Faza `candidate_activities` (ReadTimeout) | — | blokuje domknięcie syncu; notatki nie przybywają |
| Migracja 7 wywołań na `query_points()` | — | pozwoli zdjąć awaryjne przypięcie |
| 11 rozjazdów lista ↔ wyszukiwarka | — | patrz niżej |

### Rozjazdy między powierzchniami wyszukiwania

Audyt filtra umiejętności ujawnił, że `GET /api/candidates` i
`POST /api/search/candidates` mają osobne implementacje wielu filtrów.
Uszeregowane według ryzyka cichego rozjazdu wyników:

1. `skills` / `skills_must` / `skills_any` — na liście filtr **twardy**,
   w wyszukiwarce **tylko ranking**. Różnica rzędu wielkości w `total`.
2. **Doświadczenie (lata)** — lista ma zapasowy odczyt z danych Traffita,
   wyszukiwarka porównuje kolumnę pustą dla większości importu.
3. **Stawka godzinowa** — odwrotna polityka wobec braku danych: lista wyrzuca
   kandydatów bez stawki, wyszukiwarka ich zostawia.
4. `open_to` — lista łączy alternatywą, wyszukiwarka koniunkcją.
5. `competence_category_ids` — lista uwzględnia kategorie poboczne, wyszukiwarka nie.
6. `skills_none` ze składnią `|` — wyszukiwarka nie zna tej składni.
7. `q` — dwa różne silniki (świadome).
8. `tags` — w wyszukiwarce nadal **gołe dopasowanie podłańcuchowe**, czyli ta
   sama klasa błędu, którą usunięto dla umiejętności.
9. `location` — lista bez escapowania wieloznaczników i bez filtra po kraju.
10. `q_all` / `q_any` / `q_none` — osobne parsowanie grup.
11. `status`, dostępność, widełki — dziś zgodne, ryzyko dryfu.
