# Profil Championa v4.0

Zatwierdzony pusty formularz: `backend/app/assets/champion/Profil_Championa_v4.0.docx`.
Pliki w `backend/tests/fixtures/champion/` zawierają wyłącznie syntetyczne przykłady.

## Kontrakt

- `GET /api/champion/template` pobiera pusty Word po uwierzytelnieniu.
- `POST /api/champion/preview` przyjmuje multipart `file`, zwraca profil, listy umiejętności, podsumowanie i walidację. Stary endpoint `/api/talent-radar/parse-champion` deleguje do tej samej usługi.
- `POST /api/champion/validate` sprawdza edytowany podgląd; nie zapisuje rekrutacji.
- `GET /api/jobs/{id}/champion-profile` zwraca także `validation`, `fingerprint` i odpowiadające profilowi `job_values`.
- `POST /api/jobs/{id}/champion-profile/apply-import`: `profile`, `expected_fingerprint`, `sync_fields`. Zmienia tylko wybrane rubryki; niepuste MUST/NICE w rekrutacji wymagają jawnego uzgodnienia. Wiersz rekrutacji jest blokowany na czas porównania i zapisu. Nieaktualny podgląd zwraca 409 wraz z aktualnym porównaniem.

`validation.issues` zawiera kod, ścieżkę pola, komunikat, poziom, fragment źródłowy oraz blokowane operacje (`search`, `handoff`, `cv`). Szkic można zapisać. Uruchomienie zablokowanej operacji zwraca 422 z tym samym wynikiem walidacji. Sam brak budżetu nie blokuje dopasowanego CV.

Wersja reguł (`intake.policy_version=1`), wersja dokumentu (`intake.template_version=4.0`) i wersja parsera (`_parser`) są niezależne. Nierozstrzygnięte wpisy pozostają w `intake.unresolved`, a nie w polach liczbowych. Pola autora i czasu nadaje serwer. Weryfikacja, briefing i historia wyszukiwań mają osobne ścieżki zapisu.

## Stopniowe objęcie profilów regułami

Nowy profil, świadomy import lub zmiana treści przyjmuje nowe zasady. Sam odczyt, niezmieniony zapis i zmiana metadanych workflow nie przyjmują nowych zasad. Dla profilu historycznego nowe problemy są ostrzeżeniami; dotychczasowe blokady pozostają. Nie ma migracji ani masowego przepisywania JSONB.

Walidacja jest wyliczana z bieżącej treści i pól rekrutacji. Zmiany wymagań korzystają z istniejącej invalidacji kontraktu, wyników i embeddingu. Alternatywa w jednej pozycji, np. „Kafka lub RabbitMQ”, pozostaje jedną grupą OR; nieznane doświadczenie kandydata nadal domyślnie trafia do weryfikacji.

## Odbiór i utrzymanie

Testy jednostkowe: `test_champion_intake_v4.py`, istniejące testy parsera, kontekstu CV i kontraktu wymagań. Testy PostgreSQL w CI: `test_champion_intake_api.py` sprawdza zapis szkicu, atomowość, konflikt 409 i bezpośrednią blokadę API. Testy interfejsu obejmują podgląd, zachowanie istniejących wartości i ponowne porównanie po konflikcie.

Odbiór produkcyjny obejmuje pobranie Worda, stateless import prawidłowego i błędnego dokumentu, poprawianie podglądu oraz uzupełnienie Radaru. Trwałe syntetyczne zapisy i generacje należy wykonywać w środowisku testowym. Nie uruchamiać integracji wyłączonych w konfiguracji.

Monitorować `champion_validation_blocked` (operacja i kody problemów) oraz `champion_import_conflict` (ID rekrutacji). Nie logować treści profilu. W przypadku regresji odwrócić zmianę zwykłym PR-em i przejść istniejącą ścieżkę CI Gate → Deploy → Coolify; brak migracji danych pozwala wrócić do poprzedniej wersji aplikacji.
