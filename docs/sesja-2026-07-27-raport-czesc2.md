# Sesja 2026-07-27 — część druga

> Kontynuacja [`sesja-2026-07-27-raport.md`](./sesja-2026-07-27-raport.md). Tamten raport
> kończył się listą „wymaga Artura" i przejętą kolejką z zatrzymanych sesji równoległych.
> Ta część opisuje, co z tego zostało domknięte — i cztery rzeczy, które wyszły po drodze,
> a których nikt nie szukał.

---

## 1. Backup off-site — uruchomiony, potem naprawiony

Klucze Backblaze weszły, flagi włączone, pierwszy przebieg **w historii tej aplikacji**
ruszył o 20:03. Postgres (289 MB) i uploady (406 MB) wylądowały i zostały potwierdzone
zdalnym `rclone size`. Korpus CV zaczął się kopiować.

I wtedy zaczął się sypać.

### Diagnoza, która była błędna

Pierwszy odczyt brzmiał jednoznacznie: `HeadObject → 403 Forbidden`. Klucz najwyraźniej
nie ma prawa odczytu. Sprawdziłem uprawnienia — `readFiles` **jest** na liście. Sprawdziłem
klucz na obiekcie, który dopiero co wgrałem — też 403. Wniosek: klucz nie umie robić HEAD.

Ten wniosek był zły, a poprowadził mnie w stronę „trzeba zmienić zakres klucza".

### Co było naprawdę

`HEAD` z definicji nie ma ciała odpowiedzi, więc rclone pokazuje gołe „Forbidden". Dopiero
**to samo żądanie jako `GET`** ujawniło treść:

```xml
<Code>AccessDenied</Code>
<Message>Cannot download file, download bandwidth or transaction
         (Class B) cap exceeded.</Message>
```

Backblaze liczy `HEAD` i `GET` jako transakcje **klasy B** — limitowane dziennie. `PUT`
jest klasy **A**: darmowy i bez limitu. Stąd obraz, który zmylił: wgrywanie działa, odczyt
pada. rclone domyślnie robi `HEAD` po każdym wgranym obiekcie; przy 136 tys. plików
wyczerpało to dzienną pulę w kilkanaście minut.

Zmierzone w locie: **22 438 obiektów wgranych przy 16 088 odrzuconych** — ponad dwie
piąte korpusu, a odsetek rósł, bo raz wyczerpana pula nie wraca do końca doby.

