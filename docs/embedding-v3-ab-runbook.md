# Tekst embeddingu kandydata v3 — pomiar A/B i przełączenie

Stan: narzędzia gotowe (26.09.2026), **nic nie jest przełączone**. Produkcja
dalej liczy wektory tekstem v1 (`embedding_service._build_candidate_text_v1`:
imię, umiejętności, doświadczenie, podsumowanie, CV ucięte do 3000 znaków) do
kolekcji `nexus_candidates`.

Co mierzymy: czy tekst v3 (`canonical_text.build_candidate_text_v3`: sekcje bez
danych osobowych + **pełne CV do 12 tys. znaków** + sekcja **[NOTES]**
z umiejętności potwierdzonych w notatkach) znajduje właściwych ludzi lepiej niż
v1 — ZANIM zmienimy wektory na produkcji. Zmiana tekstu embeddingu to zmiana
przestrzeni wektorów, więc wymaga własnego A/B (CLAUDE.md, „Profil Championa”).

Wariant kontrolny **v3 bez [NOTES]** (`AI_TEXT_SCHEMA_V3_NOTES=false`) odpowiada
na pytanie o przeciek etykiety: notatki powstają W TRAKCIE procesu rekrutacji,
także o ludziach, których eval traktuje jako „właściwych”. Zysk, który znika bez
notatek, może być zasługą tego, że znamy już wynik — nie lepszego tekstu.

## Nazwy

| Co | Wartość |
|---|---|
| kolekcja produkcyjna (v1) | `nexus_candidates` (env `QDRANT_COLLECTION`) |
| cień v3 | `nexus_candidates_v3` (`eval_ab_run.SHADOW_V3`) |
| cień v3 bez notatek | `nexus_candidates_v3_nonotes` (`eval_ab_run.SHADOW_V3_NO_NOTES`) |
| model | bez zmian: `VOYAGE_MODEL=voyage-3` |

Tekst ofert (`nexus_jobs`) się nie zmienia — v3 dotyczy wyłącznie kandydatów.

## 1. Budowa kolekcji-cieni na produkcji

Budowa idzie w kontenerze `backend` produkcji (ma klucz Voyage i dostęp do
Qdranta), ale **nie zmienia niczego, z czego korzysta aplikacja**:

- wektory lądują w osobnej kolekcji (`--collection`);
- tekst jest wybierany jawnie (`--text-schema v3`), więc env kontenera
  (`AI_TEXT_SCHEMA_V3=false`) nie ma znaczenia;
- skrypt rozpoznaje cień i **nie dotyka** `candidates.embedding_id` ani outboxu
  indeksu (`match_index_outbox`). Zapis `indexed_hash` dla cienia powiedziałby
  reconcilerowi produkcji, że v3 jest zaindeksowane.

**Nie** ustawiaj `QDRANT_COLLECTION=…`/`AI_TEXT_SCHEMA_V3=…` w env samego
polecenia budowy. Wtedy skrypt uznałby cień za kolekcję aktywną. Do cienia
służą wyłącznie `--collection` i `--text-schema`.

### 1a. Szacunek kosztu (bez wywołań API)

```bash
docker exec <kontener-backend> sh -c 'cd /app && python -m scripts.reembed_collections \
  --target candidates --dry-run --estimate \
  --collection nexus_candidates_v3 --text-schema v3'
```

W logu linia `ESTIMATE:` podaje liczbę tekstów, łączną liczbę znaków, ~tokeny
(znaki/3) i liczbę żądań Voyage. Koszt = tokeny × cena voyage-3 (0,06 USD za
1 mln tokenów; sprawdź aktualny cennik Voyage). Oczekiwany rząd wielkości dla
~63 tys. kandydatów: **~6–15 USD na jedną kolekcję**, czyli ~12–30 USD za obie.
Zmierzone 18.08.2026: 63% CV (32 tys. z 50,6 tys.) jest dłuższych niż 3000
znaków, więc tekst v3 jest średnio kilka razy dłuższy niż v1.

### 1b. Budowa

```bash
# v3 (pełne CV + notatki)
docker exec -d <kontener-backend> sh -c 'cd /app && python -m scripts.reembed_collections \
  --target candidates --commit --ensure-collection --resume \
  --collection nexus_candidates_v3 --text-schema v3 \
  --max-batch-chars 120000 --log-every 2000 > /tmp/reembed-v3.log 2>&1'

# v3 bez notatek (kontrola przecieku)
docker exec -d <kontener-backend> sh -c 'cd /app && python -m scripts.reembed_collections \
  --target candidates --commit --ensure-collection --resume \
  --collection nexus_candidates_v3_nonotes --text-schema v3-nonotes \
  --max-batch-chars 120000 --log-every 2000 > /tmp/reembed-v3-nonotes.log 2>&1'
```

