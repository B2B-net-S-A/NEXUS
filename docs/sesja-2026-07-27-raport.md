# Raport z sesji — 2026-07-27

Stan końcowy: **main `9711eb7`**, produkcja `healthy`, dysk 52%, backlog PR-ów **42 → 29**
(dependabot **20 → 5**).

---

## 1. Co było zlecone

Trzy polecenia, po kolei:

1. *„zweryfikuj co jest nadal do wykonania i zaplanuj prace"* — po drugim audycie Codexa.
2. *„zamknij #712, #693, #694 i dependabota z patchami"*.
3. *„zrób majory dependabota, ale każdy osobno z testami"*.

---

## 2. Najważniejsze ustalenie sesji: kopii off-site nigdy nie było

Audyt zgłosił F-14 jako „backup/DR nie dowodzi możliwości odtworzenia". Weryfikacja
na żywym serwerze pokazała coś gorszego, czego audyt **nie zauważył**:

- **Lokalny backup działa** — cron 02:30, `/var/backups/nexus/`, dzienny dump ~284 MB
  + snapshoty Qdranta. **Ale leży na tym samym dysku co produkcja.**
- **Kopia off-site nigdy nie powstała.** `/root/nexus-offsite-backup.sh` od tygodni
  codziennie loguje „konto off-site nie zostało założone" i **wychodzi z kodem 0**,
  więc żaden monitoring nie zapiszczał.
- **Korpus ~136 tys. CV (37 GB) nie jest backupowany przez nic.** `object_storage.py`
  to „single source of truth" — bajty żyją wyłącznie w buckecie S3, a `backup.sh`
  taruje `uploads_data` (dokumenty kontraktowe). `pg_dump` odtworzy tylko `storage_key`,
  czyli wiersze wskazujące na nieistniejące pliki. **`docs/disaster-recovery.md`
  twierdziło, że to jest pokryte.**
- Drill `scp`-ował legacy kopię z tego samego dysku, czyli testował **inny system**
  niż ten, który pisze do bucketu. Zero testu `age -d` — nic nigdy nie dowiodło,
  że kopia da się odszyfrować.

