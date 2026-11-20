# Jeden słownik powodów zamknięcia procesu (19.11.2026)
<!-- indeks: close_reasons.py, CLOSE_REASON_GROUPS, 0745, close_reason_dictionary_seeded, AUTOFILL_TEMPLATE_REASON 1:1, client_project_closed, client_after_deadline, available_too_late, LEGACY_TO_KEY, „Kto kończy?”, early_only, rezygnacja w tym samym oknie -->

Decyzja Artura 19.11.2026 (wariant A makiety „Zamknij proces”). Do tego dnia
NEXUS pytał o powód z czterech list: okno „Nowych”/„Screeningu” (powody dla
systemu), lista z szablonu od „Zweryfikowanego”, osobne okno rezygnacji
i porcja dnia z innymi nazwami tych samych kluczy. 8 z 19 powodów okna
lądowało w szablonie jako „Inne” z nazwą w opisie. Na kopii produkcji
(60 dni) „Inne” to 22% odrzuceń w „Nowych”/„Screeningu” (1026 z 4686) i 27%
u klienta (108 z 397).

- **Źródło słownika:** `backend/app/services/close_reasons.py`
  (`CLOSE_REASON_GROUPS`), lustro na froncie w `lib/`. Każdy powód ma klucz,
  etykietę do historii, „kto może wybrać” (`recruiter` = my albo DL,
  `client`, `candidate`), nazwę wiersza szablonu przy odrzuceniu i przy
  rezygnacji, a „Dane w bazie” także `early_only` (tylko „Nowi”/„Screening”).
  Grupy: Klient (tylko „Odrzuca klient”), Nie pasuje do wymagań, Warunki,
  Sprawa osoby, Dane w bazie, „Inne” na końcu z obowiązkowym opisem.
- **Klucz słownika = powód dla systemu.** `AUTOFILL_TEMPLATE_REASON` mapuje
  1:1. `null` mają tylko stary „Język”, „Porządki” z porcji i „Inne”.
  Uczenie systemu (`autofill_feedback`, koszyki) zostaje; nowe powody dla
  systemu: kultura, termin dostępności i przyjęta oferta to „Sprawa osoby”,
  rozmowa u tego HM to „Brak danych”, powody klienta to „Inne” w raporcie
  jakości (mówią o decyzji klienta, nie o doborze).
- **Stare nazwy zostają kluczami.** Gdzie szablon miał powód o tym znaczeniu,
  słownik go używa: „Brak doświadczenia”, „Nie spełnia wymagań technicznych”,
  „Za wysokie oczekiwania finansowe” / `salary_mismatch`, `work_mode_mismatch`,
  „Zatrudniony gdzie indziej” (= „Przyjęła inną ofertę” przy odrzuceniu,
  dalej zapisuje „Nie szuka” na 3 miesiące), `client_other_vendor`
  (= „Pracuje u klienta / zgłoszona przez inną firmę”, wybieramy go też my).
  Po tych nazwach szukają ocena ryzyka, CPro, nowa stawka i weto HM, więc nie
  zmieniaj ich w bazie — etykietę daje `rejection_reason_label`.
- **Schemat (0745 + lustro w `entrypoint.sh`):** brakujące powody w każdym
  szablonie, w odrzuceniu i rezygnacji, tuż przed „Inne” tej kategorii,
  jednorazowo przez `close_reason_dictionary_seeded`. Weto hiring managera
  dostają tylko „Brak polskiego” i „Angielski za słaby”; „Za wysoki poziom”
  i „Inna rola” mówią o roli, nie o osobie. Migracja odświeża też więz
  `ck_autofill_feedback_reason`. Starych wpisów nikt nie przepina.
- **Historia i raporty:** stare nazwy bez miejsca w oknie dostają etykietę
  powodu słownika o tym znaczeniu (`LEGACY_TO_KEY`: `process_too_long`,
  „Brak odpowiedzi”, „Kandydat nieosiągalny”), więc Insights → etapy, które
  liczą po etykiecie, sumują stare i nowe wpisy. `client_conflict` (0646)
  łączył dwa powody i zostaje z własną etykietą. Insights „Wnioski” mają
  nowe klucze w `_READ_CASE`.
- **Okno (etap 2):** `RejectionV2` przy odrzuceniu zawsze pyta z listy
  słownika (`AutofillFeedbackField` z `groups`) — na Tablicy, w panelu
  osoby, w formularzu screeningu i w zakładce rozmów. Grupy w trzech
  kolumnach, każda do najkrótszej (`reasonColumns`), żeby przy 1280 × 720
  „Dane w bazie” i „Inne” nie spadały pod zgięcie. Wiersz szablonu wynika
  z powodu 1:1 (`closeTemplateReason`); szablon bez wiersza → „Inne”
  z etykietą powodu w opisie. Zmiana „Kto kończy?” zdejmuje powód, którego
  nie ma na nowej liście. „Skąd to wiesz?”, podpowiedź raportu i „na cały
  klient” tylko przy osobie od systemu. Opis obowiązkowy przy „Inne”
  i „Już po rozmowie u tego HM”. Panel DL i karta rozmowy u klienta biorą
  wiersze szablonu przez `closeTemplateOptions` (bez wierszy spoza słownika).
- Nowy powód = wpis w `close_reasons.py`, wiersz w nowej migracji z lustrem,
  klucz w `autofill_feedback_schema.REASONS` i lustro na froncie
  (`test_close_reasons.py` pilnuje zgodności).
