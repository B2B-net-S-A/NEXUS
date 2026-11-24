# Notatka z wysyłki w follow-upie, pakiecie CV i cytatach „skąd ✓”

Uzupełnia decyzję C (14.10.2026) z `rekrutacje-i-kandydatow-widza-wszyscy-stawki-do.md`:
notatka Delivery Leada „Wysłany 150/100-110” to cena dla klienta, a filtr rodzajów
(`ai_readable_clause` / `ai_readable_sql`) jej nie łapie, bo to zwykła notatka `human`.
Audyt r4 (24.11.2026) znalazł trzy kolejne powierzchnie, na których rekruter ją czytał.
Od tej poprawki każda woła `candidate_access.hidden_send_note_ids(db, widz, ids)`
(rola ze stawką do klienta — zero zapytań) i `note_content_hidden(..., send_note=)`:

- **Follow-up** — ostatnia notatka procesu w `GET /api/candidate-followups/candidates/{id}`
  i odpowiedziach zapisu wyniku/przejęcia/spotkania (`serialize_rows(..., with_notes=True,
  viewer=)`, `_detail(..., viewer=)`): zdanie zastępcze `CLIENT_RATE_PLACEHOLDER`.
  Bez widza zakrywa (nie wiadomo, kto czyta). Pulpit i Tablica (`board_tasks`) nie biorą
  notatek (`with_notes=False`).
- **Cytaty „skąd ✓”** (`POST /api/search/candidates/requirement-evidence`,
  `requirement_evidence.load_notes(..., viewer=)`): notatka wypada ze źródeł — cytat
  ±45 znaków niósłby kwotę, a zdanie zastępcze w cytacie nic nie mówi (jak wycinki
  wyszukiwania).
- **Lista notatek pakietu CV** (`GET /api/cv-generator/generated/{id}/package`):
  zdanie zastępcze zamiast treści, id zostaje — wybór notatki do pakietu i odcisk
  (`cv_packages.assess`) się nie zmieniają.

Delivery Lead, Head of Recruitment, Finanse i pozostałe role z `user_can_view_client_rate`
widzą treść; autor zawsze widzi własną notatkę. Testy bez bazy:
`backend/tests/test_audit_r4_send_note_surfaces.py`.
