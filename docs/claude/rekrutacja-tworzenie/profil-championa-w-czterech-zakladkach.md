# „Profil Championa” w czterech zakładkach (04.10.2026)

Decyzje Artura 04.10.2026 (makiety https://claude.ai/artifact/FwQr2uYhWcRfdDeWdbStUc).
Do tej daty widok „Zlecenie i Champion” był jedną stroną: „Podgląd” ok. 5 000 px
(sam blok „Po ludzku” 2 170 px), „Edytuj” 51 pól naraz, obok panel „Gotowość”,
który pokazywał „przekazane do searchu” i jednocześnie aktywne „Przekaż do searchu”.

- **Nagłówek: „Tablica” | „Profil Championa”** (`tab=champion` bez zmian,
  odznaka „brakuje N” zostaje). „Karta klienta”, „Kopiuj link do rekrutacji”,
  „Zamknij rekrutację…” i **„Edytuj cały Profil Championa”** są w menu „⋯”.
- **Cztery zakładki** (`components/champion/ChampionWorkspace.tsx`, `?ptab=`,
  stare `readiness` → Brief, `announce` → Zespół z rozwiniętymi portalami —
  `lib/champion-blocks.ts`):
  - **Brief** (`ChampionBriefView`) — to, co rekruter musi wiedzieć przed
    telefonem: „Jednym zdaniem” (`PlainBriefBlock parts="summary"`), czego
    szukamy (dymek słowniczka na chipie, `lib/plain-glossary-lookup.ts`),
    pytania na rozmowę, co powiedzieć kandydatowi, o projekcie; z prawej
    warunki, kto prowadzi, do dopytania u klienta. Nad nim pasek
    **„Do dopięcia”** (`ChampionTodoStrip`): braki bramki, przekazanie (tylko
    rekrutacja NIEprzekazana) i weryfikacja z klientem, konsultantem, briefing —
    tylko z uprawnieniem do prowadzenia rekrutacji i tylko gdy jest co dopiąć.
  - **Technologie po ludzku** (`PlainBriefBlock parts="knowledge"`) —
    słowniczek, rola z biblioteki, pytania po ludzku.
  - **Klient i historia** (`ChampionClientTab`) — opis klienta, karta klienta,
    pytania klienta z rozmów, wiedza z rozmów, wcześniejsze zapytania.
  - **Zespół i ogłoszenie** — `JobTeamTab` i `JobAnnouncementSection`.
- **Edycja blokami:** „Edytuj” przy bloku otwiera szufladę
  (`ChampionEditDrawer` → `ChampionProfileEditor layout="drawer"
  onlySections=…`, mapa bloków w `CHAMPION_BLOCKS`). Zapis to ten sam
  `PUT …/champion-profile` z całym szkicem (serwer scala). Brak z bramki
  wskazujący sekcję otwiera jej blok (`blockForAnchor`), także z okna
  „Zlecenie”; brak bez bloku — pełny formularz.
- **Pełny formularz** (`?mode=edit`, stare `?intake=1`) = `layout="workspace"`
  z „Wypełnij szybciej”, przycisk „← Wróć do Profilu Championa”. Edytor zostaje
  zamontowany po wyjściu — niezapisany szkic przeżywa, a zakładki pokazują
  „Masz niezapisane zmiany w pełnym formularzu”.
- **Panelu bocznego nie ma** — `JobReadinessDock` ma już tylko wariant listy
  (eksport `JobTeamTab` zostaje). `JobHandoffButton` przy `already_handed_off`
  pokazuje „Przekazana do searchu” zamiast przycisku.
- Harness `/preview/champion-workspace` (`?ptab=`, `?drawer=search`,
  `?as=recruiter`). Nowa funkcja tego ekranu = wpis w
  `lib/recruitment-feature-inventory.json`.
