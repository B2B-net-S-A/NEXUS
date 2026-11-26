---
name: sciezka
description: Ścieżka na stagingu z laptopa przed PR-em, który zmienia ekran, PDF, Worda, CV albo maila — każdą rolą z mapy obszaru, na kopii produkcji z kodem gałęzi i flagami jak na produkcji; kończy się paragonem, bez którego hook sciezka-stagingu-gate.js nie otworzy PR-a. Użyj przed `gh pr create` / `gh pr ready` albo gdy hook zablokował PR.
argument-hint: "<obszar: cv-do-klienta | ruch-karty-przeglad-dl | zamowienia | finanse>"
---

# /sciezka <obszar>

Reguła i powód: `docs/claude/podstawy/test-calej-sciezki-na-stagingu.md`.
Role obszaru: `docs/claude/podstawy/sciezki/mapa-rol.json`. Scenariusz: `scenariusze/<obszar>.md`.
Obszaru nie ma w mapie → przejdź ścieżkę ręcznie i dopisz nowy scenariusz oraz wpis w mapie w tym samym PR-ze.

Paragon: `~/.nexus-staging/e2e/<gałąź>.md` (gałąź z `/` zamienionym na `-`), poza repo,
bo zrzuty mają prawdziwe dane. Bramka czyta z niego dwie tabele (format niżej).

## Przed kodowaniem: mapa wpływu

```bash
python3 scripts/impact_map.py   # po pierwszym commicie; przed nim: --diff origin/main
```

Skrypt wypisuje inne miejsca (ekrany, komponenty, PDF/Word/maile, Jarvis, eksporty,
przewodniki ekranów), które używają pól, endpointów i komponentów z diffu. Dla każdego
wpisz w kolumnie „Decyzja” jedno z trzech:
- `✓ zmienione` — zmieniłeś je w tej gałęzi (wtedy też przechodzi ścieżkę),
- `— nie: <powód>` — np. „pokazuje tylko historię, nowe pole niepotrzebne”,
- `? pytanie do Artura` — zadane przez AskUserQuestion; po odpowiedzi zamień na ✓ albo —.

Bo przy dodaniu informacji na jednym ekranie ta sama informacja zwykle żyje też gdzie
indziej (np. `candidate.rate_from`: panel osoby, profil, PDF CV, Jarvis, eksport).
Uruchom ponownie przed krokiem 6 — nowe commity mogą dodać miejsca. Tabela idzie do
paragonu i do opisu PR-a w sekcji `## Wpływ na inne miejsca`.

## 0. Flagi

```bash
python3 scripts/staging/compare_flags.py --diff origin/main...HEAD --ssh-host <host z rutyny nocnej> --ssh-identity <klucz>
```

Host i klucz są w rutynie nocnej (`podstawy/staging-na-laptopie.md`), nie w repo.
Kod 1 = flaga z diffu różni się od produkcji: ustaw ją w `.env.staging-flags.local`
obok `.env.staging.local` i przebuduj backend gałęzi (krok 1). Tabelę wklej do paragonu.
Gdy w flagach z diffu po zmianie nie ma różnicy, wpisz w tabeli wartość ustawioną.

## 1. Gałąź na danych stagingu

Najpierw własna para portów worktree (pierwsza wolna z 3101–3199 / 8101–8199):

```bash
eval "$(python3 scripts/staging/free_ports.py)"   # FRONT_PORT, BACKEND_PORT
```

Backend gałęzi na `$BACKEND_PORT`, front na `$FRONT_PORT` z `NEXT_PUBLIC_API_URL` na ten
backend — komendy w `podstawy/test-calej-sciezki-na-stagingu.md` (sekcja „Gałąź na danych
stagingu”). Backend gałęzi stawiasz także przy zmianie samego frontu, bo CORS wspólnego
stagingu (8100) przyjmuje tylko 3100 i 3101. Porty idą do paragonu.
Zmiana schematu = własna kopia bazy (ta sama sekcja), nigdy wspólna baza stagingu.

## 2. Bramki lekcji

„Zaloguj jako” trafia na Poligon albo „Nowości dnia”, zanim pokaże ekran. Na czas
ścieżki wyłącz je w bazie stagingu, a wcześniejsze wartości zapisz w paragonie:

