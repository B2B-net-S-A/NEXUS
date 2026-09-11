# UAT NEXUS — plan testów końcowych przed startem produkcyjnym

> Ten katalog jest kompletnym planem testów akceptacyjnych NEXUS-a. Jest napisany tak,
> żeby dowolny agent AI (Claude, Codex, inny) albo człowiek mógł wziąć jedną kartę,
> przeczytać ją od góry do dołu i wykonać bez dodatkowego kontekstu.
>
> **Stan: wersja 1, 2026-09-11.** Testowany SHA wpisuje się do `manifest.yaml` przy starcie fali.

## Jak korzystać z tego katalogu

1. Przeczytaj [00-zasady-dla-agenta.md](00-zasady-dla-agenta.md). To jedyny plik, który
   MUSI przeczytać każdy wykonawca, niezależnie od modułu.
2. Wykonaj [01-fala-0-przygotowanie.md](01-fala-0-przygotowanie.md). Bez zielonych
   warunków wstępnych nie zaczyna się Fali 1.
3. Weź jedną kartę z `moduly/` (Fala 1) albo `przeplywy/` (Fala 2). Karta mówi: co
   testować, jaką personą, w jakim trybie, czego NIE klikać, co zapisać.
4. Wynik zapisz według [05-szablon-zgloszenia.md](05-szablon-zgloszenia.md) do katalogu
   `wyniki/` (ignorowany przez git — repo jest publiczne).
5. Po Fali 1 i 2 przejdź do [06-fala-3-poprawki-i-regresja.md](06-fala-3-poprawki-i-regresja.md),
   potem [07-fala-4-pilotaz.md](07-fala-4-pilotaz.md).

Prompt, który wystarczy wkleić agentowi, jest w [04-szablon-promptu.md](04-szablon-promptu.md).
Plik [manifest.yaml](manifest.yaml) opisuje ten sam plan maszynowo — dla orkiestratora,
który rozdaje karty wielu agentom naraz.

## Dlaczego plan wygląda tak, a nie inaczej

- **Nie ma stagingu.** Testujemy na produkcji (`https://nexus.dynaminds.pl`, API
  `https://api.nexus.dynaminds.pl`). Dlatego plan rozdziela **tryb tylko do odczytu**
  (bezpieczny, równoległy, oczami każdej roli przez „Podgląd jako użytkownik”) od
  **trybu z zapisem** (jeden wykonawca naraz, wyłącznie na danych z prefiksem `[QA-E2E-…]`).
- **Backend blokuje zapisy w podglądzie.** Gdy admin ogląda aplikację jako inny
  użytkownik, każda mutacja zwraca 403 (`backend/app/api/deps.py`, sekcja „podgląd jako
  użytkownik”). To jest fundament bezpieczeństwa Fali 1.
- **Moduły łapią błędy na ekranach, przepływy łapią błędy między modułami.** W NEXUS-ie
  najgroźniejsze błędy siedzą na szwach: zatrudnienie → szkic zamówienia, podpis umowy
  B2B → aktywny kontrakt, zamówienie → stawki i okres w kontrakcie. Dlatego są osobne
  karty przepływów P1–P4.
- **Jeden SHA na falę.** Na `main` wchodzi kilkanaście–kilkadziesiąt zmian dziennie,
  a każdy deploy restartuje kontener i przerywa zadania w tle. Podczas fali NIE merguje
  się nowych funkcji, tylko poprawki z tej fali. Testowany SHA jest zapisany w
  `manifest.yaml` i w każdym zgłoszeniu.
- **AI nie potwierdzi, że liczby są biznesowo prawdziwe.** Agent sprawdzi, że kafel
  równa się sumie kolumny. Nie sprawdzi, że MRR klienta to naprawdę tyle. Stąd Fala 4
  (pilotaż z ludźmi) jest częścią planu, nie dodatkiem.

## Struktura katalogu

```
docs/uat/
├── README.md                          ← ten plik
├── manifest.yaml                      ← plan maszynowo: moduły, trasy, persony, tryb, zależności
├── 00-zasady-dla-agenta.md            ← OBOWIĄZKOWE dla każdego wykonawcy
├── 01-fala-0-przygotowanie.md         ← warunki wstępne + komendy sprawdzające
├── 02-dane-testowe.md                 ← jak założyć i posprzątać dane [QA-E2E-…]
├── 03-macierz-rol.md                  ← 9 ról × sekcje/trasy: co ma być widoczne, co odmówione
├── 04-szablon-promptu.md              ← prompt do wklejenia agentowi
├── 05-szablon-zgloszenia.md           ← format zgłoszenia błędu i raportu z karty
├── 06-fala-3-poprawki-i-regresja.md   ← jak naprawiać, retestować, dopisywać Playwright
├── 07-fala-4-pilotaz.md               ← pilotaż z 2–3 osobami
├── moduly/                            ← Fala 1: 14 kart, tryb tylko do odczytu
│   ├── M00-wejscie-i-powloka.md
│   ├── M01-kandydaci.md
│   ├── M02-wyszukiwanie-i-dopasowanie.md
│   ├── M03-rekrutacje-i-pipeline.md
│   ├── M04-profil-championa.md
│   ├── M05-generator-cv.md
│   ├── M06-klienci.md
│   ├── M07-zamowienia.md
│   ├── M08-kontrakty-i-umowy-b2b.md
│   ├── M09-finanse.md
│   ├── M10-insights-i-dashboardy.md
│   ├── M11-administracja.md
│   ├── M12-strony-publiczne.md
│   └── M13-automaty-w-tle.md
├── przekrojowe/                       ← Fala 1: 3 kontrole przez wszystkie moduły
│   ├── A-macierz-rol.md
│   ├── B-spojnosc-liczb.md
│   └── C-sentry.md
├── przeplywy/                         ← Fala 2: 4 przepływy z zapisem, jeden wykonawca naraz
│   ├── P1-kandydat-do-werdyktu-hm.md
│   ├── P2-zatrudnienie-umowa-kontrakt.md
│   ├── P3-zamowienia-md-i-kosztowe.md
│   └── P4-wypowiedzenie-i-raporty.md
└── wyniki/                            ← wyniki i zgłoszenia; katalog w .gitignore (repo publiczne)
```