Budowy puszczaj **jedna po drugiej**, nie równolegle. Obie korzystają z tego
samego limitu tokenów na minutę w Voyage i z tego samego backendu.

- **Paczki po znakach** (`--max-batch-chars`, domyślnie 120 000): Voyage limituje
  łączną liczbę tokenów w JEDNYM żądaniu (voyage-3: 120 tys.), a nie tylko liczbę
  tekstów (128). Przy 128 tekstach v3 po ~12 tys. znaków paczka miałaby ~1,5 mln
  znaków, czyli HTTP 400 dla całej paczki. Przy 120 tys. znaków na żądanie
  wychodzi ~40–60 tys. tokenów, więc zostaje zapas. Jeśli w logu pojawi się
  `voyage batch … failed` z HTTP 400, zmniejsz `--max-batch-chars` do 60000
  i uruchom ponownie z tym samym `--resume`.
- **Wznawianie** (`--resume`): Coolify restartuje kontener przy każdym pushu na
  `main`, a budowa trwa godziny. `--resume` pomija kandydatów, których punkt
  w kolekcji docelowej ma już `content_hash` DOKŁADNIE tej treści i ten sam
  `embedding_model`. Po restarcie uruchamiasz dokładnie to samo polecenie.
  Zapłacisz tylko za to, czego jeszcze nie ma, oraz za kandydatów zmienionych
  w trakcie budowy. Samo `--only-missing` sprawdzało wyłącznie obecność id
  i zostawiało wektory ze starej treści.
- **Czas**: szacunkowo 1–3 h na kolekcję. Zależy od limitu tokenów/min konta
  Voyage (niezmierzone). Postęp widać w `/tmp/reembed-v3.log` (`N/M (ok=…,
  skipped=…, fail=…)`).
- **Miejsce w Qdrancie**: ~63 tys. × 1024 × 4 B ≈ 260 MB wektorów na kolekcję,
  z indeksem ~0,5 GB. Serwer ma 32 GB RAM.
- Kontener po restarcie deployu ma `/tmp` wyczyszczone, więc log zaczyna się
  od nowa. To normalne.

Gdyby `docker exec` był niedostępny, użyj terminala kontenera w panelu Coolify
(to samo polecenie, bez `docker exec`). **Nie** zakładaj zadania cyklicznego
Coolify bez blokady. Cron co minutę uruchomiłby kilka budów naraz i każda
płaciłaby osobno.

### 1c. Dogonienie tuż przed evalem

Wektory produkcji dogania worker outboxu, a cień nie dostaje żadnych
aktualizacji. Kandydat zmieniony po budowie ma w cieniu wektor „nieaktualny”
(evaluator liczy świeżość z `content_hash`). Takiego kandydata ramię v3
stawia na końcu listy, a ramię v1 normalnie. Dlatego **tuż przed evalem**
powtórz polecenie z 1b. Z `--resume` przeliczy tylko zmienionych, czyli zwykle
kilkaset osób.

## 2. Pomiar

Wszystkie ramiona mają **ten sam scorer (`canonical`)** i tę samą pulę
wektorową (bez hybrydy i rerankera). Metryk między scorerami nie porównujemy.
Ramię dostaje flagi przez env WŁASNEGO procesu, więc produkcja ich nie widzi.

### 2a. `eval_matching` (zamrożony zbiór 50 ofert)

GitHub → Actions → **Coolify ops** (`coolify-ops.yml`), z `main`:

| Bieg | `action` | `eval_set` | `eval_jobs` | `eval_pool` |
|---|---|---|---|---|
| v1 vs v3 (strojenie) | `eval-ab-text` | A | 50 | 2000 |
| v1 vs v3 (holdout) | `eval-ab-text` | B | 50 | 2000 |
| v3 vs v3 bez notatek | `eval-ab-text-notes` | A | 50 | 2000 |
| v3 vs v3 bez notatek (holdout) | `eval-ab-text-notes` | B | 50 | 2000 |

Komenda zadania Coolify ma ~120 znaków, więc mieści się w limicie 255
(`scheduled_tasks.command`). Test `test_workflow_command_fits_coolifys_varchar_255`
liczy ją dla najdłuższej nazwy ramion. Wynik czytasz z sekcji
`NEXUS-EVAL-OFF` / `NEXUS-EVAL-ON`: Precision@5, Recall@20, R@20 norm, MRR,
nDCG@10.

