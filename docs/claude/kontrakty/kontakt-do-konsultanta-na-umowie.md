# Kontakt do konsultanta na umowie (09.2026, migracja 0320)

Karta „Informacje o kontrakcie" pokazuje e-mail i telefon konsultanta w jednym
wierszu pod „Typ kontraktu". Reguła kolejności źródeł ma JEDNO miejsce:
`services/contract_candidate_contact.py` (front renderuje gotowy wynik, nie
powtarza reguły).

- **`contracts.candidate_email` / `candidate_phone` to NADPISANIE, nie migawka.**
  Wartość trafia tam z „Danych Partnera" generatora B2B albo z ręcznej edycji
  w widoku kontraktu. Pusta kolumna znaczy „weź z profilu kandydata", a fallback
  liczy się przy ODCZYCIE — poprawiony w profilu telefon jest na umowie widoczny
  od razu. Materializacja profilu przy backfillu dałaby umowy z kontaktem
  starzejącym się w ciszy, dlatego korekta 0320 kopiuje **wyłącznie poziom
  pierwszy** (dane z generatora).
- **Wyczyszczenie pola przywraca fallback.** Pusty string i jawny `null` w PATCH
  normalizują się do `NULL` (`_normalize_candidate_contact_updates`). Gdyby pusty
  string zapisywał się dosłownie, „usunąłem wartość" znaczyłoby „zablokowałem
  profil na zawsze", a pusta komórka obok wypełnionego profilu czyta się jak
  utrata danych. Wartość dłuższa niż kolumna jest ODRZUCANA (422), nie przycinana
  — przycięty numer telefonu wygląda na poprawny.
- **Odpowiedź szczegółów niesie trzy pary pól** (`candidate_email`,
  `candidate_email_effective`, `candidate_email_source` i analogicznie telefon).
  Bez `*_source` nie da się oznaczyć „z profilu" ani wytłumaczyć, czemu
  wyczyszczone pole nadal coś pokazuje. Lista kontraktów tego nie dostaje.
- **Zapis na umowę jest FILL-ONLY na wszystkich ścieżkach**
  (`fill_candidate_contact` w `b2b_contract_automation`): podpis obustronny
  (`confirm-fully-signed`, także z `keep_existing_terms`) i `POST /render`, gdy
  para (kandydat, rekrutacja) ma DOKŁADNIE JEDEN nie-`void` kontrakt. Zero
  trafień albo więcej niż jedno = pominięcie: wpisanie kontaktu w zgadniętą
  umowę jest gorsze niż jego brak. Stempel z `/render` jest fail-soft — awaria
  nie może zabrać wygenerowanego DOCX-a.
- **Twarde usunięcie kandydata ZERUJE obie kolumny** (`api/candidates.py`, art. 17
  RODO). Wiersz umowy celowo zostaje (podpisy, faktury), ale kontakt do usuniętej
  osoby przeżyłby w ciszy — żaden ekran nie mówi, że umowa trzyma własną kopię.
- **Edycja w miejscu reużywa `InlineText`** z `components/orders/InlineOrderFields`;
  bramka to istniejące `canEditContract` (admin + DL + zapis sekcji Delivery) —
  to samo, co odsłania przycisk „Edytuj". Bez nowej capability.
- **Raport braków: `GET /api/contracts/candidate-contact-report`** (Admin, bez
  przycisku w UI — jak `order-sync-report`). 409 przed wykonaniem korekty. Do
  arkusza „Braki" trafia kontrakt, dla którego **rozstrzygnięty** e-mail lub
  telefon jest pusty, czyli ani umowa, ani profil nic nie dają — zapytanie
  o samą pustą kolumnę wysyłałoby zespół do przepisywania danych, które i tak
  widać. Paragon korekty (`0320_contract_candidate_contact`) niesie liczniki
  i ID; wartości (PII) leżą pod `repair_details_…`, którego publiczny
  `show_migration_receipts` nie wydrukuje.
- **`render_payload` starych dokumentów zostaje nietknięty** — korekta go czyta,
  nie czyści. Kontakt w podpisanym dokumencie jest zapisem tego, co strony
  podpisały.
