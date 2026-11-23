# Dzwonienie: duplikaty — instrukcja w ekranie, Tabela bez powtórek, „To duplikat” (decyzje Artura 23.11.2026)
<!-- indeks: Jak działają duplikaty, DuplicatesHelp, Powtórki w Tabeli, not_a_repeat, repeats=true, repeat w QueueItem, To duplikat, POST records/{id}/duplicate, call_duplicate, report_duplicate, calling_repeats_report Zgłoszone, 542 powtórki sprzed 17.11 -->

Zgłoszenie osób dzwoniących (23.11.2026): „sprawdzić, czy system weryfikuje duplikaty;
jeśli tak, niech przedstawi instrukcję, jak to działa. Duplikaty nadal występują”.
Na kopii produkcji z 23.11 bramka z 17.11 działała (88 rekordów dodanych od 17.11,
0 pod numerem, pod który już dzwoniono), ale Tabela pokazywała 542 „Nowe” powtórki
z list z 13.11 i 16.11 (kolejka ich nie podawała). Przykład z danych: ta sama osoba
i numer pod dwiema kartami firmy, u jednej osoby „Nowy”, u drugiej „Oddzwonić”.
Makiety: https://claude.ai/artifact/Gxjj6erDvtVBijP4S73g6p (punkt 2).

Artur wybrał: instrukcja w ekranie i „To duplikat” na karcie, a powtórki **ukryte po
stronie serwera** (nie kasowane): kasowanie wymagałoby nowego workflowu na produkcji,
a kolejka i tak ich nie podaje.

Kod: `calling_repeats.not_a_repeat` (ten sam warunek co kolejka), `calling.list_records`
(`repeats`, pole `repeat` pozycji, licznik `repeats`), `calling_repeats.report_duplicate`,
trasa `POST /api/sales/calling/records/{id}/duplicate` („Sprzedaż: edycja”), front
`DuplicatesHelp.tsx`, `CallTableView.tsx`, `CallCard.tsx` (`ReportDuplicateButton`).
Bez migracji.

## Zasady

- **Tabela pomija powtórki domyślnie**, także w licznikach statusów. Przełącznik
  „Powtórki N” (`?repeats=true`) pokazuje je z plakietką „Powtórka: już dzwoniono”.
  Powtórka to rekord „Nowy” pod numerem, adresem albo osobą, która ma wynik w innym
  rekordzie: dokładnie warunek kolejki. Firmy z szansą w CRM Tabela dalej pokazuje.
- **Instrukcja** („Jak działają duplikaty?” przy filtrach Tabeli) opisuje bramki
  importu, kolejki, Tabeli i karty oraz to, co przechodzi celowo (nowa osoba w firmie,
  dwie karty tej samej firmy z różnymi numerami). Zmiana bramek zmienia też ten tekst.
- **„To duplikat”** zapisuje notatkę „Zgłoszony duplikat na liście dzwonienia” na osi
  firmy (`external_source = call_duplicate`, jedna na osobę i rekord; drugi klik nie
  dubluje). Rekord zostaje na liście. Listę zgłoszeń daje
  `python -m scripts.calling_repeats_report --ids` („Zgłoszone „To duplikat””).
  To materiał do poprawy bramek, nie automat.

Testy: `backend/tests/test_sales_calling_duplicates.py`, w
`frontend/src/components/sales/__tests__/sales-calling.test.tsx` „powtórki” i „To duplikat”.
