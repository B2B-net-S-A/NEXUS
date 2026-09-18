# Narzędzia rekrutera — raport z poprawek (17.09.2026)

Audyt: `docs/recruiter-tools-audit-2026-09-17.md`. Reguły dla kolejnych zmian:
CLAUDE.md, sekcja „Narzędzia rekrutera — reguły po audycie 17.09.2026”.

## Decyzje Artura

| Temat | Decyzja |
|---|---|
| Bramka „Pending” (stawka ponad budżet) | Wyłączona całkowicie; stare karty zaliczone jednorazowo |
| Head of Recruitment | Pełny parytet z rekruterem; nadpisuje cudze werdykty; w kalendarzu edytuje cudze, odwołuje/usuwa tylko własne |
| Stawka do klienta | Role zarządcze + Finanse (z członkostwem) albo właściciel/twórca rekrutacji |
| Wyszukiwarka semantyczna | Sort i chipy działają także w trybie semantycznym |
| „Kandydat utknął w etapie” | Naprawić (nie wyłączać) |
| Przypomnienia kalendarza | Wybór minut działa; wszystkie zaplanowane wydarzenia |
| Wygląd wyszukiwarki | Tokeny DS |
| Feedback po rozmowie | Widoczny w oknie wydarzenia, zakładce „Rozmowy” i na profilu kandydata |

## Co zmieniono (obszary)

1. **Pipeline i rekrutacje** — bramka „Pending” za flagą `PENDING_VERIFICATION_ENABLED=False`
   (404 tras akceptacji, odznaka „ponad budżet”, przekierowanie `/pending-verifications` → `/jobs`),
   jednorazowe zaliczenie starych kart (`pending_verification_promotion.py`, blok w `entrypoint.sh`),
   stawka do klienta tylko dla uprawnionych (`resolve_client_rate_write` + `can_write_client_rate`),
   mini-lejek liczy „Ogłoszenia”, powody odmowy serwera w toastach, ruchy zbiorcze przez
   `moveBlockedReason`, wyszukiwarka rejestru po kliencie/numerze/technologii, zakładka rekrutacji
   w `?tab=` (`lib/url-tab.ts`), 14 filtrów listy w URL, screening za członkostwem.
2. **Kandydaci** — porównanie nie wywraca się na tagach z Traffita, filtr „Ogłoszenia” przeżywa F5,
   panele Zaangażowanie/Lokalizacja nie kasują wpisanego tekstu, historia rekrutacji nie miga pustką,
   eksport dla HoR i TCM, akcje zapisu na profilu z capability `candidate.write`, blok
   „Feedback po rozmowach”.
3. **Wyszukiwarka i Talent Radar** — re-sort puli hybrydowej, limity FE = BE, błąd zamiast starych
   wyników, AbortController, porównanie ze wszystkich stron, strona poza zakresem, Radar czyści wyniki
   po zmianie kryteriów, escapowanie `%`/`_`, tokeny DS.
4. **Generator CV** — czytelne błędy kwoty AI i 422, komunikat przy zablokowanym „Generuj”, edytor
   zamykalny po błędzie zapisu i „Wczytaj aktualną wersję” po 409, reguły klienta w modalu z profilu,
   `GET /api/cv-generator/clients/{id}/rule-for-generation`, kopiowanie linku przez `lib/clipboard.ts`.
5. **Kalendarz i feedback** — `job_id` w obu formularzach (picker z `can_schedule`), feedback
   edytowalny (PATCH) i widoczny, odwołanie wydarzeń z Outlooka (`POST …/cancel`), wydarzenia
   całodniowe, działające `reminder_minutes`, edycja metadanych, link Teams z Outlooka.
6. **Dashboard i powiadomienia** — `stage_stuck_7d` (opublikowane, 7–30 dni, raz w tygodniu, nazwisko),
   wzmianki z czatu w dzwonku na żywo (zlewane odświeżenia), klik w „Moje zadania” oznacza przeczytane,
   poprawione deep-linki (notatki, Champion, integracje, raporty, `?event=`, `&msg=`), resurface
   w dobie Warszawy z savepointem, `own_unread_count`, ikony typów, klawiatura, usunięty martwy kod.

## Migracje i dane

- Brak migracji schematu.
- Jednorazowa zmiana danych: `pending_verification_promotion_2026_09_17` (blok w `entrypoint.sh`,
  paragon w `app_settings`: liczby i ID etapów). Przy `PENDING_VERIFICATION_ENABLED=true` nic nie robi.

## Nowe/zmienione endpointy

- `POST /api/calendar/events/{id}/cancel` (nowy); `DELETE` wydarzenia z Outlooka → 409.
- `GET /api/cv-generator/clients/{id}/rule-for-generation` (nowy).
- `GET /api/jobs/{id}` → `can_write_client_rate`; `GET /api/cv-generator/candidates/{id}/recruitments` → `can_schedule`.
- `GET /api/notifications` → `own_unread_count`, `on_behalf_of_name`.
- `CalendarEventResponse` → `needs_attention`, `candidate_confirmed_at`, `external_source`, `feedback_sources`, `can_remove`.
- `GET /api/pipeline/pending-verifications`, `accept-verification`, `reject-verification` → 404 przy wyłączonej bramce.

## Weryfikacja lokalna

| Bramka | Wynik |
|---|---|
| `ruff check app/`, `ruff format --check app/` | zielone |
| `tsc --noEmit`, `next lint` | 0 błędów (177 ostrzeżeń, limit 300) |
| Vitest, pełny zestaw | 3848/3861; 13 czerwonych: 2 poprawione testy HoR, 11 timeoutów pod obciążeniem — każdy plik zielony uruchomiony osobno |
| pytest, 222 pliki dotknięte zmianą | 3015 passed; 7 czerwonych poprawionych i powtórzonych (161 passed) |
| Pełny pytest backendu | tylko CI (lokalnie za wolno na obciążonej maszynie) |
| Przegląd adwersarialny | 5 × P2 i 8 × P3 — wszystkie naprawione lub rozstrzygnięte decyzją |

## Świadomie poza zakresem

- Poprawka strefy w zaproszeniach M365 (`services/m365/calendar.py:95-96`) — do sprawdzenia jednym
  prawdziwym zaproszeniem po wdrożeniu.
- „Wygeneruj ponownie” ładuje ustawienia do formularza zamiast od razu kolejkować płatną generację.
- Testy E2E dla roli HoR (stack E2E nie ma konta HoR).
- Weryfikacja UI w Chrome — po wdrożeniu.

## Nota z 18.09.2026 — flaga `PENDING_VERIFICATION_ENABLED` usunięta

Raport opisuje stan z 17.09.2026: bramka „Oczekuje" wyłączona flagą, kod
backendu zachowany. 18.09.2026 flaga i cały kod bramki (trasy akceptacji
i odrzucenia, lista oczekujących, ich schematy i komendy) zostały skasowane
— zero zmiany zachowania widocznej dla użytkownika. Jednorazowa promocja
starych wierszy `pending` (`pending_verification_promotion.py`, znacznik
`pending_verification_promotion_2026_09_17`) zostaje: jest idempotentna
i potrzebna przy świeżej instalacji oraz odtworzeniu bazy.
