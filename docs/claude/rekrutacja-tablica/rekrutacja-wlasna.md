# Rekrutacja własna: prywatny proces poza zwykłymi rekrutacjami (09.11.2026)
<!-- indeks: `/rekrutacja-wlasna`, `/t/{token}`, `services/own_hiring`, `own_hiring_*`, filtr doświadczenia, wybór terminu z linku, 3 dni robocze, kolejka asystentki -->

Decyzje Artura z 09.11.2026 (makiety: https://claude.ai/artifact/GKxpbwxaAW7z4yXDWM9Z2U).
Proces na rekrutera IT prowadzi właściciel, a do telefonów dochodzi asystentka.

Kod: `services/own_hiring/` (filtr, terminy, serwis, przebieg pętli, DDL w `schema.py`),
`api/own_hiring.py`, `api/public_own_hiring.py`, `tasks/own_hiring.py`,
front w `components/v2/own-hiring/`, klienci `lib/api/ownHiring.ts` i `lib/api/publicBooking.ts`.

## Reguły

- **Osobny moduł, nie flaga na rekrutacji.** Rekrutacje czyta 378 zapytań w 185
  plikach, Tablica ma 8 stałych kolumn, a `bez-typow-rekrutacji.md` zakazuje typów.
  Własne tabele sprawiają, że KPI, liga, Insights i automaty nic o procesie nie wiedzą.
- **Dostęp to lista osób w procesie, bez wyjątku dla adminów** (`context_for`,
  `require_own_hiring_access`). Rola konta nie ma znaczenia: asystentka może mieć
  konto bez sekcji rekrutacji. Dlatego trasy są na liście bez sekcji i mają testy
  dostępu. Właściciela i asystentkę ustawia ekran „Ustawienia” procesu, nazwisk nie
  ma w repo. Założyć proces może admin, zostaje jego właścicielem.
- **Asystentka dostaje jawną listę pól** (`call_queue`): imię, telefon, ogłoszenie,
  próby. Bez CV, oczekiwań i notatek. Nowe pole tam to decyzja o danych osobowych.
- **Zgłoszenia czyta pętla z `candidate_source_events` po kursorze**, po tytule
  z notatki „oferta: …”. Scrapery i ich trasy zostają bez zmian. Dopasowanie po
  tytule jest świadomym wyjątkiem od `aplikacja-z-formularza-justjoin…`: scraper
  Pracuj.pl nie podaje id ogłoszenia, a lista tytułów jest ustawiana ręcznie.
- **Filtr nie odrzuca** (`candidate_filter.classify`). Rozdziela zakładki „Pasuje”,
  „Do sprawdzenia”, „Odfiltrowani”. Nieodczytane CV nigdy nie trafia do
  „Odfiltrowanych”, a automat nie wysyła odmów (art. 22 RODO, do potwierdzenia z IOD).
  Pomiar 09.11: z 1193 osób 371 rola rekrutera, 61 HR z rekrutacją, 101 wzmianka, 660 nic.
- **Link w mailu otwiera stronę, nie decyduje.** Safe Links otwiera linki przed
  człowiekiem, więc samo otwarcie niczego nie zapisuje. Token: HMAC z `SECRET_KEY`,
  80 bitów, w bazie SHA-256, ważny 45 dni, odpowiedzi z jawnej listy pól, bez danych osoby.
- **Bez odczytu kalendarza nie pokazujemy godzin** (`free_slots` zwraca `None`):
  rezerwacja mogłaby trafić na zajęty termin. Godziny liczą się przy otwarciu i
  drugi raz przy rezerwacji, a podwójną rezerwację blokuje `uq_own_hiring_active_slot`.
- **Awaria Microsoftu nie cofa rezerwacji.** `sync_to_calendar` zostawia `failed`,
  dzwonek do właściciela i ponowienia w pętli (do 6 prób).
- **Licznik to dni robocze kalendarza firmy** (`response_deadline`). Mail od kandydata
  zatrzymuje licznik (`replied_at`), link działa dalej po „Bez odpowiedzi”,
  a rezerwacja zdejmuje kartę z kolejki telefonów.
- **Mail nie zakłada płci** (bez Pan/Pani). Wychodzi ze skrzynki właściciela.
- **Umowa to na razie stan**, bez generatora i podpisu w NEXUSIE.

## Przed uruchomieniem

Właściciel musi być w grupie `NEXUS-Meetings-Scope` (zajętość i spotkania Teams idą
aplikacją „NEXUS Teams Prep”) i mieć podłączoną skrzynkę M365. Staging blokuje Microsoft,
więc pierwsza prawdziwa rezerwacja to próba na produkcji na własnym adresie.
