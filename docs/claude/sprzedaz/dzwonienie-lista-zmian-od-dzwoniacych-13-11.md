# Dzwonienie: lista zmian od osób dzwoniących — decyzje Artura 13.11.2026
<!-- indeks: Nie odebrane osobna zakładka, zdjęte Nie zainteresowany i Nie teraz, RETIRED_OUTCOMES, oferta bez ponownego kontaktu never, kolejka z wyborem osoby caller_id, zapis wyniku każdy z Sprzedaż edycja, import Typ usługi, kolumna Kto dzwoni Bianca Marcel, caller_keys, bramka NIP NIP_LOADED_DETAIL, Uwagi o firmie na karcie, edycja danych PATCH records, kopiuj adres, Tabela od ostatniej modyfikacji, filtr dat powrotu, strony zamiast Pokazano 200 z 239, zmiana statusu z Tabeli bez telefonu, Przypomnienia, Mój dzień przypomnienia, spotkania przy szansie osoby, oferta do Leadów calling_crm, spotkanie zamyka lead, treść zaproszenia i adres klienta invite_message invite_to -->

Powód: lista zmian od osób dzwoniących (plik „nexus zmiany 1”, ten sam tekst w „uwagi do nexus
dzwonienie.docx”). Cztery decyzje Artur podjął 13.11.2026 w pytaniach (wszystkie rekomendowane):
oferta → Leady (nie szansa), zdjęcie obu wyników, filtr osoby z zapisem przez każdego,
„Przypomnienia” jako terminy powrotów. Reszta listy to oczywiste kroki.

Kod: `backend/app/services/sales/calling.py`, `calling_crm.py` (nowy), `calling_import.py`,
`calling_file.py`, `my_day.py`, `handoff.py` / `handoff_invite.py`; front
`frontend/src/components/sales/calling/` (`CallRemindersView.tsx` nowy), `MyDayReminders.tsx`.
Bez migracji.

## Co zmienia wcześniejsze decyzje

- **Kolejka nie jest już tylko osobista** (zmienia „Zawsze zalogowanej osoby” z 10.11.2026
  w `dzwonienie-kampanie-i-import-listy.md`). Nad kolejką jest wybór osoby
  (`GET /queue?caller_id=`, lista `callers`: osoby z otwartymi rekordami kampanii). Licznik
  „Dziś” zostaje osoby, która patrzy. Nadal bez celu, paska postępu i rankingu.
- **Wynik zapisuje każdy z „Sprzedaż: edycja”**, także w cudzej kolejce i na cudzej szansy
  z etapu „Lead” (zastępstwa). Telefon w dzienniku i w „Skuteczności” liczy się temu, kto
  kliknął; rekord zostaje przypisany do swojej osoby. 403 dostaje tylko konto bez edycji.
- **„Nie zainteresowany” i „Nie teraz” zdjęte** (`RETIRED_OUTCOMES`, zapis to 422). Rekordy,
  które już mają ten stan (ok. 640 z przeniesionego Excela), zostają ze swoją datą powrotu
  i wracają w swoim dniu; Tabela dalej je pokazuje i filtruje. Klawisze 1–5 (`KEYED_OUTCOMES`).
  Ryzyko, o którym Artur wie: odmowę ludzie mogą klikać jako „Nie kontaktować”, a to sprzeciw
  przy osobie w całej Sprzedaży.
- **„Oferta ogólna wysłana” pyta o ponowny kontakt**: termin albo „Bez ponownego kontaktu”
  (`never: true`, rekord bez daty nie wraca; `_due` nie bierze oferty bez daty).

## Kolejka i karta

- **„Nie odebrane” to osobna sekcja** (`no_answer`), bez względu na datę, od najdłużej
  czekającego. Nie stoi już w „Oddzwonieniach na dziś” ani w „wróci w swoim dniu”.
- Karta: adres e-mail z „Kopiuj”, „Uwagi o firmie” (notatka rekordu) pod danymi firmy,
  „Edytuj dane” (`PATCH /records/{id}`: osoba, stanowisko, telefon, adres, uwagi; zmienia też
  kontakt w kartotece). Edycja nie zapisuje telefonu w dzienniku.
