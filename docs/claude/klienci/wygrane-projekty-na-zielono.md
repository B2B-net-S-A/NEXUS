# Wygrane projekty klienta na zielono — wynik jak w hit ratio (26.11.2026)

<!-- indeks: Klient → Rekrutacje → Projekty, pole outcome i outcome_counts w /api/jobs, services/job_outcome.py, chipy Wygrane / Bez wyniku / Nie liczy się / Przegrane, „Uzupełnij wynik”, wyjątek od „bez tła w wierszach” -->

Prośba Delivery Leada z 26.11.2026: w „Zamkniętych projektach” klienta od razu
widać, które projekty wygraliśmy. Decyzja Artura z 26.11.2026 po makietach
na stagingu: wariant „B + chipy”, a wygrana liczona tak samo jak w hit ratio.

- **Definicja jest jedna:** `services/job_outcome.py` (`job_outcome_expr`)
  powtarza `hit_ratio_closures.closure_group`: powód z grupy „nie liczy się”
  → `neutral`; ktoś z nas na „Zatrudniony” w bieżącym otwarciu, bez
  wykluczonego placementu → `won`; brak powodu albo „Inny” → `unreviewed`;
  reszta → `lost` (także „Obsadzone przez nas” bez osoby na „Zatrudniony”).
  Bo zielony wiersz, który nie zgadza się z Ligą DL, rodzi pytanie, który
  ekran kłamie. Samego powodu zamknięcia nie używaj: 26.11.2026 na kopii
  produkcji 4198 z 4410 zamkniętych rekrutacji nie miało powodu, a 663 miały
  zatrudnienie bez „Obsadzone przez nas”.
- **API:** `/api/jobs` oddaje przy każdej zamkniętej `outcome` i
  `hired_names` (tylko przy wygranej; pusta lista w wierszu, którego osoba
  nie otworzy). Filtr `outcome=` (powtarzalny, LUB) i `outcome_counts=true`
  — liczniki po tych samych filtrach, bez filtra `outcome`.
- **Ekran:** wygrana = cały wiersz `bg-success-muted` z paskiem po lewej,
  plakietka „Wygrana” i „Zatrudniony: …”. To świadomy wyjątek od „bez tła
  w wierszach” ze spokojnych tabel (`ui/klienci-kontrakty-finanse-spokojne-tabele.md`)
  — tylko dla wygranej. Inne zamknięte mają szarą kropkę „Zamknięta” (już
  nie czerwoną: czerwień przy każdym zamkniętym czytała się jak „wszystko
  przegraliśmy”) i drugą linię z powodem.
- **Chipy** nad tabelą zamkniętych: Wszystkie · Wygrane · Bez wyniku ·
  Nie liczy się · Przegrane, liczby z serwera. Licznik zakładki „Zamknięte
  projekty” to suma chipów, nie wynik wybranego chipa.
- **„Uzupełnij wynik”** przy projekcie bez wyniku otwiera
  `JobCloseWithReasonDialog` w trybie zmiany (`PATCH /close-reason`), tylko
  dla osób z `canCloseJobAsLost`; reszta widzi „Bez powodu zamknięcia”.
