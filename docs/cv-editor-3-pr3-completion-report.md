# Edytor CV 3 — PR 3: prosty ekran edytora i karty (14.10.2026)

Propozycja i makiety: https://claude.ai/artifact/1g1FJJ2TtojTJSFjmZQj5Z
(„Ekran 1” i „Ekran 5”). Kierunek D1–D6 i „bardzo, bardzo prosto” —
decyzje Artura z 14.10.2026. Reguły: `docs/claude/generator-cv/edytor-cv-pelny-ekran.md`
(sekcja „Prosty ekran edytora”, z siedmioma zasadami prostoty z makiet)
i `docs/claude/generator-cv/cv-w-procesie.md` („Prosta karta”). Bazą jest
PR 2 (strony PDF z pliku Word).

## Co było nie tak

- Nagłówek edytora miał dwa rzędy i kilkanaście przycisków (Drukuj / PDF,
  Pobierz szkic DOCX, Zapisz, Typ akapitu, Dodaj, AI, Polecenie, Historia,
  Pokaż źródła, Do poprawy (N), przyciski stanowiska), a przy 1280 px obok
  kartki mieścił się jeden z dwóch paneli, wybierany regułą, której nikt nie
  znał. Zespół: „chaos, nie rozumiemy”.
- Pogrubienie wymagań klienta było schowane w panelu uwag i tylko wtedy, gdy
  QC je zgłosił.
- Karta „CV do klienta” pokazywała plakietki i rząd przycisków zamiast CV.

## Co weszło

- **Nagłówek w jednym rzędzie** (sprawdzone przy 1280×720): Zamknij, osoba,
  pasek (cofnij, pogrubienie, lista, „Do lewej” / „Wyjustuj”, „Pogrub
  wymagania (N)”, „Więcej”), „Edycja | Jak u klienta”, „Zapisano 14:01”,
  „Oryginał”, „Pobierz Word”.
- **„Więcej”**: Dodaj, Typ akapitu, stanowisko pod kursorem, AI na
  zaznaczonym tekście, „Wyjustuj całe CV” / „Całe CV do lewej”, polecenie,
  historia wersji, „Pobierz PDF”, „Drukuj”.
- **„Pogrub wymagania (N)”** — liczba z QC, klik woła tę samą poprawkę co
  „Pogrub wszystkie” w panelu (`qc/transform`, jeden krok cofania).
- **Jedna kolumna obok kartki**: „Do poprawy” albo oryginał; historia i plan
  zajmują ją na czas decyzji. Układ dwóch paneli od 1540 px zniknął.
- **„Gotowe” w stopce** zamiast „Zapisz” w nagłówku; z przekazaniem „Gotowe”
  i „Gotowe, przekaż do DL →”. Ścieżka zapisu i zatwierdzenia bez zmian.
- **Kartka jak plik**: czerwone kwadratowe punkty, czerwone linie między
  sekcjami i stanowiskami, edukacja w ramce tabeli z nagłówkiem.
- **Karta**: miniatura prawdziwej pierwszej strony z liczbą stron (klik =
  wszystkie strony), „Otwórz i popraw”, „Pobierz Word”, menu „⋯” (Pobierz
  PDF, Użyj innego CV, Historia wersji, Wygeneruj ponownie); panel „Z czego
  powstało” zwinięty do zdania z „Zmień”.
- Przewodnik Jarvisa ekranu osoby (`jobs.person`) mówi o „Gotowe, przekaż do
  DL” — przestemplowany.

## Testy

- Frontend (lokalnie, pliki zmienione): pasek (20, w tym „Więcej”, podmenu,
  „Wyjustuj całe CV”, „Pogrub wymagania”), okno edytora (16 + 24 układ
  i historia + 10 przekazanie), harness edytora (24, bez sieci), karta (46),
  miniatura (6), `cv-editor-issues` (35, w tym `boldRequirements`), inwentarz
  funkcji (337), granice ciężkich paczek, harnessy. `npm run type-check`
  i eslint czyste. Razem 811 testów w 30 plikach.
- Backend: testy przewodników Jarvisa (27).
- Zrzuty 1280×720 (Playwright, harnessy): edytor (szkic, „Więcej”,
  „Oryginał”, przekazanie DL), karta (miniatury, „⋯”, zwinięty panel).
  Pierwszy zrzut karty pokazał liczbę rzeczy do sprawdzenia złamaną w słupek
  obok miniatury i brak odstępów w podmenu — poprawione i sprawdzone ponownie.

## Przegląd przed PR-em (TypeScript) — trzy błędy, każdy z testem, który padał

- „Polecenie dla całego CV” z „Więcej”: menu oddawało fokus kartce, więc tekst
  polecenia wpisywał się w CV. Pozycje okna z „Więcej” ruszają po zamknięciu
  menu i nie oddają fokusu kartce (test w harnessie edytora).
- „Historia wersji” z karty nie otwierała historii, gdy karta miała CV
  w pamięci (CV od pierwszego renderu, edytor dopiero po nim). Efekt czeka na
  gotową historię (`history.enabled`), nie na samo CV.
- Miniatura zamawiała nową zamianę PDF przy każdym autozapisie edytora (ten
  sam klucz zapytania, rewizja = licznik autozapisów; limit 20/min). Gdy
  edytor jest otwarty, klucz stron stoi; miniatura odświeża się raz, po
  zamknięciu (test: 4 zamiany → 1).

## Świadomie poza zakresem

- Papier firmowy na kartce edytora — szablon bywa różny; prawdziwy papier
  jest w „Jak u klienta”.
- Nazwa panelu „Do poprawy” zostaje (makieta: „Do sprawdzenia”) — ta sama
  nazwa jest na karcie, w oknie QC i w formularzu screeningu.
- Kolumna asystenta zamiast polecenia, menu AI i dymka — PR 4.
- „Napisz od nowa” w karcie — PR 5.
- Miniatura to jedna zamiana PDF na otwarcie osoby z gotowym CV (karta jest
  w panelu jednej osoby naraz; wynik pamiętany po treści). Przy pełnej kolejce
  zamian miniatura pokazuje ikonę pliku.
