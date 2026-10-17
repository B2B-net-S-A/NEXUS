# Prepy: elastyczność i powiadomienia — raport (17.10.2026)

Zgłoszenie Delivery Leada przekazane przez Artura: w oknie „Zaplanuj prep”
nie da się dodać nikogo spoza listy zespołu rekrutacji. Do tego: rekruter
planuje prep za DL-a i musi móc go potem zmienić (kandydat pisze „nie mogę
w czwartek”), DL ma mieć kontrolę, a DL-e nie dostawali informacji, że
kandydat przyjął prep. Makiety i audyt:
https://claude.ai/artifact/BBh9XhdZDDTqArUNv5oUjR. Artur przyjął D1–D8
w całości („Tak na D1–D8 jak proponujesz. Zrób oba PR-y po kolei.”).

## Audyt (stan przed zmianą, main 330f0d129)

| Co | Gdzie w kodzie | Skutek |
|---|---|---|
| Lista zaproszonych = zespół rekrutacji z adminami | `api/prep_meetings.py` `create_prep`: `wanted <= allowed` | Nikogo spoza nie da się dodać (422) |
| Prep należy do prowadzącego | `services/prep_meetings.create_prep`: `created_by = operational_owner_id = organizator` | Rekruter, który założył Prep 1 za DL-a: „Szczegóły” 404, zmiana i odwołanie 403 |
| Zaplanowany prep bez akcji w doku | `DockInterviewCycle.tsx` | „Przełóż” tylko dla prepu po rozmowie |
| Odpowiedź kandydata | brak odczytu `attendees.status` w backendzie | NEXUS nie wie, czy kandydat przyjął; mail z Outlooka dostaje tylko organizator |
| Zmiana w Outlooku | `prep_transcripts._refresh_event` dopiero przy pobieraniu transkryptu | NEXUS widzi przełożenie po starej godzinie prepu |
| Powiadomienia | tylko `prep_attention` (organizator + HoR) | DL nie dostaje nic o Prepie 2 |

Niepotwierdzone: ile prepów rekruterzy planują za DL-ów — odczyt bazy
produkcyjnej był w sesji zablokowany.

## PR 1 — ludzie pary zmieniają prep, zaprosić można każdego (D1–D4)

- `PATCH /api/interview-cycle/preps/{event_id}` (termin, zaproszeni,
  prowadzący) i `POST …/cancel`; bramka `prep_meetings.user_can_edit_prep`:
  prowadzący, planujący, DL rekrutacji, rekruter kandydata, zastępcy, HoR,
  admin. Zmiana najpierw w Outlooku prowadzącego (app-only), potem w bazie.
- Inny prowadzący: nowe spotkanie, potem odwołanie starego; porażka
  odwołania = odwołanie nowego + rollback (nigdy dwa aktywne prepy).
- Zaproszeni: każdy aktywny z NEXUSA (`options.people`) i do 10 adresów
  spoza (`attendee_emails`). Planujący za kogoś jest od razu na liście.
- Front: pole „Zaproś” z wyszukiwaniem (`PrepPeoplePicker`, `lib/prep-people.ts`),
  okno „Przełóż / Zmień / Odwołaj prep” (`ReschedulePrepDialog` z `mode`),
  wiersze zaplanowanych prepów z „Zmień”/„Odwołaj” w doku osoby i w panelu
  kalendarza (tylko przy `can_edit`). Kroki odznaki Tablicy niosą `event_id`.
- Testy: `backend/tests/test_prep_editing.py` (10 z bazą w CI + 7 czystych,
  lokalnie zielone), `ReschedulePrepDialog.test.tsx`, `prep-people.test.ts`,
  `DockInterviewCycle.test.tsx`; wzorzec `authz_golden/prep_meetings.json`
  (dwie nowe trasy, ta sama bramka co zakładanie prepu).
- Reguła: `docs/claude/integracje/prepy-w-teams-transkrypt-notatka-i-ocena-prepu.md`;
  przewodnik Jarvisa `calendar` przestemplowany.

Poza zakresem PR 1: zmiana dopisku w zaproszeniu (dopisek nie jest zapisany
osobno), powiadomienia i odpowiedź kandydata (PR 2).
