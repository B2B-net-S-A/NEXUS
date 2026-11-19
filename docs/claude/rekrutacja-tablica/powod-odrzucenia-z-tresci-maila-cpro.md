# Powód odrzucenia z treści maila CPro zamiast „Inne” (19.11.2026)
<!-- indeks: cpro_reason_map, reason_name_for, cpro_mail._reason_id, client_other_vendor, client_interview_weak, 0740, cpro_rejection_reason_repair, nexus_reason w banerze CPro, weto hiring managera -->

Decyzja Artura 19.11.2026 (sprawa B7, wariant A z makiet
`FiA2yR96sow4Bo6pq1C7EU`). Po #3040 udział „Inne” w odrzuceniach przez klienta
wzrósł z 23% do 33%, choć człowiek wybierał „Inne” rzadziej (37% → 5%). Cały
wzrost to automat poczty CPro: każdy mail „rejected” lądował jako
„Inne (rejected)” z tekstem klienta w notatce „Z CPro: …”.

- **Słownik fraz, nie model.** `services/cpro_reason_map.reason_name_for`
  przypisuje tekst klienta do powodu z szablonu. Sprawdzony na 108 tekstach
  z produkcji (02–19.11): 104 trafiają, 4 zostają przy „Inne”. Kolejność reguł
  ma znaczenie: inny dostawca przed „wybrał kogoś innego”, grzecznościowe
  formułki o innych kandydatach przed oceną osoby, rozmowa przed brakiem
  doświadczenia. Mail bez tekstu to „Klient nie podał powodu”. Tekst bez
  trafienia i szablon bez danego powodu dają „Inne”, a notatka „Z CPro: …”
  zostaje zawsze, więc pomyłka słownika nie gubi tego, co napisał klient.
  Nowy wzorzec tekstu = przypadek w `tests/test_cpro_reason_map.py`.
- **Dwa nowe powody klienta (0740 + lustro w `entrypoint.sh`):**
  `client_other_vendor` „Zgłoszony już przez innego dostawcę” (duplikat, tańsza
  oferta) i `client_interview_weak` „Rozmowa u klienta wypadła słabo”. Tylko
  przy „Odrzuca klient” (`CLIENT_ONLY_REASONS`), w grupie „Klient” okna.
  Przy 1280 × 720 „Inne” schodzi przez nie pod zgięcie okna; Artur to widział
  na makiecie.
- **Weto hiring managera jak przy ręcznym odrzuceniu** (decyzja Artura).
  Powód z CPro liczy się tak samo jak wybrany przez człowieka: „Brak
  doświadczenia”, „Nie spełnia wymagań”, „Nie pasuje kulturowo” i słaba rozmowa
  mają `disqualifies_person = true`; inny dostawca nie (jest też
  w `CLIENT_NOT_A_VERDICT`). Na danych z 19.11 weto dostało 7 osób po rozmowie
  u klienta.
- **Stare wpisy:** naprawa jednorazowa `cpro_rejection_reason_repair`
  w `entrypoint.sh` (znacznik `cpro_rejection_reason_repair_2026_11_19`)
  przepina „Inne” z notatką „Z CPro” przy `ended_by = client`. Paragon
  w `app_settings` pod znacznikiem: trójki `[id wiersza, stary powód, nowy
  powód]`, z których da się cofnąć zmianę. Ręcznych „Inne” nie rusza.
- **Baner CPro w rekrutacji** pokazuje przy osobie pigułkę z powodem
  (`nexus_reason` w `GET /api/jobs/{id}/cpro-events`, liczone tym samym
  słownikiem).
- **Insights „Wnioski”:** inny dostawca → „KonfliktKlient”, słaba rozmowa →
  „Umiejetnosci”.
