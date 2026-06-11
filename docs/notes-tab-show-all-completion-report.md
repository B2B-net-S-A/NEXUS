# Notatki tab — pokazuj WSZYSTKIE notatki (też z Traffita)

[← Wróć do docs](./)

**Data:** 2026-06-11
**Commit:** `862416b` (deploy SHA `ae8ea84`)
**Zgłoszenie:** „Jest: Brak wszystkich notatek z traffita. Ma być: Wszystkie notatki
z traffita mają być pobrane i widoczne." — `https://nexus.dynaminds.pl/candidates/20164`

## Root cause

Zakładka **Notatki** (`NotatkiTab` w `CandidateDetailV2`) wyprowadzała notatki z
endpointu `/api/candidates/{id}/timeline?limit=50`, filtrując `type === "note"`.
Timeline **miesza** notatki ze zmianami etapów, aktywnościami i user-activities,
sortuje malejąco po dacie i **ucina cały feed do `limit` (50)** (`timeline[:limit]`).

Kandydat 20164 (Karol Dróżdż) ma **37 notatek** w bazie + etapy + aktywności.
Po połączeniu i ucięciu do 50 pozycji starsze notatki wypadały poza okno i
znikały z zakładki (UI pokazywał ~19). Notatki były w bazie cały czas
(`SELECT count(*) FROM notes WHERE candidate_id=20164` → 37).

## Fix

Dedykowane, **nieucinane** źródło notatek dla zakładki Notatki:

- **Backend** `GET /api/notes` (`backend/app/api/notes.py`) zwraca teraz
  `EnrichedNoteList`: komplet notatek (bez limitu) wzbogacony o
  `author_name`/`author_email` (User outerjoin), `content_rendered`
  (rozwinięte `$$user_NN$$` Traffit mention tokeny — jak w `/timeline`) i
  `job_title`. Nowe schematy `EnrichedNoteResponse`/`EnrichedNoteList`
  (`backend/app/schemas/note.py`) — superset starego `NoteResponse`
  (wstecznie zgodne).
- **Frontend** `CandidateDetailV2.tsx`: zakładka Notatki czyta z dedykowanego
  query `["candidate-notes", id]` → `/api/notes?candidate_id=id` zamiast z
  uciętego timeline'u. Invalidacja cache po add/edit/delete notatki.
- **Timeline tab** bez zmian (chronologiczny recent feed, limit OK).

## Weryfikacja (prod)

- `GET /api/notes?candidate_id=20164` → `200`, `total: 37`, `count: 37`,
  `author_name` + `content_rendered` wypełnione.
- UI (Chrome): zakładka Notatki woła `/api/notes` (200) i renderuje **37**
  kart notatek z autorami (Katarzyna Orlinska, Marlena Rosol, …). Wcześniej
  badge „19".

## Pliki

- `backend/app/api/notes.py` — enriched `list_notes`
- `backend/app/schemas/note.py` — `EnrichedNoteResponse` / `EnrichedNoteList`
- `frontend/src/components/v2/pages/CandidateDetailV2.tsx` — dedykowany notes query
