# Talent Radar — raport z wdrożenia

Stan na 2026-08-11. Moduł: wklejasz treść requestu, dostajesz ranking bazy
kandydatów. Nie zakłada rekrutacji.

## Co wjechało

| PR | co |
|---|---|
| #1115 | Silnik: `POST /api/talent-radar/search`, serwis, filtr dopuszczalności, testy |
| #1116 | Rename kolidującego źródła importu `talent_radar` → `tr_legacy` (migracja 0222) |
| #1117 | Naprawa SQL-a, który nie wykonywał się od 24.07, + bramka `PREPARE` w CI |
| #1119 | UI: sekcja `/talent-radar`, tożsamość kandydata w wynikach, harness stanów |
| #1120 | Casty w imporcie Traffita przestają po cichu ucinać (+ savepoint) |

## Decyzje, które nie są kosmetyczne

**Klient jest wymagany.** Filtr dopuszczalności sprawdza względem niego
blacklistę, NDA, konflikty konkurencyjne i weto hiring managera. Klient
opcjonalny dałby listę, w której te kontrole cicho nie zaszły — dokładnie
defekt naprawiony w `/ai-matches` (#1109). Konsekwencja w UI: własny picker,
bo `ContractsClientPicker` oferuje „Wszyscy klienci" jako wybór, a tutaj taki
wybór z definicji nie może zadziałać.

**Degradacja retrievalu nie jest pustym stanem.** Gdy Qdrant albo Voyage
milczy, odpowiedź niesie `meta.degraded` i zero wyników. Wyrenderowanie tego
jako „brak dopasowań" byłoby kłamstwem w najgorszą stronę — rekruter uznałby,
że w bazie nie ma nikogo takiego. Harness `/preview/talent-radar` trzyma te
stany obok siebie, żeby różnica nie zniknęła przy kolejnej zmianie.

**Wyniki niosą mniej niż profil.** Bez e-maila, telefonu i stawki. Lista
rankingowa służy do decyzji kogo otworzyć; kontakt jest za tym kliknięciem, więc
wysyłanie go w każdej odpowiedzi poszerzałoby ekspozycję danych osobowych bez
wpływu na jakąkolwiek decyzję podejmowaną na tym ekranie.

## Czego pomiar NIE potwierdził

**Ranking nie jest wąskim gardłem — retrieval jest.** Baseline z 2026-08-10
(`docs/matching-eval-2026-08-10-baseline.md`) dał NO-GO: przy puli 200 sufit
recall wynosi 13,6%, czyli scoring nie widzi 86,4% ground truth. Podniesienie
puli do 1000 dało jedyny zmierzony zysk jakościowy (P@5 0,080 → 0,110). Strojenie
wag przed naprawą retrievalu mierzyłoby szum — i dlatego Talent Radar świadomie
NIE dostał własnych wag ani progów.

## Błędy popełnione po drodze, warte zapamiętania

**Trzy defekty przeszły przez zielone CI w jednej instrukcji SQL.** Przyczyna
wspólna: każdy test dotykający surowego SQL podmienia `db.execute` na
`AsyncMock`, więc instrukcja jest asertowana, ale nigdy nie trafia do
PostgreSQL. Zamknięte bramką `PREPARE` (#1117), która korzysta z Postgresa już
obecnego w jobie pytest.

**Bramka sama miała ten sam defekt co kod, który miała pilnować.** Pierwsza
wersja przepisywała `:nazwa` na `$n` własnym regexem, który nie znał reguły
SQLAlchemy — przez co planowała inny string, niż wykonuje aplikacja, i potrafiła
zarówno przepuścić błąd, jak i wymyślić awarię. Naprawione przez usunięcie
drugiej implementacji: SQL renderuje sam SQLAlchemy.

**Pierwsza wersja poprawki zamieniała głośną awarię w cichą utratę danych.**
`CAST(:p AS varchar(n))` ucina; dopiero kolumna odrzuca. Wyszło dopiero z
adversarialnego audytu i zostało zamrożone testem.

**Type-check i testy nie zastępują obejrzenia strony.** Dwie rzeczy w UI wyszły
dopiero w przeglądarce, po zielonym `tsc`: `<Button asChild>` wywalał stronę w
runtime (Radix `Slot` dostawał dwoje dzieci), a picker klienta zapraszał do
wyboru, którego nie wolno dokonać.

## Otwarte

- **Wag się nie stroi** dopóki sufit retrievalu nie wzrośnie. Plan fal: patrz
  `~/.claude/plans/` (Fala 2 — chunkowanie CV, Fala 3 — backfill pól z CV).
- **`Button asChild` jest zepsuty w prymitywie** (slot na spinner obok dziecka),
  ma jeszcze trzy wywołania poza Talent Radarem. Osobna decyzja.
- **Nocny sync Traffita może zacząć zgłaszać błędy**, których wcześniej nie
  pokazywał — wiersze dziś po cichu ucinane trafią do `progress.errors`. To jest
  cel zmiany, ale warto wiedzieć, skąd się wzięły.
- **46 miejsc w `app/`**, gdzie `text()` dostaje wyrażenie zamiast literału, jest
  poza zasięgiem bramki `PREPARE`. Katalog `alembic/` **nie** jest luką — CI
  wykonuje `upgrade heads`, co jest mocniejszą walidacją niż `PREPARE`.
