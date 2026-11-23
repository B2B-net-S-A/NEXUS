# Rozwiązanie umowy spoza NEXUSA — porozumienie i wypowiedzenie do kontraktu (23.11.2026)

<!-- indeks: accepts_contract, wybór osoby zamiast listy rejestru, numer i data umowy wpisane ręcznie, bez „Bez kontraktu” -->

Zgłoszenie z Finansów (23.11.2026): porozumienia nie dało się przygotować,
bo „Umowa bazowa” w kreatorze Dokumentów pokazywała wyłącznie rejestr
generatora. Rejestr ma umowy wystawione w NEXUSIE od 09.06.2026, a na
produkcji 392 z 510 trwających kontraktów nie miało w nim wiersza (importu
z Excela działu na produkcji nie ma). Decyzja Artura: wariant „umowa spoza
NEXUSA”, jak przy trzech aneksach.

- **Flaga `accepts_contract`** (`services/b2b_documents/registry.py`) mają
  `termination_agreement` i `termination_notice`. Bez umowy z rejestru dokument
  przyjmuje KONTRAKT B2B (`contract_id`), osobę i klienta bierze serwer
  z kontraktu (`_load_subject_contract`, ta sama bramka `_binds_contracts` co
  przy aneksie). Kontrakt z żywą umową w rejestrze odmawia
  (`_reject_contract_with_own_agreement`) — wtedy dokument idzie przez umowę.
  Cofnięcie wypowiedzenia flagi nie ma: zmienia tylko wiersz rejestru.
- **To nie jest `allows_external`.** Ta flaga znaczy „aneks z zakładki
  Generator aneksów” i włącza `annex_register.apply` przy wygenerowaniu oraz
  „Bez kontraktu”. Rozwiązanie bez kontraktu nie miałoby czego zakończyć:
  serwer daje 422 „Wybierz umowę z rejestru albo kontrakt”, a wybór osoby nie
  pokazuje przycisku „Tej osoby nie ma w kontraktach”. `effects.annex_takes_contract`
  (blokada „Bez kontraktu”, powiązanie aneksu) zostaje tylko dla aneksów;
  rozszerzony jest `_takes_contract` w `api/b2b_documents.py`.
- **Numer i data umowy** to pola grupy `base` (`EXTERNAL_BASE_FIELDS`) bez
  `required` w rejestrze typów: przy umowie z rejestru zna je wiersz i front ich
  nie pokazuje (`typeForSubject` w `lib/b2b-documents.ts`), bez wiersza wymaga
  ich serwer (`_validate_values(..., external=True)`) i front. Wersja wzoru
  umowy jest nieznana, więc formularz prosi o numery paragrafów — jak przy
  wierszu z Excela. Prefill podpowiada numer i datę z kontraktu
  (`b2b_contract_details`), jeśli ktoś je tam wpisał.
- **Wybór w kreatorze = `AnnexSubjectPicker`** („Czyją umowę rozwiązujesz?”):
  umowy z rejestru i kontrakty bez umowy w rejestrze. Dla rozwiązań lista umów
  bierze statusy `_LIVE_AGREEMENT_STATUSES` (także `suspended` — umowa bez
  projektu), bo dotychczasowa lista z `GET /generated` je pokazywała. Wymaga
  wpisania co najmniej dwóch znaków (stara lista pokazywała od razu 20
  najnowszych).
- **Komunikaty po zapisie** rozróżniają aneks po `family`, nie po rodzaju
  wyboru: rozwiązanie nie jest w rejestrze aneksów.
- Podpis działa bez zmian: `effects.apply` kończy kontrakt dokumentu
  (`current_contract_id` = kolumna dokumentu, gdy nie ma wiersza), a wiersza
  rejestru nie ma do zamknięcia. Przećwiczone na stagingu 23.11.2026 (Finanse
  generuje, podpis kontem z „Zakończenie współpracy”). Testy:
  `test_b2b_termination_outside_nexus.py`, `lib/__tests__/b2b-documents.test.ts`.