- „Umówione spotkanie” z rekordu kampanii otwiera „Umów spotkanie” z polami „Zaproszenie dla
  klienta”: adres (z karty, do poprawienia) i treść. Trafiają do bloku przekazania
  (`invite_to`, `invite_message`) i wypełniają okno „Wyślij zaproszenie” prowadzącego.
  **Nic nie wychodzi samo**: wysyła dalej prowadzący, ze swojej skrzynki (decyzja 10.11.2026).

## Import

- Kolumny z Excela dzwoniących: „Nazwa firmy”, „NIP”, „Numer kontaktu”, „Adres mailowy”,
  „Imię i nazwisko”, „Stanowisko”, „LinkedIn”, „Typ usługi”, kolumna podziału („Kto dzwoni”,
  „Podział”, „Dzwoni”…), „Uwagi o firmie”.
- **Kolumna podziału** przypisuje wiersz osobie z „Sprzedaż: edycja” po imieniu albo imieniu
  i nazwisku (`caller_keys`; imię dwóch osób nikogo nie wskazuje). Pusta albo nieznana:
  osoba wybrana w oknie. Podgląd pokazuje, komu trafi każdy wiersz.
- **„Typ usługi”** idzie na początek notatki rekordu („Typ usługi: …”), bo bez migracji rekord
  nie ma pola usługi; kampania dalej niesie swoją usługę i skrypt.
- **Kolejne wczytanie dodaje tylko nowe NIP-y**: wiersz z NIP-em, którego firma ma już rekord
  w dowolnej kampanii, dostaje „Już w kampanii” (`NIP_LOADED_DETAIL`). Rekordy szans (bez
  kampanii) się nie liczą. Dotyczy też przeniesienia Excela (wspólne `apply_import`).

## Tabela i Przypomnienia

- Kolumny „Status” i „Ostatnia modyfikacja” (`modified_at` = `updated_at` rekordu) zamiast
  „Wynik” i „Powrót”; termin powrotu stoi pod statusem. Kolejność od ostatnio zmienionego.
- Filtr „Powrót od / do” (`callback_from`, `callback_to`) i strony po 200 (`offset`).
- **Zmiana statusu w wierszu** (`POST /records/{id}/state`): Nie odebrał, Oddzwonić, Oferta,
  Zły numer. To poprawka zapisu: bez telefonu w dzienniku, bez licznika „Dziś”, `attempts`
  bez zmian. Spotkanie i sprzeciw tylko z karty rozmowy (wymagają szansy i potwierdzenia).
- **„Przypomnienia”** (`GET /reminders`): rekordy „Oddzwonić” i oferty z terminem, po dniach
  (zaległe, dziś, jutro, później). „Mój dzień” ma blok „Przypomnienia na dziś” (`until=dziś`)
  z linkiem `/sales/calling?view=reminders`. Bez nowej tabeli.

## CRM

- **Oferta → Leady** (`calling_crm.offer_lead`): lead „W kontakcie”, źródło `manual`
  z `payload.origin = "calling"` (front podpisuje „Dzwonienie”), opiekun = osoba z rekordu,
  podsumowanie i `payload` z danymi rekordu. Jeden lead na rekord (`fingerprint`
  `call|<id>`), kolejna oferta go odświeża. Bez leada: szansa z etapu „Lead” (już w CRM)
  i firma, która jest klientem NEXUSA. **Szansa dalej nie powstaje z oferty.**
- **Spotkanie** z rekordu kampanii zamyka lead jako „Szanse” z `opportunity_id`, dopisuje
  osobę i pusty opis szansy z danych rekordu. Zmiana statusu z Tabeli na ofertę też zakłada lead.

## Mój dzień

- Spotkania dnia to wpisy osoby **oraz spotkania przy jej szansach** (`_meetings_between`):
  termin wpisany przez dzwoniącego albo zsynchronizowany z cudzej skrzynki nie trafiał do
  opiekuna. Widok odświeża się co 2 minuty i po powrocie do okna.
- Nie naprawione tutaj: Outlook zapisuje wspólne spotkanie tylko pod pierwszą skrzynką, która
  je zsynchronizowała (`outlook_activities.py`, `on_conflict_do_nothing`), i pomija spotkania
  bez dopasowanej firmy.

Testy: `backend/tests/test_sales_calling_list_changes.py`, zmiany w
`test_sales_calling_queue.py`, `test_sales_calling_excel_workflow.py`, `test_sales_my_day.py`,
`test_sales_handoff_invite.py`; front `sales-calling.test.tsx`, `my-day.test.tsx`.