**Zrobione:** utworzony bucket Backblaze B2 `dynaminds-nexus-offsite` (prywatny, SSE-B2,
EU, skasowane pliki znikają po 30 dniach), klucz aplikacyjny ograniczony do tego jednego
bucketu, `BACKUP_S3_BUCKET/ENDPOINT/REGION` w Coolify, zmienne GitHuba. Kod (#924):
korpus CV jako czwarty artefakt (`rclone sync --backup-dir`, porównanie **liczby
obiektów**, nie tylko bajtów), drill ciągnący z bucketu przez **realny `age -d`**,
konsument `LATEST.json` alarmujący o zaniku backupu, retry w pętli, healthcheck.

**BLOKADA — po stronie Artura, 6 wklejeń:** klucz z B2 (keyID + applicationKey),
dwa klucze `age` (`age-keygen`: master + drill), `BACKUP_AGE_PUBLIC_KEY` = oba klucze
publiczne po przecinku, oraz 3 sekrety w GitHubie dla drilla. Do tego czasu
`BACKUP_ENABLED=false` i **cała baza plus wszystkie CV mają kopie wyłącznie na dysku
produkcyjnym.**

---

## 3. Audyt Codexa #2 — dyspozycja 29 findingów

Weryfikacja adwersaryjna przed naprawą. Wynik: **11 potwierdzonych, 1 false positive,
7 świadomych decyzji, 1 infra**.

| Finding | Wynik |
|---|---|
| F-18 pętla logowania | naprawione (#918), zweryfikowane w przeglądarce na prodzie |
| F-19/F-20 capability + stany błędu | naprawione (#920) |
| F-11 crash windows | **4 okna**, wszystkie naprawione (#923 + #932) |
| F-27 skany pipeline'u | 6 skanów/tick → 1 (#922) |
| F-23 a11y/debounce | naprawione (#925) |
| F-17 pokrycie CI | +1013 testów realnie wykonywanych (#931) |
| F-14 backup | kod gotowy (#924), czeka na sekrety |
| F-24 blast radius Coolify | **false positive** — żaden z 3 zarzutów nie repro |

**Zawężenia, które oszczędziły złej roboty:** F-03 miał połowę fałszywą (BOLA — dodanie
filtra członkostwa odwróciłoby udokumentowany model dostępu; naprawiony tylko row-lock);
F-13 część o FX była fałszywa, a `rate_candidate` w generatorze B2B to świadomy dostęp
zespołu prawnego; F-07 dotyczył jednego endpointu, nie listy.

**Moja pomyłka, skorygowana:** ogłosiłem, że AAD RBAC jest żywy i nadpisuje role z panelu.
Nieprawda — w `config.py` jest walidator `_force_aad_group_rbac_disabled`, który twardo
wymusza `False` niezależnie od env. Przegapiłem go, bo uciąłem `grep` na 20 liniach.
Env był martwy, dziury nie było.

---

## 4. Łańcuch, który doprowadził do realnego błędu produkcyjnego

Najciekawszy wynik sesji — żadnego ogniwa nie dało się pominąć:

1. **F-17** ujawnił, że CI odpala 190 z 311 plików testowych.
2. Dopięcie brakujących pokazało dwa testy krzyczące, że **wygasłe linki serwują treść**.
3. Weryfikacja: **dziury nie ma** (#941). Wygaszanie działa we wszystkich 5 rodzinach
   linków. Testy były martwe — po migracji hash-at-rest `UPDATE ... WHERE token = <sekret>`
   trafiał w **zero wierszy i milczał**, więc link nigdy nie był wygaszany.
4. Przy okazji wyszło, że **CI nie ustawia `M365_TOKEN_ENCRYPTION_KEY`, a produkcja go ma**
   (44 znaki, zweryfikowane w Coolify) — czyli dla linków zapraszających CI od migracji
   `0183` zielenił się na ścieżce legacy, której prod nie wykonuje.
5. Uruchomienie tych testów na właściwej ścieżce odsłoniło **realny błąd**: gubioną
   etykietę źródła kandydata (#948). Objaw dla użytkownika: „nie wiadomo, skąd przyszedł
   ten kandydat".

Domknięte przez #949 — CI szyfruje teraz tokeny tak jak produkcja.

**Lekcja wpisana w kod:** każdy naprawiony setup asertuje `rowcount == 1`. Setup, który
po cichu nic nie robi, zamienia test bezpieczeństwa w pieczątkę.

---

## 5. Majory dependabota — 9 rozstrzygniętych, każdy osobno z testami

W **trzech przypadkach dowieziono inną wersję, niż proponował dependabot**:

| Proponowane | Dowiezione | Dlaczego |
|---|---|---|
| pdfminer 20260107 | 20251230 + pdfplumber 0.11.9 | 20260107 **niemożliwe** — pdfplumber pinuje przez `==`; **wywaliłoby build**. Nowa wersja niesie **CVE-2025-64512** (RCE przez `pickle`) |
| node 26-alpine | 24-alpine LTS | 26 to linia *Current*. Przy okazji: **node 20 jest EOL od kwietnia** — obraz prod i CI stały bez łatek |
| python-json-logger 4.1.0 | 4.1.0 + `%(taskName)s` | sam bump **gubiłby pole `taskName`** z logów ~24 pętli w tle; changelog o tym milczy |

Pozostałe: `actions/checkout` 4→6, `actions/cache` 4→5 (z dowodem, że cache trafia bit
w bit), `actions/setup-node` 4→6, `icalendar` 6→7 (**naprawia** podwójne odescapowanie
w 6.1.0), `aiofiles` 24→25, `react-markdown` 9→10, `recharts` 2→3.

**Wzorzec:** przy pięciu z dziewięciu bumpów **sam zielony build byłby kłamstwem**.
Wykresy zbudowałyby się i renderowały pusto. Logi leciałyby bez etykiety zadania.
Ekstrakcja CV mogła zwracać pustkę. Za każdym razem trzeba było porównać **realne
wyjście przed i po** — SVG, linię logu, tekst z PDF-a, plik ICS.

Dwie pułapki warte zapamiętania (recharts): stub `getBoundingClientRect` musi być
**tylko** na `.recharts-responsive-container`, bo globalny okłamuje pomiar tekstu i
**wszystkie serie znikają bez błędu**; słupki wymagają stubu `prefers-reduced-motion`,
inaczej grupy `.recharts-bar-rectangle` **istnieją, ale są puste**.

---

## 6. Operacyjne

- **Env Coolify posprzątane: 140 → 88 wpisów, zero duplikatów.** 52 klucze były
  zduplikowane, **2 z rozjechanymi wartościami** — o tym, którą dostaje kontener,
  decydowała kolejność renderowania. Mina czekająca na dowolny redeploy.
- **CloudTalk wyłączony** — zwracał 401 co godzinę od miesiąca, synchronizacja rozmów
  martwa (`inserted=0`), a health kłamał `unhealthy` zamiast `unconfigured`.
- **Traffit: 324 etapy pipeline'u gubione na każdym syncu** (#921). Przyczyna zmierzona
  na prodzie: fallback powodu kluczowany po `jobs.pipeline_template_id`, który jest NULL
  dla **4058 z 4075 jobów (99,6%)**.
- **Dysk: dodany cron czyszczący cache BuildKita** (04:15 UTC, filtr `until=24h`).
  Wbudowane sprzątanie Coolify jest włączone (co godzinę, próg 60%), ale **czyści obrazy
  i kontenery, nie cache builda** — dlatego przy zerowej liczbie obrazów dangling dysk
  dwukrotnie dziś podszedł pod 84%. Ten serwer padł raz przy 98,8%.
- **F-09 zmaterializował się** — 4 czerwone deploye, wszystkie fałszywe. Coolify klonuje
  HEAD maina w momencie budowania, więc przy serii merge'ów smoke test szuka SHA, który
  przestał być aktualny. Prod za każdym razem był zdrowy i zbieżny z mainem.

---

## 7. Otwarte

**Wymaga Artura:**

1. **Backup off-site — 6 wklejeń.** Jedyna pozycja, przy której chodzi o to, czy dane
   przetrwają utratę serwera.
2. **Tailwind 4 (#954) — NIE zmergowany, czeka na Twoje oczy.** 222 pliki. Dowody są
   mocne: macierz 56 kombinacji motywu × 67 elementów (64/67 identyczne, 3 różnice to
   artefakty pomiaru), realne ekrany przed/po z **maks. deltą kanału 2–6/255** (poziom
   antyaliasingu, zero reflow). Agent znalazł i naprawił **4 defekty oficjalnego kodmodu**,
   w tym cichy: kodmod **zgubił plugin typography** → 139 reguł `.prose` → **0**, przy 22
   użyciach. Ale sam zaleca ręczne przejście po zalogowanej aplikacji, bo trzy ryzyka
   rezydualne są dokładnie tam, gdzie nie dało się sprawdzić: ekrany za logowaniem,
   665 użyć `space-x/y-*` ze zmienionym selektorem, oraz to, że DS jest wspólny dla
   4 aplikacji, a NEXUS byłby pierwszy na v4.
3. **`head_of_recruitment`** — backend odmawia tej roli zakładania ofert i klientów.
   UI przestało pokazywać przyciski, które i tak nie działały. Jeśli to backend jest
   niezgodny z zamysłem, poprawka należy się jemu.
4. **5 PR-ów dependabota** — 3 grupowe (#564, #519, #299) + tailwind (#53) + python (#44).

**Do potwierdzenia:** `checks.traffit` zejdzie z `degraded` po dziennym syncu o 02:00 UTC.
Można przyspieszyć przez `POST /api/admin/traffit/sync?mode=delta` jako admin.

**Świadomie odłożone:** multi-replika (latentna, chroniona jedną repliką), F-25 analytics
cutover (wymaga 7 dni shadow na prodzie), E2E na PR-ach (wymaga sekretów).

### Kolejka — przejęte z zatrzymanych sesji równoległych

Artur zatrzymał 6 równoległych sesji; te zadania przechodzą tutaj, do zrobienia po raporcie.
Dwa okazały się **już nieaktualne** (sprawdzone na `main`):

| Zadanie | Stan |
|---|---|
| Zamknąć Dependabot #55 (@vitest/ui) | ❌ zbędne — #55 już `CLOSED`, pakiet usunięty w #945 |
| Usuń zduplikowany `useDebouncedValue` z `AppShell.tsx` | ❌ zbędne — zrobione w #926, zero wystąpień |
| **Usuń martwy pakiet `voyageai`** | ✅ zasadne — **UWAGA:** martwy jest wyłącznie *pakiet SDK* (zero importów); *usługa* Voyage żyje i jest wołana przez `httpx` w `embedding_service.py` + `reranker_service.py`. Do usunięcia jedna linia w `requirements.txt`. Odczytanie tego jako „Voyage nieużywany" wycięłoby embeddingi i matching. (#953 podbił go do 0.3.3, bo 0.3.2 blokował Pythona 3.13) |
| **Usuń martwy `SuggestedCandidatesDrawer`** | ✅ zasadne — plik istnieje, zero importów w `src/` |
| **Napraw martwe testy e2e po drawerze** | ✅ zasadne, zależne od powyższego |
| **Uniezależnij testy od stanu bazy → auto-discovery w CI** | ✅ najwartościowsze i najtrudniejsze. Dziś sama zmiana kolejności zbierania daje **6 awarii**, w tym 3 w pliku podpiętym i zielonym. Warunek konieczny dla `pytest tests/` zamiast ręcznej listy |

**Uwaga o równoległości:** dwie sesje zrobiły dziś tę samą robotę dwa razy — #948 i #949
naprawiały ten sam objaw (martwe `test_invite_links.py` + gubiona etykieta źródła).
Rozwiązane przez zwężenie #949 wyłącznie do konfiguracji CI. Przy rozdzielaniu zadań
na równoległe sesje warto pilnować rozłączności zakresów.

---

## 8. Liczby

| | |
|---|---|
| PR-y zmergowane (moje) | 26 |
| PR-y zamknięte z uzasadnieniem | 14 |
| Backlog PR-ów | 42 → 29 |
| Dependabot | 20 → 5 |
| Testy realnie wykonywane w CI | +1013 (89 plików) |
| Czas joba Backend | 13,7 → 18,1 min (świadomy koszt) |
| Migracje | 0195 → 0198, jedna głowa |
| Python w obrazie prod | 3.12 → 3.13 (3.14 nieosiągalne) |
| CVE załatane | 1 (CVE-2025-64512) |