Zanim przeczytasz deltę, sprawdź:
1. W obu nagłówkach jest `Scorer: canonical` oraz `Voyage API key configured: yes`.
2. Kolumna **GT indexed** jest podobna w obu ramionach. Jeśli w ramieniu v3
   jest wyraźnie mniej, cień jest niekompletny albo nieaktualny i delta mierzy
   pokrycie, nie tekst. Wtedy wróć do 1c.
3. Ramię OFF w `eval-ab-text` (v1) zgadza się z poprzednimi biegami canonical
   na tym samym zbiorze. Porównuj tylko biegi tego samego scorera.

### 2b. Kolejność „Szukaj ręcznie” (`eval_manual_search_order`)

Workflow tego harnessu nie wystawia, bo potrzebne byłoby nowe wejście. Uruchom
go w kontenerze. Komenda też mieści się w 255 znakach, więc da się ją wkleić
także jako jednorazowe zadanie Coolify z blokadą `--lock`:

```bash
docker exec <kontener-backend> sh -c 'cd /app && python -m scripts.eval_ab_run \
  --arms text --harness manual --set A --jobs 120 --pool 2000 --lock /tmp/nexus-eval-1001'
docker exec <kontener-backend> sh -c 'cd /app && python -m scripts.eval_ab_run \
  --arms text-notes --harness manual --set A --jobs 120 --pool 2000 --lock /tmp/nexus-eval-1002'
```

`--set` i `--pool` są tu bez znaczenia (ten harness bierze rekrutacje
z historii). `--jobs` to liczba rekrutacji, od 1 do 300. Sekcja
`NEXUS-EVAL-OFF/ON` to tabela z końca logu. Tabela ma kolumny: właściwe osoby
w wynikach, rekrutacje z ≥1 właściwą osobą na 1. stronie, właściwe osoby
w top 50, MRR i mediana pozycji. Porównuj **te same wiersze** tabeli (np.
„wektor kolumny Dop.”) między ramionami. Wiersze nexus_jobs i „najnowsi” nie
zależą od wektora kandydata albo zależą tylko częściowo. Wiersz „najnowsi” ma
być identyczny w obu ramionach i służy jako kontrola przyrządu.

Pusta sekcja `NEXUS-EVAL-OFF` nie znaczy „zero wyników”. Znaczy, że harness
się wywrócił. Przyczyna jest wtedy w `NEXUS-EVAL-TAIL-*`.

## 3. Reguła decyzji

Przełączamy **tylko wtedy, gdy żadna metryka nie spada**:

1. `eval-ab-text` na zbiorze A **i** B: v3 ≥ v1 na Precision@5, R@20 norm, MRR
   i nDCG@10. Remis jest dopuszczalny, spadek nie.
2. `eval_manual_search_order` (`--arms text`): v3 ≥ v1 w wierszach zależnych od
   wektora kandydata. Chodzi o rekrutacje z ≥1 właściwą osobą na 1. stronie,
   właściwe osoby w top 50 i MRR. Mediana pozycji nie może rosnąć.
3. **Kontrola przecieku** (`text-notes`): v3 bez notatek też musi spełniać
   punkty 1–2 względem v1.
   - Oba warianty ≥ v1, a zysk v3 z notatkami ≈ zysk bez notatek: przełączamy
     na **v3** (z notatkami).
   - Oba ≥ v1, ale prawie cały zysk znika bez notatek: zysk może pochodzić
     z przecieku etykiety. Decyduje Artur. Bezpieczniejsza opcja to
     przełączenie na v3 **bez** notatek, czyli kolekcję
     `nexus_candidates_v3_nonotes` z `AI_TEXT_SCHEMA_V3_NOTES=false`.
   - v3 bez notatek < v1: nie przełączamy.
4. Każdy inny wynik: nie przełączamy. Cienie można usunąć (koniec rozdziału 5).

Każda decyzja trafia do raportu z liczbami obu zbiorów (A i B) i obu harnessów.

## 4. Przełączenie (po decyzji)

Przełączenie zmienia źródło wektorów i schemat tekstu jednocześnie. Obie
zmienne siedzą w `_SCORING_CACHE_INPUTS`, więc cache score'ów unieważni się sam.

