# Runbook — uruchomienie i weryfikacja kopii off-site (#201)

> Zakres: **doprowadzić kopię zapasową do stanu, w którym jest sprawdzalna**.
> Ten dokument opisuje czynności właściciela. Automat ich nie wykona:
> **nie generuje kluczy, nie zakłada kont i nie odczytuje ani nie ustawia
> wartości żadnego sekretu.**
>
> Konstrukcja systemu, decyzje projektowe i **procedura odtwarzania** —
> `docs/disaster-recovery.md`. Tutaj: kolejność kroków i dosłowne polecenia.

## Stawka, w jednym akapicie

`pg_dump` zachowuje z dokumentów kandydatów wyłącznie
`candidate_documents.storage_key`, czyli **wskaźniki**. Same pliki — ~136 tys.
CV, ~37 GB — leżą w osobnym buckecie object storage i **nie istnieją nigdzie
indziej**. Odtworzenie z samego zrzutu bazy daje ATS pełen martwych odnośników.
Dlatego „backup działa" znaczy tu dokładnie jedno: **zielony
`backup-drill.yml`**, który pobiera archiwum, odszyfrowuje je i próbkuje korpus
CV względem odtworzonych wierszy. Wszystko poniżej prowadzi do tego jednego
zielonego biegu.

---

## (a) Czy kopia w ogóle powstaje — i jak to sprawdzić

**Nie zgaduj i nie ufaj temu dokumentowi.** Stan czytasz z produkcji:

```
GitHub → Actions → „Coolify Ops" → Run workflow → action = backup-status
```

Read-only: same GET-y do API Coolify, zero zapisów, zero deployu. Wypisuje
wartości konfiguracji (jawna allowlista), **samą obecność** sekretów, status
aplikacji i **werdykt**. Bieg kończy się czerwono, jeśli kopia nie jest
produkowana w komplecie — werdykt jest też w podsumowaniu biegu.

Powód, dla którego ten kanał musiał powstać: kopii pilnują **trzy niezależne
bramki, każda domyślnie zamknięta i każda cicha**.

| # | Bramka | Gdzie | Objaw, gdy zamknięta |
|---|---|---|---|
| 1 | `BACKUP_ENABLED` (default `false`) | vault Coolify | **żaden** — `backup.sh` wychodzi na kill-switchu z kodem 0, kontener jest „healthy", pętla tyka, kopia nie powstaje ani razu |
| 2 | `BACKUP_AGE_PUBLIC_KEY`, `BACKUP_S3_*`, `OBJECT_STORAGE_*` | vault Coolify | **żaden na zewnątrz** — skrypt przerywa w `fail()`, `loop.sh` ponawia 3× i śpi do jutra |
| 3 | sekrety repo `BACKUP_AGE_PRIVATE_KEY`, `BACKUP_S3_*` + zmienna `BACKUP_MONITORING_ENABLED` | GitHub | drill pada na pierwszym kroku, a godzinowy check świeżości jest **pomijany** (`skipped`, nie `failed`) |

Sonda kontenera (`backup/healthcheck.sh`) **z założenia nie odpowiada** na
pytanie „czy kopia się udała" — bada wyłącznie żywotność pętli. Zielony kontener
przy zamkniętej bramce nr 1 jest w pełni poprawnym zachowaniem systemu i zarazem
dokładnie tym, co przez miesiące wyglądało na „backup działa".

---

## (b) Dedykowana para kluczy `age` dla drilla

**Nigdy nie wkładaj klucza głównego do sekretów GitHuba.** Utrata klucza
głównego jest nieodwracalna — cała historia kopii staje się bezużyteczna — a
jego kopia w GitHubie przenosiłaby całe archiwum za granicę bezpieczeństwa
GitHuba na stałe. `backup.sh` przyjmuje **wielu odbiorców** (`age -R`, lista po
przecinku) właśnie po to, żeby klucz drillowy dało się dołożyć, a potem
rotować lub porzucić, **bez przeszyfrowywania choćby jednego zapisanego
obiektu**.

Na **lokalnej maszynie**, nigdy na serwerze:

```bash
age-keygen -o nexus-backup-master.key   # wypisze swój klucz publiczny age1…
age-keygen -o nexus-backup-drill.key    # wypisze swój klucz publiczny age1…
```

Gdzie trafia która połówka:

| Połówka | Miejsce | Uwaga |
|---|---|---|
| **publiczna** obu kluczy (`age1…`) | vault Coolify → `BACKUP_AGE_PUBLIC_KEY`, **po przecinku**: `age1master…,age1drill…` | jedyne, co opuszcza lokalną maszynę w stronę serwera |
| **prywatna** klucza **głównego** (`nexus-backup-master.key`) | wyłącznie menedżer haseł | nigdzie indziej — ani serwer, ani GitHub, ani ten worktree |
| **prywatna** klucza **drillowego** (`nexus-backup-drill.key`) | menedżer haseł **oraz** sekret repo `BACKUP_AGE_PRIVATE_KEY` | to jedyny klucz prywatny, który wolno oddać automatowi |

