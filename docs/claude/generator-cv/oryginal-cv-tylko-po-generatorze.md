# Oryginał CV tylko po próbie z generatorem — sama rola rekrutera, powody, „Jakość generatora CV”
<!-- indeks: bramka `services/cv_download_policy.py`, trasa `…/cv/original/download-after-generator`, tabela `cv_generator_feedback` (0636), ekran `/settings/jakosc-generatora` -->

Decyzje Artura z 02.11.2026 (makiety: https://claude.ai/artifact/9tug3jyTM3kZmjaXo8VcQ6).
Rekruterzy pobierali CV hurtem do prywatnych baz i czatów. Od 23.10 do 02.11
dni z 10 lub więcej osobami to 260 z co najmniej 381 zapisów, a tylko 1 z nich
wrócił do karty jako wgrane CV.

- **Kogo dotyczy:** rekruter bez żadnej innej roli (`is_recruiter_only`). Każda
  rola dodatkowa (admin, HoR, DL, TCM, Finanse, Automatyzacje) zdejmuje zasady.
  Osoba wrzucająca do Cpro też jest zwolniona, bo kolejka Cpro pobiera plik:
  firmowa, zapasowa i zastępca z urlopu, a `jobs.cpro_sender_id` i
  `task_assignee_id` tylko wtedy, gdy nikogo nie ustawiono na firmę (jak `board_tasks`).
- **Bez limitu dziennego** (decyzja Artura). Limit był w pierwszej makiecie i wypadł.
- **Podgląd bez zmian.** Blokowany jest tylko zapis (`disposition=attachment`).
  Bramka musi patrzeć na żądanie, a nie na wynik `safe_document_disposition`,
  bo ta zmienia `inline` pliku Word na `attachment` i rekruter straciłby podgląd.
  Z tego samego powodu dziennik zapisuje żądanie: do 02.11 podgląd Worda
  liczył się jako zapis na dysk, także w alarmie masowego przeglądania.
- **Blokada obejmuje każdy plik z podglądem, nie tylko rodzaj „CV”.** Rodzaj da się
  zmienić w profilu, a CV dla klientów z Traffita mają rodzaj „Inny”. Plik bez
  podglądu (`.doc`, `.odt`, Excel) zostaje do pobrania, bo inaczej nikt nie zobaczy
  jego treści. Lista w `has_inline_preview` jest lustrem `previewKind` we froncie.
- **ZIP:** `CandidateBulkCvAccess`, rola w zależności trasy (wzorzec uprawnień).
  Pozostałe trasy pytają w handlerze, bo liczy się format pliku; to pilnuje
  `tests/test_cv_download_policy.py`.
- **Jedyna furtka:** `POST …/cv/original/download-after-generator`. Wymaga generacji
  w tej parze ze stanem `ready` albo `failed` (inaczej 409 `generator_attempt_required`)
  i co najmniej jednego powodu. Błąd techniczny to za mało na furtkę: 3 z 866
  generacji w 30 dniach, dlatego liczy się też ocena rekrutera przy gotowym CV.
  Po wysyłce do klienta link się nie pokazuje (`canReplace`).
- **CV firmowe (Word i PDF) bez zmian** (decyzja Artura). Powstaje przez generację
  na osobę, więc nie nadaje się do hurtu.
- **Powody:** lista w `FEEDBACK_REASONS` i lustro w `lib/cv-download-access.ts`.
  `cv_generator_feedback` trzyma odnośniki do pary, generacji i klienta, kody
  i opcjonalny opis, bez kopii treści CV. „Inny powód” wymaga opisu.
- **Ekran:** Ustawienia → „Jakość generatora CV” (`/settings/jakosc-generatora`,
  `GET /api/cv-generator/feedback/summary`), admin i HoR.
- **Załączniki z własnej skrzynki** (`/emails/…/attachments/…/download`) zostają:
  to poczta tej osoby, nie baza kandydatów.
- **Czego to nie zatrzyma:** podgląd wysyła plik do przeglądarki, więc da się go
  wyciągnąć narzędziami deweloperskimi albo sfotografować. Alarm masowego
  przeglądania zostaje i liczy podglądy (`candidate_data_access_alerts`).