```bash
docker exec nexus-staging-postgres-1 psql -U nexus -d <baza stagingu> -c \
  "select key, value from app_settings where key ilike '%poligon%' or key ilike '%novelt%' or key ilike '%porcj%';"
```

Ustaw je na wyłączone (`update app_settings set value = … where key = …`), po kroku 6 przywróć
zapisane wartości. Nocna kopia i tak je odtworzy, ale inne sesje pracują na tej bazie teraz.

## 3. Scenariusz

Przeczytaj `scenariusze/<obszar>.md` i plik reguł obszaru, który wskazuje. Wypisz mapę
„kto → co robi → co widzi następny”, razem z rolą, która ma czegoś nie widzieć.

## 4. Każda rola

`python -m scripts.staging_login_as --role <rola>` (wymiana tokenu na ciasteczko — plik reguły,
sekcja 3), wbudowana przeglądarka 1280 × 720, kroki ze scenariusza, zrzut po każdym kroku
do `~/.nexus-staging/e2e/<gałąź>/<n>.png`. Plik pobrany (PDF, Word) otwórz i obejrzyj, Worda
też edytuj. Rola, która ma nie widzieć: brak na ekranie **i** 403 z API (`curl` jej tokenem).

## 5. Błąd

Krok na czerwono: test, który go odtwarza i pada → poprawka → ten krok od nowa,
a gdy poprawka zmienia to, co widzą inne role, cała ścieżka od nowa.

## 6. Paragon i opis PR-a

Zapisz paragon (po ostatnim commicie z ekranem — bramka porównuje czas):

```markdown
gałąź <sha> · baza <nazwa> · backend <BACKEND_PORT> · front <FRONT_PORT> · <data godzina>

| flaga | staging | prod | w diffie? |
|---|---|---|---|
| CV_NEW_LAYOUT_ENABLED | true | true | tak |

| # | Rola | Krok | Wynik | Zrzut |
|---|---|---|---|---|
| 1 | Rekruter | Nowe CV, zdanie 2 poprawione | ✓ | 1.png |
| 2 | Delivery Lead | QC CV → „Jak u klienta” | ✗ → poprawka f81c2 → ✓ | 2.png |

## Wpływ na inne miejsca

| Miejsce | Decyzja |
|---|---|
| Jarvis — `rate_from · backend/app/services/jarvis/tools.py` | ✓ zmienione |
| eksport — `rate_from · backend/app/api/import_export.py` | — nie: eksport ma osobną kolumnę stawki |

Bramki lekcji przed ścieżką: <klucz=wartość, …> (przywrócone)
Strażnik: <plik testu, np. frontend/src/__tests__/cvQcPreview.test.tsx> / nie dotyczy

## Nie sprawdzone na stagingu

- <krok> (<powód: poczta wyłączona, KSeF, pętla>); na produkcji ma być widać: <co>
```

**Strażnik:** błąd znaleziony na ścieżce, który może wrócić w innym miejscu, dostaje
test w CI (plik w tej gałęzi), a nie notatkę w pamięci. Bo notatkę czyta tylko sesja,
która trafi na ten sam plik pamięci, a CI pilnuje każdego PR-a. „nie dotyczy”, gdy ścieżka
nie znalazła błędu albo błąd był jednorazowy (np. literówka w tekście).

Bramka blokuje paragon bez sekcji „Wpływ na inne miejsca” albo z miejscem z `impact_map` bez decyzji
(pustą albo `?`) i bez linii `Strażnik:`. Kolumna „Rola” = nazwa z mapy ról. Każda rola z mapy musi mieć co najmniej jeden wiersz z `.png`.
Do opisu PR-a idzie sekcja `## Ścieżka na stagingu`: tabela rola · kroki · wynik, bez nazwisk,
id i zrzutów, porty i linia `Strażnik: …`. Osobno sekcja `## Nie sprawdzone na stagingu`, jeden
punkt na linię z tym, co ma być widać na produkcji; po wdrożeniu sprawdza ją rutyna „Kontrola po
wdrożeniu” (plik reguły, §6).
Na koniec: przywróć bramki lekcji, `docker stop nexus-staging-backend-branch-$BACKEND_PORT`, zatrzymaj front.