> ⚠️ **Nowy odbiorca działa dopiero od NASTĘPNEGO backupu.** `age` szyfruje do
> odbiorców znanych w chwili zapisu. Dopisanie klucza drillowego nie odblokowuje
> archiwów już leżących w buckecie — po zmianie `BACKUP_AGE_PUBLIC_KEY` trzeba
> odczekać jeden nocny bieg (albo wymusić bieg przez `BACKUP_RUN_ON_START=true`),
> zanim drill ma co odszyfrować. Drill uruchomiony wcześniej padnie na `age -d`
> i będzie miał rację.

---

## (c) Klucz B2 **read-only**, zawężony do bucketa

Sidecar backupu potrzebuje klucza **z prawem zapisu** (wgrywa archiwa i kasuje
przeterminowane) — ten mieszka w vaultcie Coolify i tam zostaje. Drill
potrzebuje **wyłącznie odczytu**, więc dostaje **osobny** klucz. Nie jest to
rytuał: sekret repo GitHuba jest dostępny każdemu biegowi workflow z tego
repozytorium, a klucz z prawem zapisu w tym miejscu oznaczałby, że kopie
zapasowe da się skasować z poziomu zmiany w `.github/workflows/`. Czyli że
backup i produkcja padają tym samym uprawnieniem — a to znosi sens kopii.

W panelu Backblaze (`secure.backblaze.com` → **Application Keys** → *Add a New
Application Key*):

| Pole | Wartość |
|---|---|
| Name of Key | `nexus-drill-readonly` |
| Allow access to Bucket | **tylko** bucket off-site (wg `docs/disaster-recovery.md`: `dynaminds-nexus-offsite`) — nie „All" |
| Type of Access | **Read Only** |
| File name prefix / Duration | zostaw puste |

`keyID` i `applicationKey` pokazują się **raz**. Zapisz oba w menedżerze haseł,
zanim zamkniesz okno.

Uprawnienia, których drill faktycznie używa: `listFiles` (`rclone lsjson`,
`rclone size`) i `readFiles` (`rclone cat`). `RCLONE_S3_NO_CHECK_BUCKET=true`
jest już ustawione w workflow, więc klucz **nie** potrzebuje `listBuckets` ani
niczego na poziomie konta.

> ⚠️ **Każdy odczyt z B2 to transakcja klasy B/C, objęta dziennym limitem.**
> Limit wyczerpany = `403 … transaction (Class B) cap exceeded`, czyli
> odtwarzanie niemożliwe dokładnie wtedy, kiedy jest potrzebne. Limity
> podnosi się **przed** pierwszym biegiem — procedura i zmierzone wielkości:
> `docs/disaster-recovery.md`, sekcja *Activation*, punkt 3.

---

## (d) Co ustawić — dosłownie

### d.1 Vault Coolify (bramki 1 i 2)

Wszystkie te wartości są **runtime**, więc `is_buildtime = false`. Ale **nie
wszystkie wolno wprowadzić tą samą drogą** — i to jest jedyne miejsce w całej
procedurze, w którym łatwo wyrządzić szkodę nieodwracalną.

> 🚫 **Wartości sekretnych NIE podawaj przez workflow „Coolify set env".**
> To `workflow_dispatch`, a jego `inputs` **nie są sekretami GitHuba**:
> maskowanie w logach obejmuje wyłącznie zarejestrowane `secrets.*`, więc
> wpisanej ręcznie wartości nie chroni nic. Zostaje ona w rekordzie biegu,
> widoczna dla każdego, kto ma odczyt repozytorium, i **nie da się jej stamtąd
> wymazać inaczej niż kasując bieg**. Sam workflow jej dziś nie drukuje, ale to
> jedna linijka `echo` od zmiany — bez maskowania, które by ten błąd złapało.
>
> Dotyczy to w szczególności klucza B2 **z prawem zapisu**. Sekcja (c) wyżej
> odrzuca trzymanie takiego klucza w sekretach repo, bo wtedy „backup i
> produkcja padają tym samym uprawnieniem". Wpisanie go w pole formularza
> `workflow_dispatch` kładzie go w tym samym repozytorium — tylko gorzej, bo
> jawnym tekstem i bez maskowania.

**Sekrety → panel Coolify, ręcznie.** `coolify-nexus.dynaminds.pl` →
Resources → nexus → Environment Variables. Logowanie jest interaktywne i to
jest zaleta: wartość nie przechodzi przez żaden system, który ją zapamiętuje.

