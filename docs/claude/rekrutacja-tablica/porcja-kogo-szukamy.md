# Porcja dnia: profil „Kogo szukamy”, lista „Nie proponujemy” i bogatsze „Inna rola”
<!-- indeks: `job_role_profiles` (0728), `services/job_role_profile.py`, `job_role_profile_schema.py`, `GET`/`PUT /api/review-batch/jobs/{job_id}/profile`, `job_profiles` w `/me/queue`, `keep_role_allowed` w `_allowed`, `EXCLUDE_MIN` = 3, `detail.person_role`, `role_kind` (technology / lead_not_ic / ic_not_lead / past_role / side_role / domain), `ROLE_KIND_CHOICES`, `rememberLine`, `RoleProfileBlock`, „Popraw” -->

Decyzja Artura z 16.11.2026 („rób wszystko teraz”, propozycje 1 i 3 z raportu
o odrzuceniach „Inna rola”). Pomiar na 1 948 decyzjach porcji z produkcji
(15.10–16.11): „Inna rola” to 28% odrzuceń z 16.11 (68), a szczegół
(`detail.role_kind`) kliknięto przy 15 z 68. 37% decyzji jest w rekrutacjach,
których tytułu `role_family.family_of` nie rozpoznaje, więc filtr roli nic tam
nie robi. Tytuł osoby nie rozstrzyga: w jednej rekrutacji „Test Automation
Engineer” ta sama rola dostała 5× „Pasuje” i 1× „Inna rola”, bo rekruter
odrzuca za specjalizację, technologię albo poziom. Reguły z samych tytułów
sprawdzone na tych danych: +0,5 pkt, więc nie dokładaj reguł regex z tytułów.

## Profil „Kogo szukamy”

- **Pola:** rola, specjalizacja (opcjonalnie), główna technologia (opcjonalnie),
  poziom `wykonawca` / `lider` / `dowolny` i lista „Nie proponujemy”. Tabela
  `job_role_profiles` (migracja 0728, lustro w `entrypoint.sh` z
  `job_role_profile_schema.py`, sonda w `/api/health/deep`).
- **Bez zapisu profil się liczy:** rola z tytułu (`family_of` → `LABELS`) albo
  pusta, poziom „lider”, gdy tytuł ma lead/head/manager/kierownik/architect,
  inaczej „dowolny”, technologia = pierwsza krytyczna z profilu Championa
  (`stored_critical`). Zapisany wiersz wygrywa w całości.
- **Rola, specjalizacja, technologia i poziom niczego nie filtrują.** To
  podpowiedź na ekranie i w „Szukamy:”. Filtruje tylko lista.
- **API:** `GET`/`PUT /api/review-batch/jobs/{job_id}/profile`. Zapis: rekruter
  przypisany do rekrutacji (`recruiter_ids_for_jobs`, jak „Dodaj kolejnych”),
  Delivery Lead w swoim zakresie, Head of Recruitment, admin
  (`user_can_staff_job`); reszta 403. `GET /api/review-batch/me/queue` niesie
  `job_profiles` (klucz = id rekrutacji jako tekst).

## „Nie proponujemy”

- **Wpis ręczny** („Popraw” → „Dodaj”) działa od następnego dokładania kart.
- **Z odrzuceń:** „Osoba to: X” przy „Inna rola” (`autofill_feedback.detail.person_role`)
  liczy się per rekrutacja; od `EXCLUDE_MIN` = 3 takich samych (bez wielkości
  liter i nadmiarowych spacji) etykieta wchodzi na listę ze źródłem „z odrzuceń”.
- **Bezpiecznik:** etykieta z odrzuceń nie wchodzi na listę, gdy w tej
  rekrutacji osoba z takim stanowiskiem przeszła dalej niż „Nowi”
  (`_accepted_positions`); zostaje w „Uczy się” z `accepted: true`. Ten sam tytuł
  bywa przyjmowany i odrzucany (Nordea 509921: „Test Automation Engineer”
  5 × Pasuje i 1 × Inna rola). Wpis ręczny działa zawsze.
- **Zdjęcie z listy** etykiety z odrzuceń zapisuje ją w `dismissed`: dalej się
  liczy, ale nie filtruje, dopóki ktoś jej nie doda z powrotem.
- **Filtr:** `new_column_autofill._allowed` → `keep_role_allowed`, obok
  `keep_passing` (reguła z braków). Osoba, której obecne stanowisko
  (`role_family.current_position`) zawiera etykietę z listy całymi słowami
  (casefold), nie jest dokładana do „Nowych” tej rekrutacji: poranna porcja,
  „Dodaj kolejnych”, dopełnianie. Karty, które już czekają, zdejmuje osobny
  mechanizm w `review_batch`, nie ten filtr.

## „Inna rola” w oknie odrzucenia (klawisz 7)

- **„Co nie gra z rolą?”, klawisze 1–8 po wybraniu 7:** Inny zawód, Inna
  specjalizacja, Inna technologia w tej roli, Lider zamiast wykonawcy, Wykonawca
  zamiast lidera, Robił to dawno, teraz co innego, Rola poboczna w CV, Inna
  branża / domena. Wybór jest opcjonalny, Enter dalej odrzuca; Backspace wraca do
  wyboru powodu (9 i 0 dalej wybierają powód).
- **„Osoba to:”** ma podpowiedź = obecne stanowisko osoby, do poprawy, i idzie jako
  `person_role`. **„Szukamy:”** ma podpowiedź = rola z profilu (`role_wanted`).
  Linia „Silnik zapamięta: …” mówi, który to raz w tej rekrutacji i że od 3. silnik
  przestaje proponować takie osoby (`rememberLine`).
- **`clean_detail`:** `person_role` tylko przy „Inna rola”; nowe `role_kind`:
  `technology`, `lead_not_ic`, `ic_not_lead`, `past_role`, `side_role`, `domain`.
  Stare `profession`, `level`, `specialty` zostają ważne; `level` nie ma już na
  ekranie.

## Ekran

- Nad kartą w `JobContext` blok „Kogo szukamy: … · Nie proponujemy: … · Popraw”.
  „Popraw” otwiera okno (Dialog, bez natywnego `confirm`, błąd przez `apiErrorMessage`).
- **1280 × 720:** po pierwszej karcie danej rekrutacji blok zwija się do jednej
  linii (pełny tekst w dymku), żeby nie zepchnąć „Pasuje” pod krawędź.

Testy: `backend/tests/test_job_role_profile.py`, `test_autofill_feedback.py`
(`test_detail_keys_follow_the_reason`),
`frontend/src/components/v2/review-batch/__tests__/ReviewBatchRoleProfile.test.tsx`,
`ReviewBatchCard.test.tsx` („szczegół powodu (runda 5)”, `rememberLine`).