## Harmonogram (fale)

| Fala | Co | Tryb | Kto | Czas |
|---|---|---|---|---|
| 0 | warunki wstępne, dane testowe, wybór SHA | zapis (tylko dane testowe) | człowiek + 1 agent | 1 dzień |
| 1 | 14 modułów + 3 kontrole przekrojowe | **tylko odczyt**, równolegle | do 17 agentów naraz, każdy z osobną sesją przeglądarki | 1–2 dni |
| 2 | 4 przepływy P1–P4 | **zapis na danych testowych**, sekwencyjnie | 1 agent; człowiek przy akcjach ze stop-listy | 2 dni |
| 3 | poprawki (jeden PR na moduł), retest, testy Playwright dla przepływów MUST | — | człowiek + agenci | ~tydzień |
| 4 | pilotaż: 2–3 osoby robią prawdziwą pracę w NEXUS-ie | prawdziwe dane | ludzie | ~tydzień |

Fala 3 jest warunkiem sensu całości: wyniki Fali 1–2 dezaktualizują się po tygodniu
normalnych deployów.

## Kryteria startu produkcyjnego (definition of done całego UAT)

- [ ] Zero otwartych zgłoszeń P0 i P1 (definicje priorytetów w `00-zasady-dla-agenta.md`).
- [ ] Każdy przepływ oznaczony MUST w `manifest.yaml` jest zielony dla każdej roli z pilotażu.
- [ ] Cotygodniowy test odtwarzania backupu (`.github/workflows/backup-drill.yml`) jest **zielony**.
  Stan 2026-09-11: czerwony trzy tygodnie z rzędu (24.08, 31.08, 07.09), bo drill nie ma
  dostępu do kopii off-site ani klucza do jej odszyfrowania. To blocker startu.
- [ ] `/api/health` bez pozycji `degraded`/`unhealthy` (stan 2026-09-11: `traffit = degraded`).
- [ ] `/api/health/deep` zielony.
- [ ] Nocny bieg Playwright (`e2e.yml`) zielony 3 noce z rzędu i obejmuje przepływy MUST.
- [ ] Decyzja o okresie przejściowym z Traffitem zapisana (patrz niżej).
- [ ] Osoby z pilotażu potwierdzają na piśmie, że kwoty (MRR, marże, MD) zgadzają się z tym, co znają.

## Decyzje otwarte (do podjęcia PRZED Falą 0)

1. **Kto zaczyna pierwszy** (role, liczba osób) i co musi działać w dniu startu. Od tego
   zależy, które moduły dostają głębokość „pełna”, a które „przegląd”. Domyślnie plan
   zakłada głębokość pełną dla M05, M07, M08, M09, M12 i przegląd dla reszty.
2. **DynaReporter** (`/dynareporter/*`): testujemy czy wygaszamy? Jeśli wygaszamy — M10
   pomija sekcję DR, a M00 sprawdza tylko, że linki do DR nie prowadzą w białe strony.
3. **Okres przejściowy z Traffitem.** Import Traffit → NEXUS działa co noc w jedną stronę
   (`TRAFFIT_SYNC_ENABLED`). Zapis zwrotny NEXUS → Traffit jest wyłączony
   (`TRAFFIT_OUTBOUND_ENABLED=false`, `TRAFFIT_DRY_RUN=true`). Praca zrobiona w NEXUS-ie
   nie wraca do Traffita. Trzy opcje: (a) twarde cięcie w dniu startu, (b) równoległa
   praca w obu systemach przez N tygodni z ręcznym uzgadnianiem, (c) włączenie zapisu
   zwrotnego (osobny program, patrz `traffit-bidirectional-program` w pamięci projektu).

## Powiązane dokumenty w repo

- [docs/qa-process-runbook.md](../qa-process-runbook.md) — metoda „najpierw Sentry, potem klikanie”; ten plan ją rozszerza.
- [docs/qa-session-2026-05-27.md](../qa-session-2026-05-27.md) — poprzednia sesja QA: 30 zgłoszeń, 3 false positive.
- [frontend/e2e/](../../frontend/e2e/) — istniejące testy Playwright; `flow-stubs-todo.spec.ts` zawiera 28 przepływów czekających na implementację.
- [CLAUDE.md](../../CLAUDE.md) — decyzje produktowe; karty modułów cytują z niego konkretne reguły jako oczekiwane zachowanie.
