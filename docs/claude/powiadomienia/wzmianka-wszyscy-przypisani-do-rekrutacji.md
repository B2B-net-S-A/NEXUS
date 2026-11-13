# `@wszyscy` — wzmianka dla osób przypisanych do rekrutacji

Decyzja Artura z 13.11.2026 po zgłoszeniu z czatu rekrutacji: wpisanie
„@Wszyscy” kończyło się komunikatem „Nie ma osoby pasującej”, więc
rekruterzy oznaczali cztery osoby po kolei. Wybrany wariant A (jeden znacznik,
który serwer rozwija przy zapisie). Odrzucony wariant B wstawiał adres każdej
osoby osobno, przez co pole i wiadomość zapełniały się adresami.

- **Gdzie działa:** czat rekrutacji i notatki z rekrutacją (`parse_mentions`
  z `job_id`, więc także screening i uwaga przy przesunięciu karty). W czacie
  kandydata i notatce bez rekrutacji `@wszyscy` zostaje zwykłym tekstem,
  bo nie ma tam zespołu.
- **Kogo oznacza:** `list_job_assigned_ids`, czyli rekrutera prowadzącego,
  Delivery Leada, osoby z aktywnym przypisaniem, ręcznie dodanych
  współpracowników, plan priorytetów i zastępcę za nieobecnego. Nie oznacza
  adminów spoza zespołu, uczestników kategorii (`auto_cc`), „Poprzednich
  rekruterów” ani autora. To nie jest „zespół: N” z nagłówka czatu: na kopii
  produkcji z 13.11 nagłówek pokazywał 15 osób, a przypisanych było 7. Nie
  zamieniaj tej listy na `list_job_members`, bo wzmiankę dostawali wtedy
  wszyscy admini.
- **Reguła wzmianek zostaje:** rozwinięta lista przechodzi przez
  `mentionable_users`, tak jak oznaczenie po nazwisku. Każda osoba dostaje
  zwykłą wzmiankę (`job_chat_mention` / `note_mention`, kategoria
  „Wzmianki”), zapisaną per osoba w `job_chat_mentions` / `note_mentions`.
- **Lista liczona w chwili zapisu.** Odznaka „@Wszyscy (n)” w czacie bierze
  liczbę i nazwiska z zapisanych wzmianek wiadomości (`mentions`), a nie
  z dzisiejszego składu zespołu. W notatce stoi sama odznaka „@Wszyscy”.
- **Wzorzec znacznika** jest w dwóch miejscach i musi być ten sam:
  `_EVERYONE_RE` w `services/mention_parser.py` i `EVERYONE_SOURCE`
  w `lib/renderMentions.tsx`. `@wszyscy` musi być osobnym słowem:
  `biuro@wszyscy.pl` i `@wszyscy@firma.pl` to adresy.
- **Podpowiedź:** pozycja „Wszyscy przypisani · N osób” stoi w liście „@”
  pola rekrutacji na samym „@” i przy „wsz”, „zesp”, „all”, „everyone”.
  Lista osób przychodzi z `GET /api/jobs/{id}/chat/members?assigned=true`.
  Pod polem po wstawieniu: „Wzmiankę dostanie N osób: …”. Gdy przypisany
  jest tylko autor, pozycji nie ma.
- Przewodnik Jarvisa („jobs.person”) nie wspomina `@wszyscy`: odpowiedź o notatkach jest przy limicie 350 znaków.
- `has_mention` uznaje `@wszyscy` za wzmiankę, więc Jarvis pyta przed
  `create_note` z tym znacznikiem.

Testy: `tests/test_mention_everyone.py`,
`test_job_chat.py::test_everyone_mentions_only_assigned_people`,
`MentionTextarea.test.tsx`, `renderMentions-everyone.test.tsx`.
