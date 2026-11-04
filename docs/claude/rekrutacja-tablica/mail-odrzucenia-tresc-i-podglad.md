# Mail odrzucenia: treść domyślna i podgląd w oknie odrzucenia (13.10.2026)

<!-- indeks: treść domyślna w kodzie, podgląd przed potwierdzeniem -->

Decyzje Artura D1–D6 z 13.10.2026 (makiety:
https://claude.ai/artifact/2YZDg3zkKYxayvWayRiZxs). Pierwszy mail odrzucenia
z produkcji poszedł z treścią z kodu („zaangażowanie w proces… zakończenie
współpracy”) i z dwoma pożegnaniami: własnym „Pozdrawiam, imię z konta NEXUSA”
i podpisem Outlooka, który `m365/sender.py` dokleja pod treścią każdego maila.

## Treść domyślna

- Żyje w kodzie: od 17.10.2026 w `services/rejection_email_text.py`
  (wcześniej `_DEFAULT_SUBJECT` / `_DEFAULT_BODY` w
  `rejection_email_scheduler.py` — zostały jako zapas renderera). Zwykły
  tekst, pusta linia = akapit.
  Temat bez zmian: „Informacja zwrotna — {{job_title}}”.
- Treść (D2: „Życzymy”): „Cześć {{candidate_name}}, dziękujemy za udział
  w rekrutacji na stanowisko {{job_title}}. Niestety został wybrany inny
  kandydat. Życzymy powodzenia i zachęcamy do udziału w przyszłych procesach
  rekrutacyjnych!”
- Bez „Pozdrawiam” i imienia rekrutera — pożegnanie daje podpis Outlooka.
  Nie dopisuj go z powrotem.
- Bez bloku „Nadal rozważamy Cię w N innych procesach” (D4). Od 17.10.2026
  zastępuje go dopisek o pozostałych rekrutacjach (sekcja niżej). Renderer
  nadal obsługuje `{{#if other_processes}}` w szablonie wskazanym jawnie.
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
- `StageMove.rejection_email_subject` (≤ 998 jak kolumna — domyślny temat
  z tytułem rekrutacji do 255 znaków ma ~276; jedna linia, pusty = 422)
  i `rejection_email_body` (≤ 5000, pusty = 422). `maybe_schedule` robi
  z treści HTML przez `plain_text_to_html` — zawsze escape. Nigdy przez
  `body_to_html`: ten przepuszcza tekst ze znacznikami HTML bez zmian.
- Wpis historii `rejection_email_scheduled` ma `details.edited`; oś czasu
  kandydata dopisuje „· treść zmieniona ręcznie”. Wysłany temat i treść stoją
  w `scheduled_rejection_emails` jak dotąd.

## Mail od „Zweryfikowany” i dopisek o pozostałych rekrutacjach (17.10.2026)

Prośba rekrutera, decyzje Artura D1–D8 z 17.10.2026 (makiety i pomiar:
https://claude.ai/artifact/HvWWRjHpxovrQeNbLJudYL). Pomiar z produkcji:
w 30 dni 415 odrzuceń w NEXUSIE, 64 z możliwym mailem, wysłany 1; 35 z 80
osób odrzuconych od „Zweryfikowany” było dalej w innej otwartej rekrutacji.

- **Kiedy mail (D1):** poprzedni etap w kolumnie „Zweryfikowany”, „QC CV”
  (z kolejką Cpro), „CV wysłane”, „Rozmowa u klienta”, „Umowa”
  (`mail_text_kind`, lustro `lib/rejection-email.ts`). „Nowi” i „Screening”
  bez maila — kod powodu `not_client_visible` zostaje (zna go API
  integracyjne), zdanie mówi „od etapu Zweryfikowany”.
- **Dwie treści (D4):** „po kliencie” (od „CV wysłane”) = tekst z 13.10 bez
  zmian; „przed klientem” („Zweryfikowany”, „QC CV”) nie mówi, że „wybrano
  innego kandydata”. `previous_is_client_visible` rozdziela tylko treści.
- **Dopisek (D2):** osoba, która jest w innej OPUBLIKOWANEJ rekrutacji od
  „Zweryfikowany” do „Umowa”, dostaje zamiast zakończenia „To dotyczy tylko
  tej rekrutacji — nadal bierzesz udział w…”. Zapisana treść niesie znacznik
  `OTHER_PROCESSES_MARKER`, a `dispatch` wypełnia go listą Z CHWILI WYSYŁKI —
  osoba odrzucona w międzyczasie i tam nie przeczyta, że nadal bierze udział.
  Lista pusta przy wysyłce = zwykłe zakończenie. Pole edycji w oknie nie
  zawiera dopisku; checkbox „Dopisz pozostałe rekrutacje” (domyślnie
  zaznaczony) → `StageMove.rejection_email_other_processes=false` wyłącza go.
- **Nazwy dla kandydata (D5):** `mail_job_title` — zatwierdzony opis na
  stronę kariery wygrywa, inaczej `default_public_title` (bez prefiksu klienta
  i kodów). Nazwa, w której po czyszczeniu nadal widać 4 cyfry albo klienta
  (kontrola strony kariery + pierwsze słowo nazwy klienta), w dopisku idzie
  jako „inna rekrutacja”, a w temacie i treści zostaje z ostrzeżeniem
  `title_warning` w oknie. Pomiar 17.10: numer w 33 z 201 nazw (było 145),
  klient w 1 (było 47). Do 17.10 lista brała tylko rekrutacje z zatwierdzonym
  opisem publicznym (runda 9, R9-N10-2) — miało go 2 z 201.
  Od 18.10.2026 (decyzja Artura, wariant B z makiety
  https://claude.ai/artifact/XKwCRn3N3iFv6Uhdny3Ej8): gdy nazwa od klienta
  nie przechodzi kontroli, zapasowo tytuł dla rekrutera do pierwszego „ · ”
  (`rejection_email_text.pick_mail_title`), jeśli przechodzi tę samą kontrolę;
  dopiero gdy i on nie przechodzi — nazwa od klienta z `title_warning`. Pomiar
  18.10: 35 z 201 nazw niebezpiecznych, 21 ratuje tytuł rekrutera. Kontrola nie
  łapie nazwisk w tytule rekrutera ani literówek — rekruter widzi temat i treść
  w podglądzie przed potwierdzeniem.
- **Przegląd DL (D6):** `DlReviewPanel` ma to samo pole maila w „Odrzuć…”;
  mail wychodzi ze skrzynki DL (reguła „mail od osoby, która odrzuca”).
- **Brak skrzynki (D7):** okno daje „Podłącz skrzynkę” (Ustawienia →
  Integracje w nowej karcie), podgląd odświeża się po powrocie do karty.
  17.10 skrzynkę miało 8 osób; z 10 rekruterów, którzy odrzucali, 2.
- **Checkbox (D8):** dalej domyślnie odznaczony.
- **Jeden mail przy kilku odrzuceniach (D3):** gdy do osoby czeka już mail
  z innej rekrutacji (nie ruszył, bez szablonu, treść nie poprawiana ręcznie
  — `mergeable_pending_mail`), okno proponuje „Jeden wspólny mail o obu
  rekrutacjach” (domyślnie) albo osobny (`StageMove.rejection_email_merge`).
  Wspólny: nowy wiersz z treścią `merged_text` („W tych dwóch procesach nie
  przechodzisz dalej”, dopisek „tych rekrutacji”), stary dostaje `cancelled`
  i `last_error = "merged_into:<id>"` — bez nowej kolumny; `covered_job_ids`
  czyta, o których rekrutacjach mówi mail. `dispatch` sprawdza „nadal
  odrzucona” w KAŻDEJ z nich, a powrót osoby do którejkolwiek
  (`pending_rows_covering` w `/move`) anuluje wspólny mail. Nadawca
  anulowanego maila dostaje dzwonek; oś czasu ma wpis `rejection_email_merged`.
  Poprawiony ręcznie mail wychodzi osobno — i tak z dopiskiem z chwili wysyłki.
- Podgląd (`preview`) oddaje przy osobie `text_kind` i `other_processes`
  (nazwa w NEXUSIE, nazwa w mailu, kolumna), a `samples` — po jednej treści
  każdego rodzaju dla okna kilku osób (przełącznik „Przed klientem /
  Po kliencie”).

## Harness

`/preview/rejection-email?state=one|blocked|bulk|others|work_mode` — prawdziwy `RejectionV2`,
podgląd zasiany w cache ze znacznikiem czasu w przyszłości, dane fikcyjne.

## Powód „Nie akceptuje trybu pracy” zapisuje tryb pracy na profilu (14.10.2026)

Decyzje Artura D1–D6 z 14.10.2026 (propozycja rekrutera; makiety
i pomiar: https://claude.ai/artifact/SzBQiqjBZDSr8f8T2skSm5). Wcześniej
rekruter wybierał „Inne” i pisał „zdalnie” w notatce okna odrzucenia. Ta
notatka trafia tylko do `candidate_stages.notes` — nie widzi jej profil ani
nocny odczyt faktów (`notes_insights_extractor` czyta tabelę `notes`), więc
informacja ginęła dla wyszukiwania.

### Powód (D1)

- Klucz danych `work_mode_mismatch`, etykieta „Nie akceptuje trybu pracy
  (biuro / hybryda)” (`services/rejection_reason_labels.py`). Rozpoznajemy go
  PO KLUCZU (`WORK_MODE_MISMATCH`, front `WORK_MODE_MISMATCH_REASON`), jak
  `counter_offer` w ocenie ryzyka — nie zmieniaj nazwy wiersza w bazie.
- Jest w każdym szablonie procesu, w odrzuceniu i w rezygnacji kandydata,
  tuż przed „Inne” (migracja 0442 + lustro w `entrypoint.sh`, jednorazowe
  przez marker `work_mode_rejection_reason_seeded`, żeby start nie
  przywracał powodu skasowanego przez admina). Lista powodów sortuje się
  `order, id`.
- `disqualifies_person = false` — to sytuacja, nie werdykt o osobie; nie
  blokuje ponownego zgłoszenia do tego samego hiring managera.
- Nowy szablon z „Utwórz” nie dostaje powodów wcale (tak było zawsze);
  klon kopiuje wszystkie, także ten.

### Okno odrzucenia (D2–D3)

- Po wyborze powodu: „Ile dni w biurze kandydat akceptuje?” — domyślnie
  „Tylko zdalnie”, do wyboru tylko mniej dni, niż wymaga rekrutacja
  (`onsite_days_per_week`), a przy nieznanym wymogu 0–4
  (`lib/work-mode.ts` `officeDaysChoices`). „Nie chce 3 dni” to nie „tylko
  zdalnie” — zapis 0 dni u kogoś, kto akceptuje 1, chowałby go z hybryd.
- Ptaszek „Zapisz na profilu kandydata: Tryb pracy → …” domyślnie włączony.
  Przy jednej osobie „Teraz na profilu: …”; przy kilku zapis idzie do każdej
  osoby, bez podglądu.
- `RejectionWorkModeField` + `useRejectionWorkModeContext` (tryb pracy
  rekrutacji z `["job", id]`, profil z `candidateQueryKeys.detail`). Pytanie
  jest w czterech miejscach: Tablica (`usePipelineMove`), panel osoby
  (`ScreeningFullForm`), zakładka rozmów (`JobInterviewsTab`) i odrzucenie
  w przeglądzie Delivery Leada (`DlReviewPanel`, własna lista powodów, bez
  `RejectionV2`). Nowe miejsce, które wysyła `rejection_reason_id` do
  `/move`, musi je mieć — inaczej ten powód kończy się 422.

### Serwer

- `StageMove.work_mode_max_onsite_days` (0–4) i `work_mode_save_to_profile`.
  Powód bez dni → 422 „Podaj, ile dni w biurze kandydat akceptuje.”; dni przy
  innym powodzie → 422.
- Zapis: `candidate_notes_facts.set_work_mode_from_rejection` — tryby z dni
  (`modes_for_office_days`), nadpisuje profil (najświeższa deklaracja),
  kasuje zgodę „można dzwonić z większą liczbą dni” i zostawia źródło
  `preferences._work_mode_origin` (rekrutacja, etap, kto, kiedy). Audyt
  `candidate_work_mode_changed` z `source: rejection`, odświeżenie wyników
  dopasowań.
- Źródło znika przy każdej INNEJ zmianie trybu pracy (`set_profile_work_mode`,
  ogólny PATCH kandydata) — zapis tej samej wartości go zostawia. Profil
  pokazuje „z odrzucenia · data · rekrutacja” (`rejectionWorkModeOrigin`)
  przed linią z karty rekomendacji.

### Dopasowania (D4)

- `dealbreaker_filters.remote_only_refuses_office`: profil z 0 dni w biurze
  albo z samym trybem „zdalnie” = „tylko zdalnie”, tak samo jak
  `remote_only` z notatek. Profil, który akceptuje biuro (dni > 0, hybryda,
  zgoda na więcej dni), nadal wygrywa z notatką.
- Skutek: rekrutacja hybrydowa (też bez liczby dni) — plakietka; praca
  stacjonarna albo 4+ dni — osoba schowana z licznikiem „tylko zdalnie”.
  Pomiar 14.10.2026: 1 607 profili „tylko zdalnie”, 286 bez tego w notatkach;
  otwarte rekrutacje: 2 stacjonarne, 141 hybrydowych.
- Jedna plakietka „Tylko zdalnie” (`REMOTE_ONLY_BADGE_PL`): przy niej
  `office_fit_status` zwraca `remote_only` zamiast `days_exceeded`, więc
  „Mniej dni w biurze” nie dubluje informacji.

### Czego nie robimy (D5–D6)

- Wpis nie wygasa sam — rekruter zmienia go ołówkiem „Tryb pracy”.
- Stare odrzucenia „Inne” z notatką o pracy zdalnej (6 do 14.10.2026) nie są
  przepisywane: wolny tekst, a dopasowania wycinają tylko na pewnej wiedzy.
