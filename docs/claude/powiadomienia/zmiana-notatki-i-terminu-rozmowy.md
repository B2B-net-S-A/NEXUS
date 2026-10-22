# Zmieniona notatka z oznaczeniem i przełożona rozmowa u klienta (21.10.2026)
<!-- indeks: `notify_mentions`, `interview_changed` (0500), kto dostaje -->

Zgłoszenie rekruterki: terminy prepów i rozmów często się zmieniają, a gdy
rekruter poprawiał notatkę, w której oznaczył Delivery Leada, DL nic nie
dostawał — powiadomienie szło tylko do osób dopisanych w tej edycji. Zmiana
terminu rozmowy u klienta w kalendarzu nie powiadamiała nikogo (prep tak, od
0453). Decyzja Artura 21.10.2026: oba w jednym PR. Makiety:
https://claude.ai/artifact/3zTatChF7unCnUcYXkxLAN.

## Edycja notatki — „Powiadom oznaczonych o zmianie”

- **Pole w edytorze notatki** (`NotesList.renderEditor` — profil i panel
  osoby): widać je, gdy treść się zmieniła i zostaje w niej ktoś, kto był
  oznaczony już wcześniej (bez autora) — `lib/note-edit-notify.ts`
  (`notifyOnEditRecipients`, lustro serwera). **Domyślnie zaznaczone**;
  przy literówce autor odznacza. Przycisk mówi wtedy „Zapisz i powiadom”.
- **Serwer:** `PATCH /api/notes/{id}` z `notify_mentions: true` wysyła
  `note_mention` z tytułem „X zmienił(a) notatkę, w której Cię oznaczył(a)”
  osobom z `nowe ∩ stare` wzmianki, gdy treść się zmieniła. Bez pola (stary
  klient, przypięcie, literówka) — jak dawniej: fragment w istniejącym
  powiadomieniu odświeża się po cichu. Nowo dopisani dostają zwykłą wzmiankę
  niezależnie od pola. `notify_mentions` nie jest kolumną — nie trafia do
  `setattr` na notatce.
- **Gdzie to widać:** typ `note_mention`, czyli ikona „Wiadomości” z „@”
  i dymek (`TOAST_TYPES`), mail w kategorii „mentions” z tematem „zmienił(a)
  notatkę…” (`send_mention_email(edited=True)`). Dzisiejszy wiersz tej
  notatki wraca jako nieprzeczytany (`dedupe_resurface`), starszy — nowy wiersz.
- Pierwsza wersja nie ma dopisku „edytowano · powiadomiono” przy notatce
  (był na makiecie jako propozycja).

## Rozmowa u klienta przełożona albo odwołana — `interview_changed` (0500)

- **Kiedy:** wydarzenie `client_interview` z parą (kandydat + rekrutacja),
  przed nami — `PATCH` zmieniający początek (`moved`), `PATCH status=cancelled`,
  `POST …/cancel` i `DELETE` (`cancelled`). Zmiana samego tytułu, miejsca
  albo rozmowy, która już się odbyła, nic nie wysyła.
  `services/interview_change_notifications.py`, wołane z `api/calendar.py`.
- **Kto:** Delivery Lead rekrutacji, rekruter pary
  (`interview_slots.default_recruiter_ids`) i właściciel wydarzenia, bez
  autora zmiany.
- **Treść** w brzmieniu prepu: „Rozmowa u klienta przełożona na 24.10, 14:00”
  / „… odwołana”, w treści kandydat, rekrutacja, kto zmienił i „było …”.
  Link `/calendar?cycle=<kandydat>-<rekrutacja>`.
- **Encja bez ID** (`client_interview_<rodzaj>`, `None`) — jak `prep_changed*`:
  dzienny dedup zjadałby drugie przełożenie tego samego dnia.
- **Gdzie to widać:** kategoria „Rozmowy” → ikona „Kalendarz”, sekcja „Nowe”,
  z dymkiem (nie ma go w `QUIET_INTERVIEW_TYPES`). Front: typ w
  `INTERVIEW_NOTIFICATION_TYPES`, ikona `calendar` w `interview-window.ts`.
- **Poza zakresem:** przełożenie rozmowy w samym Outlooku (synchronizacja
  M365) — ta ścieżka powiadomienia nie wysyła.
- Nowy typ = migracja 0500 i lustro `ALTER TYPE` w `entrypoint.sh`
  (`test_interview_change_notifications.py`).