| `key` | `value` | Kiedy |
|---|---|---|
| `BACKUP_S3_ACCESS_KEY` / `BACKUP_S3_SECRET_KEY` | klucz B2 **z prawem zapisu** | najpierw |
| `OBJECT_STORAGE_ENDPOINT` / `_ACCESS_KEY` / `_SECRET_KEY` / `_BUCKET` | te same, których używa backend | najpierw — **bez nich korpus CV nie jest kopiowany**, a to jedyny zbiór bez drugiej kopii |

**Reszta → workflow „Coolify set env"** (`workflow_dispatch`, po jednym kluczu
na bieg). Te wartości nie są sekretami: klucz age jest **publiczną** połówką,
a pozostałe to flagi i liczby. Ich obecność w historii biegów nie szkodzi.

| `key` | `value` | Kiedy |
|---|---|---|
| `BACKUP_AGE_PUBLIC_KEY` | `age1master…,age1drill…` — **wyłącznie połówki publiczne** | najpierw |
| `BACKUP_RUN_ON_START` | `true` | przed włączeniem — błąd konfiguracji wyjdzie w minuty, nie o 02:00 |
| `BACKUP_ENABLED` | `true` | **na końcu**, dopiero gdy `action=backup-status` nie zgłasza już braków |
| `BACKUP_RUN_ON_START` | `false` | po pierwszym udanym biegu |

Po każdej zmianie — niezależnie od drogi — odpal ponownie `action=backup-status`.
To jest test, czy zapis rzeczywiście doszedł, i zarazem jedyny sposób, żeby
sprawdzić wpis z panelu bez oglądania jego wartości.

> Gdyby sekret mimo wszystko przeszedł kiedyś przez `workflow_dispatch`:
> traktuj go jak ujawniony. Kasowanie biegu nie wystarcza za rotację —
> **wygeneruj nowy klucz B2 i unieważnij stary** (`~/.claude/rules/common/security.md`).

### d.2 Sekrety i zmienne repo (bramka 3)

**Sekrety.** Wartości nie podawaj przez `--body` — trafiłaby do historii
powłoki. Klucz prywatny wczytaj z pliku, klucze B2 wklej w ukrytym monicie:

```bash
R=artur-t-96/Nexus

# prywatna połówka klucza DRILLOWEGO (nigdy głównego) — z pliku, bez echa
gh secret set BACKUP_AGE_PRIVATE_KEY --repo "$R" < nexus-backup-drill.key

# klucz B2 read-only z punktu (c) — gh zapyta o wartość i jej nie wyświetli
gh secret set BACKUP_S3_ACCESS_KEY --repo "$R"
gh secret set BACKUP_S3_SECRET_KEY --repo "$R"
```

**Zmienne.** `BACKUP_S3_BUCKET`, `BACKUP_S3_ENDPOINT` i `BACKUP_S3_REGION`
muszą być **znak w znak takie same** jak w vaultcie Coolify — te wartości
wypisuje `action=backup-status` (są na allowliście). Rozjazd choćby w schemacie
`https://` daje drill, który szuka nie w tym miejscu i mówi „brak kopii".

```bash
R=artur-t-96/Nexus

gh variable set BACKUP_S3_BUCKET   --repo "$R" --body "dynaminds-nexus-offsite"
gh variable set BACKUP_S3_ENDPOINT --repo "$R" --body "s3.eu-central-003.backblazeb2.com"
gh variable set BACKUP_S3_REGION   --repo "$R" --body "eu-central-003"
gh variable set BACKUP_S3_PREFIX   --repo "$R" --body "nexus"
gh variable set BACKUP_S3_PROVIDER --repo "$R" --body "Other"
```

Kontrola (wypisuje **nazwy**, nigdy wartości sekretów):

```bash
gh secret   list --repo artur-t-96/Nexus
gh variable list --repo artur-t-96/Nexus
```

`BACKUP_MONITORING_ENABLED` **jeszcze nie teraz** — patrz punkt (e).

---

## (e) Jak potwierdzić, że zadziałało

Kolejność jest częścią procedury: każdy krok sprawdza dokładnie jedną rzecz,
a następny ma sens dopiero po poprzednim.

1. **Konfiguracja.** `Coolify Ops` → `action=backup-status` → werdykt
   „Konfiguracja po stronie Coolify jest kompletna", bieg zielony.
   *To nie jest dowód, że cokolwiek wylądowało.*

