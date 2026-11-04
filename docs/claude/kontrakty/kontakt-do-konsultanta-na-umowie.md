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

## Menedżer u klienta (D8, „Ludzie w NEXUSIE” etap 2, 17.10.2026)

Druga strona tej samej karty: osoba po stronie KLIENTA, pod którą pracuje
konsultant. Kolumna `contracts.client_pm_contact_id` (0097) była w bazie, ale
API i ekrany jej nie pokazywały; do 17.10 obok stały tylko teksty „PM po stronie
klienta” i „Line Manager”. Reguły w `services/contract_client_manager.py`.

- **Menedżer to kontakt klienta TEGO kontraktu.** PATCH z kontaktem innego
  klienta = 422. Sprawdzamy tylko realną zmianę — formularz z dawnym,
  błędnym kontaktem nie blokuje zapisu innych pól (taki kontakt blokuje za to
  przepięcie kontraktu na innego klienta, `contract_client_reassign`).
- **Nowa osoba** idzie w `client_pm_new_person` (nigdy razem z
  `client_pm_contact_id` — 422) przez `job_hiring_manager.find_or_create_contact`:
  ta sama osoba wpisana inaczej nie staje się drugim kontaktem.
- **Teksty PM i Line Manager zostają opisem.** Gdy kontakt jest pusty, a tekst
  to DOKŁADNIE imię i nazwisko kontaktu klienta (bez wielkości liter), odpowiedź
  szczegółów niesie `client_pm_contact_hint` i ekran pokazuje „Przypnij: X”.
  Skrót („Michał R.”) nie podpowiada nikogo. Nic nie przypina się samo.
- **Domyślnie hiring manager rekrutacji** — przy ręcznym zakładaniu kontraktu
  z `job_id` (`POST /api/contracts`, „Nowy kontraktor” z zamówieniem) i w
  automacie „Zatrudniony” (także gdy szkic bez rekrutacji właśnie ją dostaje),
  o ile HM jest kontaktem klienta kontraktu. Wpisanego menedżera automat nie
  zmienia.
- **Front**: pole „Menedżer u klienta” w sekcji „Osadzenie u klienta” edycji
  kontraktu (ten sam `HiringManagerCombobox` z etykietami menedżera) i fakt
  „Menedżer u klienta” nad zakładkami. Odpowiedź szczegółów niesie imię
  i stanowisko (`client_pm_contact_name`, `client_pm_contact_position`); lista
  kontraktów — samo id.
- **Scalanie i powrót po przerwie** przenoszą pole jak dotąd (`contract_merge`
  `_MERGEABLE_FIELDS`, `contract_return_after_break._COPIED_FIELDS`). Struktura
  u klienta i opinie — `docs/claude/ludzie/opieka-mapa-technologii-i-sprawy.md`.
