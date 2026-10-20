# Odrzucenie z uzasadnieniem i rozmowa u tego samego managera (20.10.2026)

Decyzja Artura 20.10.2026 (wariant A + B + C z makiet `67bSoc1Xs7tXDRDDLC1a49`).
Delivery Lead chciał odrzucić osobę, bo była już na rozmowie u managera tej
rekrutacji. Przy „Inne” nie było pola na opis, a serwer zapisywał tekst tylko
bez powodu ze słownika, więc w historii zostawało samo „Inne”.

- **Opis powodu = `notes` ruchu.** Profil kandydata pokazuje go jako
  „Powód — opis” (`_format_rejection_reason`). Nie trafia do maila odrzucenia.
- **„Inne” i „Już po rozmowie u tego hiring managera” wymagają opisu.** Serwer
  (`apply_move`) odrzuca taki ruch bez `notes` i bez `rejection_reason` (422).
  Reguła jest w `rejection_reason_labels.needs_description`, a jej lustro na
  froncie to `reasonNeedsDescription`. Dotyczy panelu DL, okna odrzucenia na
  Tablicy (RejectionV2) i API integracyjnego. API integracyjne może podać opis
  w `rejection_reason` obok `rejection_reason_id` i ten opis też ląduje w `notes`.
- **Nowy powód `hm_already_interviewed`** (migracja 0484 plus lustro
  w `entrypoint.sh`). Dotyczy tylko odrzucenia, nie rezygnacji, i stoi przed
  „Inne”. Ma `disqualifies_person = false`: znaczy, że manager zna osobę,
  a nie, że ją odrzucił. Nie uruchamia weta z `hiring_manager_verdicts`.
- **Wcześniejsze rozmowy** (`services/earlier_client_interviews.py`, pole
  `earlier_interviews` w `GET /api/dl-review/context`) to procesy osoby
  w innych rekrutacjach rodziny klienta, w których doszła do kolumny
  „Rozmowa u klienta” albo „Umowa”. Kolumnę liczy `board_column_for`, bo etapy
  Nordei są rozpoznawane po nazwie. Zatrudnienie się nie liczy.
- **Panel DL, powód „Już po rozmowie…”:** DL wybiera rozmowę z listy albo
  „Poza NEXUSEM”. Notatka ma postać „Tytuł · rozmowa DD.MM.RRRR — dopisek”.
  Przy „Poza NEXUSEM” albo pustej liście opis jest obowiązkowy.
- **Ostrzeżenie w panelu DL** pojawia się tylko wtedy, gdy rozmowa była
  w rekrutacji z tym samym `hiring_manager_contact_id`. Bez wpisanego hiring
  managera ostrzeżenia nie ma. Ostrzeżenie nie blokuje akceptacji. „Odrzuć
  z tym powodem” otwiera formularz z wybranym powodem i rozmową, a „Wiem —
  oceniam dalej” chowa ostrzeżenie dla tej osoby.
