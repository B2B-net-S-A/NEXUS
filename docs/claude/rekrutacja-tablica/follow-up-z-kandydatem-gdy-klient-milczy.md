# Follow-up z kandydatem, gdy klient milczy (0372, 24.09.2026)

Decyzje Artura 24.09.2026, makiety https://claude.ai/artifact/E3rjEeFPRqp2RFTo3cQunj.
Kod: `services/candidate_followups.py` (reguła), `api/candidate_followups.py`,
lista w „Czeka na Ciebie” (`followups` w `GET /api/board-tasks`), pole
`followup` na karcie Tablicy, blok „Kontakt z kandydatem” w doku, fakt
„Kontakt” w profilu. Harness `/preview/candidate-followup`.

- **Zadanie należy do OSOBY, nie procesu.** Kandydat w pięciu procesach
  u pięciu rekruterów dostaje JEDEN telefon. Dzwoni rekruter procesu, który
  zaszedł najdalej (`client_interview` przed `cv_sent`). Przy remisie ten, kto
  ostatnio rozmawiał z kandydatem, a potem proces wysłany najwcześniej.
  Właściciel procesu = pierwszy weryfikator pary, a zapasowo osoba, która
  wysłała CV, i prowadzący rekrutację. Zastępstwo COMPASS przejmuje
  (`effective_owner_id`), nieaktywne konto oddaje zadanie kolejnemu procesowi,
  „Zrobię to ja” (`claim`) wygrywa bieżącą rundę.
- **Duplikaty usuwa kontakt KOGOKOLWIEK, nie przydział.** Termin to
  max(najstarsza cisza klienta, ostatni kontakt) + 14 dni kalendarzowych.
  Kontakt to notatka-ROZMOWA (typ telefon/spotkanie/mail, także
  „Rozmowa telefoniczna”/„Email” z Traffita), telefon, wysłany mail, minione
  wydarzenie kalendarza albo wynik `connected`/`changed`. Zwykła notatka
  (np. komentarz przy dodaniu do innej rekrutacji) NIE jest kontaktem —
  inaczej ukrywałaby przypomnienie na 14 dni (przegląd kodu 24.09.2026).
  „Nie odebrał” NIE jest kontaktem: przesuwa termin o 2 dni robocze, bez
  limitu prób i bez maila (decyzja Artura).
- **Wchodzą tylko CV wysłane od `CANDIDATE_FOLLOWUP_SINCE` (24.09.2026).**
  Liczy się pierwsze `cv_sent` pary. Stare procesy (318 „CV wysłane” starszych
  niż 90 dni na 24.09) świadomie nie dają telefonów. Nie przesuwaj tej daty
  wstecz bez decyzji — pierwszego dnia wyszłoby ~200 telefonów naraz.
- **Kolumnę liczy się po NAZWIE etapu, jak na Tablicy** (`board_column_for`
  + `_Catalog.effective_def_id`). „Przepuszczony przez DZ” ma kod
  `interview`, a jest QC, więc nie jest czekaniem na klienta. „Po Interview”
  z Traffita jest. Zaplanowana rozmowa u klienta i otwarty wniosek o terminy
  wstrzymują proces (klient odpowiedział).
- **Wynik telefonu to JEDNA notatka** (`note_type=call`, `job_id=NULL`,
  `source_ref=followup:<id>`). Nie powielamy jej per proces — profil
  pokazywałby wtedy N kopii. Właściciele procesów widzą wynik w bloku doku
  (historia z `candidate_followups`). `changed` wysyła dzwonek
  `candidate_followup_signal` do właścicieli procesów oznaczonych jako
  „rezygnuje” (albo do wszystkich), z pominięciem dzwoniącego. Etapu nie
  zmienia.
- Request „Zakończony” (`jobs.work_state = 'finished'`) nie daje follow-upów.
  Dzwonek `candidate_followup_signal` to jeden wpis na właściciela ze wszystkimi
  jego procesami; drugi sygnał tego samego dnia dopisuje się do dzisiejszego
  wpisu i oznacza go jako nieprzeczytany (dobowy dedup go nie połyka).
- Awaria liczenia NIE kładzie pulpitu ani Tablicy (`load_followups_safely`:
  savepoint, log, pusta lista). „Moje następne kroki” (do 25 tablic) liczy
  tablice bez follow-upów (`with_followups=False`).
- Lista liczy się przy odczycie. Tabela `candidate_followups` trzyma tylko
  wyniki (kandydat CASCADE, RODO). Poranny skrót (`board_tasks_digest`)
  liczy follow-upy każdej roli. Wyłącznik `CANDIDATE_FOLLOWUP_ENABLED`.
