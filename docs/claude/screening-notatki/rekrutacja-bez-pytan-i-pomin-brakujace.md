# Rekrutacja bez pytań screeningowych i „Pomiń brakujące” poza przepięciem (12.10.2026)
<!-- indeks: „Zweryfikowany” bez Profilu Championa, kto pomija pytania -->

Zgłoszenie z 12.10.2026 (kilka osób): po przepięciu kandydata do innej rekrutacji ruch na
„Zweryfikowany” kończył się komunikatem „uzupełnij: arkusz screeningu”, którego nie dało się
spełnić. Pomiar na produkcji (tylko odczyt): 33 z 206 otwartych rekrutacji nie miały ani jednego
pytania screeningowego — wszystkie przeniesione z Traffita, żadna z założonych w NEXUSIE
(przekazanie wymaga dwóch pytań); stało w nich 311 osób przed „Zweryfikowany”. Od wyłączenia
importu nikt w takiej rekrutacji nie przeszedł dalej.

Decyzje Artura 12.10.2026:

- **Rekrutacja bez pytań: zamiast arkusza wystarcza „Dlaczego ten kandydat”** (plus stawka, jak
  zawsze). Regułę liczy `move_requirements.screening_requirement` — czytają ją bramka ruchu
  (`pipeline_move_rules.assert_verified_requirements`, brak = `why_candidate`) i okno „Przesuń
  dalej”. „Rekrutacja ma pytania” znaczy to samo co w zapisie formularza: pytanie z identyfikatorem
  i treścią (`screening_sheets.question_texts`). Pole liczy się z bieżącej próby procesu, wpisane
  ręcznie albo z notatki, i tylko wtedy, gdy liczyłby się arkusz tej próby (`screening_window`):
  ocena z próby zamkniętej ponad 30 dni temu nie przepuszcza osoby wracającej prosto
  z „Zamkniętych”. Arkusz zapisany, zanim pytania zniknęły z profilu, dalej wystarcza.
  Rekrutacja z pytaniami nie zmienia się: ocena nie zastępuje odpowiedzi.
- **Komunikat mówi, co da się wpisać.** Odmowa w rekrutacji bez pytań nazywa „Dlaczego ten
  kandydat” i powód („ta rekrutacja nie ma pytań screeningowych”); pusty stan sekcji pytań
  w formularzu mówi, co wystarcza do ruchu dalej. Formularz zatrzymuje „Zapisz i przekaż dalej”
  sam tylko wtedy, gdy jest pewny (`assessmentMissingForForward`) — w pozostałych przypadkach
  rozstrzyga serwer.
- **„Pomiń brakujące” nie tylko po przepięciu z panelu.** Zespół przepina też ręcznie, a panel
  „Podobne rekrutacje” nie pozwala wybrać osoby zatrudnionej w rekrutacji źródłowej (od 05.10:
  152 ręczne dodania, 56 osób z arkuszem w innej rekrutacji, 9 zatrudnionych gdzie indziej).
  `GET …/screening/reassign-context` oddaje `skip_reason`
  (`screening_reassign.skip_missing_reason`): `reassign` — przepięcie, `earlier_screening` —
  wypełniony arkusz w innej rekrutacji w zakresie odczytu patrzącego, `employed` — etap
  „Zatrudniony” w innej rekrutacji albo trwający kontrakt (`current_employment`). Osoba
  zatrudniona bez wcześniejszych rozmów dostaje samo pole wyboru; Luna nie jest wtedy wołana.
  Limitu czasu nie ma — pominięcie jest jawną decyzją rekrutera z notatką wewnętrzną, którą
  widzi Delivery Lead. Notatka domyślna i znacznik przy pytaniu mówią prawdziwy powód
  (`SKIP_NOTE_BY_REASON`; formularz niesie `skip_reason` w wartościach, ustawia go zaznaczenie
  pola) — „przepięcie” zostaje tylko przy przepięciu. Pominięte odpowiedzi i notatka dalej nie
  idą do klienta.

- **Karta Tablicy i „Czeka na Ciebie” mówią to samo co bramka (13.10.2026).** W rekrutacji bez
  pytań karta niesie `screening_requirement: "why_candidate"`, a `screening_done` znaczy „ocena
  wpisana” (`move_requirements.card_screening_state` z podsumowań kart, które Tablica i tak
  wczytuje — bez dodatkowego zapytania). Krok w „Screeningu” to „Wpisz „Dlaczego ten kandydat””
  (na karcie skrót „Wpisz ocenę”, bo pełna nazwa pola nie mieści się w kolumnie przy 1280 px),
  podpowiedź strzałki „Brak „Dlaczego ten kandydat””. Etykieta kroku żyje w dwóch językach
  (`pipeline_next_action.py`, `pipeline-next-action.ts`) na wspólnych przypadkach
  `next-action-cases.json`. Kolejka oddaje brak `why_candidate` zamiast `sheet`
  (`board_flow._screening`, `missing_screening_requirement`). Klucze braków czytają trzy miejsca:
  schemat odpowiedzi (`api/board_tasks.py`), plakietki na pulpicie (`BoardFlowSections`)
  i poranny skrót mailem (`daily_digest._MISSING`) — nowy klucz dopisuje się we wszystkich,
  inaczej mail wypisze go surowego. Rekrutacja z pytaniami nie zmienia się w żadnym z tych
  miejsc: karta dalej liczy sam arkusz.

- **Bramka liczy odpowiedzi, a „Pomiń brakujące” pilnuje serwer (14.10.2026).** Audyt z 13.10
  pokazał, że oba warunki trzymał tylko ekran. Formularz wysyła każde pytanie, także puste, a
  bramka liczyła pozycje listy (`sheet_filled`). Dlatego arkusz z samym sprawdzeniem
  doświadczenia albo z samymi `skipped` wysłanymi z pominięciem ekranu przepuszczał na
  „Zweryfikowany”. Teraz bramka, karta Tablicy (`screening_done`) i okno „Przesuń dalej” czytają
  `move_requirements.sheet_answered`: co najmniej jedna odpowiedź z treścią, pominięciem albo
  trafieniem deal-breakera (ta sama `answer_has_content` co zapis formularza). Kompletu odpowiedzi
  reguła nie wymaga i dalej go nie wymagamy. `sheet_filled` zostaje dla pytania „czy arkusz jest
  zapisany”. Zapis `skipped` bez `skip_missing_reason` kończy się 422 `SCREENING_FORM_INVALID`
  (`screening_form.assert_skip_allowed`), zarówno w `PUT /screening-form`, jak i w starej
  `POST /pipeline/stages/{id}/screening`. Arkusz pary, który ma już pominięte pytania, zapisuje
  się dalej bez sprawdzania powodu: formularz przywraca zaznaczenie, a przepięcie mogło od tamtej
  pory zniknąć. Lustro na froncie: `assessmentMissingForForward` liczy arkusz tą samą regułą.

Świadomie poza zakresem: opis kolumny „Screening” na Tablicy („Arkusz pytań z…”) jest stały dla
każdej rekrutacji. Arkusz z samymi sprawdzeniami doświadczenia zapisuje się, ale bramki nie
spełnia. Odpowiedzi z notatki (`card_answers`) nie mają okna próby zamkniętej dawno temu — stan
sprzed tej zmiany.