1. **Dogonienie cienia** (1c) tuż przed przełączeniem.
2. GitHub → Actions → **Coolify set env** (`coolify-set-env.yml`), każda
   zmienna z `redeploy=false`:
   - `QDRANT_COLLECTION` = `nexus_candidates_v3` (albo `…_v3_nonotes`),
   - `AI_TEXT_SCHEMA_V3` = `true`,
   - tylko przy wariancie bez notatek: `AI_TEXT_SCHEMA_V3_NOTES` = `false`.
3. Uruchom workflow **Deploy** (jeden deploy dla wszystkich zmiennych).
   Sprawdź, że `/api/health` zwraca nowy SHA.
4. **Zapis stanu indeksu do outboxu.** Bez tego kroku reconciler dryfu
   porówna ostatni zapisany `indexed_hash` (v1) z haszem v3. Każdy kandydat
   wyglądałby wtedy na dryf i poszedłby do ponownego embeddingu, czyli ~60 tys.
   wywołań Voyage za wektory, które już są w kolekcji. Teraz aplikacja ma v3
   jako aktywny schemat, więc skrypt na to pozwala:

   ```bash
   docker exec -d <kontener-backend> sh -c 'cd /app && python -m scripts.reembed_collections \
     --target candidates --commit --resume --record-outbox \
     --max-batch-chars 120000 --log-every 2000 > /tmp/reembed-switch.log 2>&1'
   ```

   Bez `--collection`/`--text-schema` skrypt bierze parę aktywną w aplikacji.
   Z `--resume` przelicza tylko kandydatów zmienionych od ostatniego dogonienia.
   Każdy kandydat z aktualnym wektorem (także pominięty) dostaje w outboxie
   wiersz `done` z `indexed_hash = desired_hash`. Hasz liczy
   `index_outbox_service.desired_state`, więc reconciler porównujący
   `hashes_match` trafia dokładnie. Na aktywnej kolekcji skrypt dopisuje też
   `candidates.embedding_id`.
   Przez kilka minut między deployem a końcem tego kroku reconciler (tik co
   300 s, paczki po 500) może zakolejkować kilka tysięcy „dryfów”. Worker
   policzy je tekstem v3 do nowej kolekcji. Wynik będzie poprawny, a koszt
   to ułamek dolara.
5. Sprawdź: `GET /api/admin/ai-matching/diagnostics` pokazuje
   `version_trace.text_schema_version = text-v3-cv-notes` (albo `text-v3-cv`)
   oraz flagi `AI_TEXT_SCHEMA_V3`/`QDRANT_COLLECTION`. Na ekranie „Dodaj
   kandydatów” w rekrutacji kolumna „Dop.” ma liczby, a nie „Ocena niepełna”
   masowo.
6. Stara kolekcja `nexus_candidates` zostaje **nietknięta** przez okno
   rollbacku (co najmniej 2 tygodnie).

## 5. Rollback

1. **Coolify set env** (`redeploy=false`): `QDRANT_COLLECTION=nexus_candidates`,
   `AI_TEXT_SCHEMA_V3=false` (i `AI_TEXT_SCHEMA_V3_NOTES=true`, jeśli był
   zmieniany), potem jeden **Deploy**.
2. Wektory v1 w `nexus_candidates` przestały się aktualizować w chwili
   przełączenia, bo worker pisał do nowej kolekcji. Dogoń je krokiem 4 z
   rozdziału 4 (`--resume --record-outbox`, bez `--collection`). Po rollbacku
   aktywna para to znowu (`nexus_candidates`, v1), więc skrypt przeliczy
   zmienionych i zapisze w outboxie hasze v1.
3. Cache score'ów unieważni się sam (digest wersji zawiera obie zmienne).

Usunięcie cienia, gdy nie jest już potrzebny (Qdrant REST w sieci kontenerów):
`DELETE /collections/nexus_candidates_v3`. Nigdy nie usuwaj kolekcji wskazanej
w `QDRANT_COLLECTION`.

## Otwarte / niezweryfikowane

- Limit tokenów na żądanie dla voyage-3 (120 tys.) i limit 128 tekstów pochodzą
  z dokumentacji Voyage, nie z pomiaru. Sufit 120 000 znaków ma zapas nawet
  przy 2 znakach na token.
- Koszt i czas budowy to szacunek. Liczby da `--estimate` na produkcji.
- `eval_matching` i `eval_manual_search_order` przy ramieniu v3 czytają cień
  przez `QDRANT_COLLECTION` z env procesu. Nie sprawdzano ich na żywym cieniu.
