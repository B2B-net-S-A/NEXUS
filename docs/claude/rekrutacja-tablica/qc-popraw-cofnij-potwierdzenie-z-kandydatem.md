# „Popraw” i „Cofnij” przy „Potwierdzone z kandydatem” w QC CV (27.11.2026)
<!-- indeks: PATCH/DELETE `/qc/confirm/{note_id}`, autor albo admin, ta rekrutacja, do „CV wysłane”, QC od razu, etykieta z nazwą blokady, `confirmation_parts` -->

Decyzja Artura z 27.11.2026 (wariant A + etykieta z C, makiety:
https://claude.ai/artifact/H1B39bUScYRsUJMmxLcqhw). Zgłoszenie rekrutera:
przy dwóch blokadach „spoza oryginału” kliknął „Kandydat to ma” przy jednej
i wpisał słowa kandydata, które dotyczyły drugiej. Wpis to zwykła notatka pary
(`external_source = qc_confirmation`), więc dało się ją usunąć tylko w profilu
kandydata → Notatki, a lista w oknie QC i w edytorze była tylko do odczytu.
Na kopii z 27.11: 654 takie wpisy od 25 osób, edytowany później jeden.

Notatka nie zmienia bieżącego CV, ale jest źródłem dla QC, generatora CV
(następne generowanie i propozycje AI), tabeli wymagań w przeglądzie DL
i bramki must / krytycznych. Liczba „Dopasowanie AI” bierze z notatek tylko
stawkę, tryb, formę umowy, dostępność i miasta.

## Reguły

- **Gdzie:** sekcja „Potwierdzone z kandydatem” w oknie QC (`CvQcDialog`)
  i w panelu edytora CV (`CvEditorIssues`) — ten sam komponent `Confirmations`
  z `ctx.confirmationFix`. Bez `confirmationFix` (podgląd jako inny
  użytkownik, harness bez zapisu) przycisków nie ma.
- **Kto i kiedy:** autor wpisu albo admin, wpis z tej rekrutacji (lista
  pokazuje potwierdzenia kandydata ze wszystkich rekrutacji), karta przed
  „CV wysłane” (`integration_cv.locked_after_send` na bieżącym wierszu pary).
  Po wysyłce wpis jest śladem tego, na czym oparto wysyłkę. Serwer liczy
  `can_edit` dla oglądającego w `_response`; odmowa: 403 cudzy wpis, 422
  po wysyłce, notatka spoza pary, blokada, której QC nie zgłasza, zdanie
  krótsze niż `CONFIRM_TEXT_MIN`.
- **„Popraw”** (`PATCH /api/pipeline/stages/{id}/qc/confirm/{note_id}`, to samo
  ciało co `POST /qc/confirm`): blokada ta sama co dotąd albo jedna z tych, które
  QC teraz zgłasza; zdanie i rola jak przy zapisie. Ta sama notatka (autor
  i data zostają), `Activity` `cv_qc_confirmation_edited` ze starą i nową
  blokadą, znacznik zmiany notatek dla nocnej ekstrakcji. Wpis pokazuje
  „poprawione <data>” (`edited_at`, gdy `updated_at` odbiega od `created_at`
  o ponad 5 s).
- **„Cofnij”** (`DELETE` tej samej trasy) pyta przez `useConfirmV2`, usuwa
  notatkę, zapisuje `cv_qc_confirmation_retracted` i czyści fakty z notatek tą
  samą drogą co usunięcie w profilu (`_forget_note_facts`).
- **QC liczy się od razu** z zapisem przebiegu (`run_qc(persist=True)`), więc
  Tablica i kolejka DL nie czekają na ponowne otwarcie okna.
- **Treść notatki** buduje jedna funkcja `confirmation_content`
  („Potwierdzone z kandydatem: X (Firma) — słowa”), a czyta
  `confirmation_parts`. Nawias na końcu to rola tylko wtedy, gdy to firma
  z historii kandydata (`confirm_roles`); „CI/CD (Jenkins)” zostaje nazwą.
- **QC czyta treść notatki jako źródło.** Słowa kandydata, które zawierają
  nazwę innej blokady, zamykają też ją. Dlatego formularz pyta „Co kandydat
  powiedział o „X”?” — z nazwą blokady w etykiecie (część C makiety), w oknie
  QC, w edytorze i w „Popraw”.

Testy: `test_confirmation_saved_under_the_wrong_blocker_can_be_moved_and_retracted`,
`test_confirmation_parts_read_back_what_the_note_saved`,
`test_only_the_author_or_an_admin_edits_a_confirmation_before_sending`
(`backend/tests/test_cv_qc.py`); „„Popraw” i „Cofnij”” w `CvQcDialog.test.tsx`;
„„Popraw” w panelu edytora…” w `CvEditorIssues.test.tsx`.
