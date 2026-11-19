# „Nie szuka pracy” z datą przy każdej karcie, nie tylko od systemu
<!-- indeks: `not_looking_until` w ruchu, NotLookingUntilField w RejectionV2 przy `not_looking_for_work`, 3 mies. domyślnie, wspólne `_mark_not_looking_from_move`, źródło `not_looking_rejection` -->

Decyzja Artura z 19.11.2026 (wariant A z makiet:
https://claude.ai/artifact/Y81iqmGYv5jpdg9nKYk8bM), po zgłoszeniu rekrutera
„zniknęła opcja kontakt za pół roku”. Wybór „3 miesiące / 6 miesięcy / Rok”
stał tylko przy osobie od systemu z Nowych i Screeningu
(`needsAutofillReason`). Na kopii z 19.11.2026 w 30 dni 179 odrzuceń „Nie szuka
pracy” na kartach dodanych ręcznie nie miało daty, a 116 na kartach od systemu
ją miało; rekruterzy dopisywali „odezwę się za pół roku” w notatce.

- **Okno:** przy powodzie `not_looking_for_work` z listy szablonu stoi to samo
  pole co przy osobie od systemu (`NotLookingUntilField`), domyślnie 3 miesiące.
  Osoba od systemu dalej podaje datę w wyborze dla systemu (`autofill`).
- **Ruch:** `not_looking_until` w `/api/pipeline/move`, tylko przy tym powodzie,
  od jutra do dwóch lat (`autofill_feedback.check_not_looking_until`, ta sama
  reguła co `autofill_not_looking_until`). Bez daty profil zostaje bez zmian,
  więc API integracyjne i stare okna działają jak dotąd.
- **Zapis:** `_mark_not_looking_from_move` w `api/pipeline.py`, wspólne z osobą
  od systemu: profil „Nie szuka” + „Dostępny od”, wpis
  `candidate_availability_changed` ze źródłem `not_looking_rejection`
  i zdjęcie nietkniętych kart od systemu z innych rekrutacji. Wybrana data
  nadpisuje dotychczasową, bo to świeża deklaracja z rozmowy.
- **Zbiorcze odrzucenie z osobą od systemu:** osoby dodane ręcznie dostają datę
  z jej wyboru „Nie szuka” (`confirmRejection` w `usePipelineMove`).
- **Bez przypomnienia.** Po dacie system znów podsuwa osobę; zadania „odezwij
  się” na pulpicie nie ma (warianty B i C z makiet odłożone).
- **„Zatrudniony gdzie indziej” bez zmian:** dalej 3 miesiące bez pola
  (`zatrudniony-gdzie-indziej-nie-szuka-3-miesiace.md`).
