# Mail odrzucenia: treść domyślna i podgląd w oknie odrzucenia (13.10.2026)

<!-- indeks: treść domyślna w kodzie bez „Pozdrawiam”, podgląd adresata/tematu/treści przed potwierdzeniem, poprawka przy jednej osobie, kilka osób tylko do odczytu, powód braku wysyłki od razu, szablony odrzucenia z Ustawień nieużywane -->

Decyzje Artura D1–D6 z 13.10.2026 (makiety:
https://claude.ai/artifact/2YZDg3zkKYxayvWayRiZxs). Pierwszy mail odrzucenia
z produkcji poszedł z treścią z kodu („zaangażowanie w proces… zakończenie
współpracy”) i z dwoma pożegnaniami: własnym „Pozdrawiam, imię z konta NEXUSA”
i podpisem Outlooka, który `m365/sender.py` dokleja po „--” do każdego maila.

## Treść domyślna

- Żyje w kodzie: `_DEFAULT_SUBJECT` / `_DEFAULT_BODY` w
  `services/rejection_email_scheduler.py`. Zwykły tekst, pusta linia = akapit.
  Temat bez zmian: „Informacja zwrotna — {{job_title}}”.
- Treść (D2: „Życzymy”): „Cześć {{candidate_name}}, dziękujemy za udział
  w rekrutacji na stanowisko {{job_title}}. Niestety został wybrany inny
  kandydat. Życzymy powodzenia i zachęcamy do udziału w przyszłych procesach
  rekrutacyjnych!”
- Bez „Pozdrawiam” i imienia rekrutera — pożegnanie daje podpis Outlooka.
  Nie dopisuj go z powrotem.
- Bez bloku „Nadal rozważamy Cię w N innych procesach” (D4). Renderer nadal
  obsługuje `{{#if other_processes}}` w szablonie wskazanym jawnie.
- D6: wysyłka NIE sięga po szablony odrzucenia z Ustawień → Szablony
  (nazwany „Auto-odrzucenie…”, domyślny, dowolny). `_resolve_template` bierze
  tylko jawny `rejection_email_template_id` kategorii rejection, inaczej
  treść z kodu. Do 13.10 na produkcji żaden szablon nie był używany, a poprawka
  jednego z nich podmieniłaby po cichu treść, którą widzi rekruter. Wpis
  „Auto-odrzucenie…” zniknął z `DEFAULT_TEMPLATES`.
- Zmiana treści domyślnej = PR (D6), razem z testami
  `test_rejection_email_scheduler.py::test_default_text_is_the_approved_text`.

## Podgląd w oknie odrzucenia

- `RejectionV2` → `RejectionEmailField`: przy otwarciu okna (gdy mail jest
  możliwy) `POST /api/rejection-emails/preview` z `{job_id, candidate_ids}`.
  Dostęp jak `POST /api/pipeline/move` (`RecruiterPlus` + członkostwo
  w rekrutacji, sekcja Pipeline z zapisem — POST nie jest na liście
  read-only). Nic nie zapisuje.
- Odpowiedź: dla każdej osoby `to_email` i `skip_reason` (ten sam słownik co
  `rejection_email_status` z ruchu, ta sama kolejność: `not_client_visible`
  → `no_candidate_email` → `no_permission` → `no_mailbox`) oraz `subject`/`body`
  zwykłym tekstem dla pierwszej osoby, do której mail wyjdzie. Przy podglądzie
  liczy się BIEŻĄCY wiersz pary (osoba jeszcze nie jest odrzucona), przy ruchu
  — wiersz przed odrzuceniem.
- Gdy mail nie wyjdzie do nikogo: checkbox wyłączony, baner z powodem
  (`rejectionEmailBlockedMessage`). Odrzucenie przechodzi bez maila.
- Jedna osoba: „Do” (tylko odczyt), Temat i Treść do poprawy,
  „Zmieniona ręcznie” i „Przywróć treść domyślną”, dopisek o podpisie
  z Outlooka. Pusty temat albo treść blokują „Potwierdź”.
- Kilka osób (D5): podgląd dla pierwszej osoby z mailem tylko do odczytu
  i lista „Mail wyjdzie do N z M osób” z krótkim powodem przy pominiętych.
  Treść poprawia się, odrzucając osoby pojedynczo.
- Awaria podglądu nie blokuje odrzucenia: komunikat „…Mail wyjdzie z treścią
  domyślną.”, bez ponawiania w tle.

## Wysyłka poprawionej treści

- `onConfirm` okna dostaje 8. argument `emailText` (`{subject, body}` tylko
  przy jednej osobie i tylko po zmianie, inaczej `null`). Wołający:
  `usePipelineMove`, `ScreeningFullForm`, `JobInterviewsTab`.
- `StageMove.rejection_email_subject` (≤ 200, jedna linia, pusty = 422)
  i `rejection_email_body` (≤ 5000, pusty = 422). `maybe_schedule` robi
  z treści HTML przez `plain_text_to_html` — zawsze escape. Nigdy przez
  `body_to_html`: ten przepuszcza tekst ze znacznikami HTML bez zmian.
- Wpis historii `rejection_email_scheduled` ma `details.edited`; oś czasu
  kandydata dopisuje „· treść zmieniona ręcznie”. Wysłany temat i treść stoją
  w `scheduled_rejection_emails` jak dotąd.

## Harness

`/preview/rejection-email?state=one|blocked|bulk` — prawdziwy `RejectionV2`,
podgląd zasiany w cache ze znacznikiem czasu w przyszłości, dane fikcyjne.