2. **Pierwszy bieg naprawdę się wykonał.** Po włączeniu z
   `BACKUP_RUN_ON_START=true` w logach kontenera `backup` mają być linie
   `[backup] ok postgres …`, `ok uploads`, `ok cv_corpus`, `ok qdrant:…`
   i `run complete: 0 failure(s)`.
   **Pierwszy przebieg jest długi** — zasianie ~41 GB / ~139 tys. obiektów.
   `BACKUP_CV_MAX_DURATION` to domyślnie `6h`; przekroczenie zapisuje `cv_corpus`
   jako `error` **celowo** (niepełny korpus to nie kopia), a następny bieg
   wznawia od miejsca zatrzymania. Dwie noce to normalny wynik.

3. **Manifest.** W buckecie `nexus/LATEST.json` ma mieć `failures: 0`, a
   `objects` artefaktu `cv_corpus` — zgadzać się z liczbą obiektów w buckecie
   źródłowym. Wtedy `BACKUP_RUN_ON_START` → `false`.

4. **Drill.** `gh workflow run backup-drill.yml --repo artur-t-96/Nexus`
   i przeczytaj log. To jedyne miejsce w repozytorium, które faktycznie pobiera
   archiwum, **odszyfrowuje je** (`age -d`), odtwarza bazę, puszcza
   `alembic upgrade head`, sprawdza pięć tabel i próbkuje 25 wartości
   `storage_key` względem kopii korpusu CV.
   **Dopiero zielony bieg tutaj znaczy „mamy kopię zapasową".**

5. **Monitoring — dopiero teraz.**

   ```bash
   gh variable set BACKUP_MONITORING_ENABLED --repo artur-t-96/Nexus --body "true"
   ```

   Świadomie na końcu: włączony wcześniej zapala godzinowy job na czerwono
   natychmiast (nie ma czego czytać), a **stale czerwony alarm jest tak samo
   niewidoczny jak brak alarmu**. Od tej chwili zatrzymanie się backupów ma
   objaw: `backup-freshness` w `uptime-probe.yml` czerwienieje w ciągu godziny.

6. **Wyłącz stary skrypt na hoście** (`/root/nexus-offsite-backup.sh` i cron do
   `/var/backups/nexus`) — dopiero po zielonym drillu, żeby dwa mechanizmy nie
   biły się o dysk. Kontekst: `docs/disaster-recovery.md`.

7. **Zaktualizuj blok statusu** na górze `docs/disaster-recovery.md` — datą
   biegu z punktu 4, nie datą wykonania tej procedury.

### Co się dzieje, gdy drill padnie

Od tej zmiany cotygodniowa porażka **z harmonogramu** zakłada issue
`🚨 NEXUS backup drill nie przechodzi` (kolejne tygodnie dopisują komentarz do
tego samego wątku, nie zakładają nowego). Treść rozróżnia dwie sytuacje: „drill
nie ma czym weryfikować" (bramka 3 zamknięta) i „drill miał czym, więc padł na
treści" — bo pierwsza czynność jest w nich inna. Ręczne uruchomienia
(`workflow_dispatch`) issue **nie** zakładają: operator siedzi wtedy nad logiem.

---

## Czego ten runbook NIE rozstrzyga

- **Dopóki `backup-drill.yml` nie przejdzie na zielono, kopię off-site należy
  traktować jak NIEISTNIEJĄCĄ.** Nie „prawdopodobnie działającą", nie „pewnie
  jest". Historia tego repozytorium jest jednoznaczna: drill był zielony przez
  wiele tygodni, **nie odtwarzając niczego** — dopiero gdy zaczął naprawdę
  pobierać i odszyfrowywać artefakt, zrobił się czerwony. Cztery porażki z rzędu
  (27.07, 03.08, 10.08, 17.08) to drill mówiący prawdę, a nie regresja.
- **Nie zakłada bucketa ani nie podnosi limitów B2.** Limity trzeba podnieść
  **przed** pierwszym biegiem, bo B2 egzekwuje je **odmową** (`403`), a nie
  rachunkiem — i uderzą najpierw w zasianie korpusu, a potem w odtwarzanie.
  Wielkości i procedura: `docs/disaster-recovery.md`, *Activation*, punkt 3.
- **Nie odtwarza produkcji.** Procedura odtworzenia po awarii to osobna sekcja
  `docs/disaster-recovery.md` (*Restoring from an off-site copy*).
- **Nie dotyka klucza głównego `age`.** Żaden automat go nie widzi, nie zna
  i nie potrafi odtworzyć. Jego jedynym miejscem jest menedżer haseł
  właściciela; jego utrata jest nieodwracalna niezależnie od stanu wszystkiego
  powyżej.
- **Zielony `backup-status` nie jest dowodem kopii** — mówi tylko, że skrypt ma
  z czym wystartować. Dowodem jest świeży `LATEST.json` (punkt 3) i zielony
  drill (punkt 4).