**Poprawka** (#962): `RCLONE_S3_NO_HEAD=true` globalnie, nie flagą przy `sync` — bo dotyczy
też małych `rcat`. I dokładnie to się potem stało: przebieg dobił do końca, wgrał wszystkie
artefakty, po czym **`LATEST.json` padł na HEAD-zie i położył cały przebieg**:

```
[backup] FAILED manifest: could not write .../LATEST.json
[backup] run complete: 8 failure(s)
```

Zweryfikowane na produkcji na żywym wyczerpanym limicie: ten sam `rcat` bez zmiennej →
2 błędy, ze zmienną → 0.

### Co zostaje po stronie konta

**Odtworzenie backupu jest dziś niemożliwe.** Pobieranie też jest klasy B. Backup, którego
nie da się ściągnąć, nie jest backupem — więc trafiło to jako **pierwszy krok** procedury
w `docs/disaster-recovery.md`, z jednolinijkowym testem, czy limit nadal blokuje. Realny
koszt jest znikomy (całe 37 GB grubo poniżej euro); limit istnieje po to, żeby nie było
niespodzianek na rachunku, a nie żeby zostać na domyślnej wartości.

### Efekt uboczny: nieudane przebiegi zabierają miejsce

Nazwy obiektów zawierają znacznik czasu (`nexus-${STAMP}.dump.age`), więc każde ponowienie
tworzy **nową** kopię. Retencja jest — słusznie — zablokowana, dopóki przebieg ma błędy.
Efekt: pętla ponawiająca co 15 minut dokładała ~700 MB, kubełek urósł do 11,3 GB przy
2 zrzutach Postgresa, 2 archiwach uploadów i 4 snapshotach Qdranta. Sidecar zatrzymany
ręcznie do czasu deployu z poprawką.

---

## 2. Dozór backupu krzyczał w próżnię

`BACKUP_MONITORING_ENABLED` było ustawione na `true` od 11:47 — **bez sekretów dostępowych**.
Efekt: `uptime-probe` czerwienił się **co godzinę**, 12+ razy, na `cannot read LATEST.json`.

Zamysł w kodzie jest wyraźny: „deliberately a skipped job rather than a passing one" — nie
twierdzić nic o backupach, których się nie odczytało. Stan był trzeci, najgorszy: twierdzenie
„awaria" bez podstaw, czyli dokładnie to, co uczy ignorować czerwone workflow.

Cofnięte na `false`. Zmienne opisowe (bucket, endpoint, region, prefix, provider, max-age)
ustawione. Włącznik wraca po pierwszym czystym przebiegu i rotacji klucza.

---

## 3. FastAPI 0.140 — komunikat, który kłamał

Bump grupy backendowej padł na CI z czterema awariami, które brzmiały alarmująco:
`/api/fireflies/*` niezarejestrowane, bramki `schema-drift` i `candidate-pii-orphans`
nieobecne, a kontrakt autoryzacji domagający się **skasowania 148 wpisów baseline'u**.

Gdyby posłuchać komunikatu, wypatroszyłoby to kontrakt bezpieczeństwa obejmujący 233 trasy.

Trasy nie zniknęły. Od FastAPI 0.139 `app.routes` nie jest już spłaszczane: każde
`include_router()` staje się obiektem `_IncludedRouter` (u nas 139 sztuk), a pełna ścieżka
to `include_context.prefix` + ścieżka z `original_router.routes`. Testy iterujące `app.routes`
widzą 4 trasy zamiast 786 i wnioskują, że reszta nie istnieje.

Trzy pomiary, które to rozstrzygnęły:

| Pytanie | Odpowiedź |
|---|---|
| Czy zejście na 0.139 pomaga? | Nie — zmiana jest w obu wersjach |
| Czy dotyka kodu produkcyjnego? | Nie — zero iteracji po `app.routes` w `app/` |
| Czy FastAPI jest jedyną przyczyną? | Tak — po cofnięciu samego FastAPI: 786 tras, 15 passed, 0 failed |

Grupa poszła bez FastAPI (13 aktualizacji, #961). Adaptacja introspekcji to osobne zadanie
i musi udowodnić **równoważność** — że zbiór ścieżek zrekonstruowany po nowemu jest
identyczny z dzisiejszym, a nie tylko że testy świecą na zielono.

---

## 4. „Nie ma Go" wykluczało 191 osób zamiast 5

PR #960 z zatrzymanej sesji naprawiał dopasowanie umiejętności: `%Go%` → `%"Go"%`. Opis
argumentował poprawnie, ale skalę zmierzyłem sam, na produkcyjnej bazie 49 tys. kandydatów:

| Wzorzec | Trafień |
|---|---|
| stary `%Go%` | **196** |
| nowy `%"Go"%` | **5** |
| fałszywych | **191** (w tym 15 z Django) |

`skills_none` jest **twardym filtrem**. Rekruter wpisujący „nie ma Go" tracił z wyników
191 osób, z których tylko 5 faktycznie zna Go — i nie miał jak tego zauważyć. 97% fałszywych
wykluczeń.

---

## 5. Nocny E2E był czerwony od tygodni

Wszystkie 9 speców Playwrighta padało co najmniej od 22.07: bramka deny-by-default (#812)
objęła też `/preview/*`, więc harnessy chodzące bez sesji dostawały 307 na `/login`.
Jedyny mechanizm E2E nie dawał żadnego sygnału.

#959 otwiera **dwie dokładne ścieżki**, nie prefiks. Przed merge'em sprawdziłem twierdzenie,
które decyduje o bezpieczeństwie: `grep` po `fetch|apiClient|useQuery|axios` w tych stronach
i ich komponentach → **zero trafień**. `/preview/shell` renderuje prawdziwy `SidebarV2`
z role-gatingiem i zostaje za bramką; test pilnuje obu stron granicy.

---

## 6. Tailwind 4 — przegląd wizualny bez regresji

Przejście po zalogowanej produkcji, porównanie z bazą zebraną przed merge'em:

| Obszar | Wynik |
|---|---|
| `/candidates`, `/jobs`, `/cv-generator` | pozycje pikselowo identyczne |
| Modal (Radix) | scroll-lock, `aria-modal`, focus w środku, 36 elementów focusowalnych, ESC działa |
| `max-h-[80vh] overflow-y-auto` | przeżył codemod — przyciski zapisu osiągalne |
| Podmiana palety w runtime | działa (`@theme inline` → `var(--primary)`, nie wypalony kolor) |
| Tryb Kids | pełna warstwa dekoracyjna renderuje się |
| Sidebar | jedyna zmiana: odstępy z nierównych (37/29/30/29 px) na równe (37/38/38/38) — poprawa |

---

## 7. Zdublowana praca — druga raz tego samego dnia

Zbudowałem gałąź odsprzęgającą testy od kolejności. #952 z zatrzymanej sesji robi to samo
**i więcej**: ta sama poprawka `conftest`, plus auto-discovery w `ci.yml` (−286 linii listy
plików), plus naprawa dokładnie tego testu, który u mnie został czerwony, plus wycofanie
kategorii `SUITE_INTERFERENCE`. Moja gałąź skasowana, #952 zrebasowane.

Pierwszy raport odnotował ten sam wzorzec (#948 i #949 naprawiały ten sam objaw). To już
nie przypadek, tylko koszt równoległości bez rozłącznych zakresów: **przed podjęciem
zadania z przejętej kolejki trzeba sprawdzić, czy nie ma na nie otwartego PR-a.**

Przy rozwiązywaniu konfliktu #952 sprawdziłem rzecz, która byłaby cichą regresją: czy lista
`--ignore` nie wyklucza pliku, który main dziś uruchamia. Nie wyklucza — 288 uruchamianych,
26 wykluczonych, zero przecięcia.

---

## 8. Otwarte

**Wymaga Artura:**

1. **Limity Backblaze** — `secure.backblaze.com` → Caps & Alerts → dzienny limit powyżej
   zera. Bez tego odtworzenie backupu nie zadziała. Koszt realny: całe 37 GB poniżej euro.
2. **Rotacja klucza B2** — `applicationKey` wyświetlił się plaintextem na stronie i trafił
   do transkryptu sesji. Klucz jest zawężony do jednego kubełka, ale należy go wymienić.
3. **#384** — decyzja produktowa o generatorze CV (`allow_incomplete`).
4. **`head_of_recruitment`** — backend odmawia tej roli zakładania ofert i klientów.

**Do potwierdzenia automatycznie:** `checks.traffit` po nocnym syncu 02:00 UTC — pierwszym
z naprawą #921. Ręczny sync uruchomiony o 20:15 został zabity o 20:46 przez redeploy po
merge'u #958; **długie zadania w tle nie przeżywają deployu i nie mają wznawiania w locie.**

**Odłożone świadomie:** adaptacja introspekcji tras do FastAPI ≥0.139 (osobny PR, wymaga
dowodu równoważności), włączenie dozoru świeżości backupu (po pierwszym czystym przebiegu).

---

## 9. Liczby

| | |
|---|---|
| PR-y zmergowane w tej części | 4 (#958, #962, #960, #959) |
| PR-y zamknięte z uzasadnieniem | 5 (#53, #299, #519, #564, #950) |
| Dependabot | 5 → 0 otwartych |
| Fałszywych wykluczeń w wyszukiwarce | 191 z 196 (97%) |
| Fałszywych alarmów uptime-probe | 12+, zatrzymane |
| Obiektów w mirrorze CV przed poprawką | 22 438 z ~136 000 |
