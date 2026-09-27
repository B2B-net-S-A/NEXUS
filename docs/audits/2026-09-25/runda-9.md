# Audyt NEXUS — runda 9 (27.09.2026)

Baza: `5fc015405` (main po rundzie 7 + gałąź poprawek rundy 8, PR #1870). Naprawa: PR rundy 9 (gałąź `claude/audit-r9-fixes`).

## Przebieg

- **Audyt:** 20 agentów tylko do odczytu. Trzech weryfikowało poprawki rundy 8 (V1 pieniądze, V2 rekrutacja, V3 integracje). Piętnastu audytowało obszary dotąd płytko sprawdzane (N1–N15: logowanie, powiadomienia i WebSocket, generator CV v3, klienci, Talent Radar, KPI i konkursy, pliki, profil kandydata, integracje, poczta, ruch w pipeline, alerty DL, administracja, lista kandydatów, rekrutacje). Dwóch audytowało przekrojowo (X1 async i transakcje, X2 autoryzacja obiektów).
- **Znaleziska:** ok. 150, w tym 9 wysokich. Trzy były regresjami poprawek rundy 8 i naprawiłem je jeszcze w PR #1870 przed jego scaleniem:
  - nowe 422 wywracało nocny skan wygasania,
  - skaner zapisanych wyszukiwań trzymał w pamięci do 100 tys. pełnych wierszy,
  - zwolniona propozycja przydziału oznaczała prowadzącego jako automat.
- **Naprawa:** 17 agentów, każdy w osobnym worktree i we własnym obszarze. Przy scalaniu były 3 prawdziwe konflikty (`jjit/nexus_client.py`, `dl_alerts.py` eksport, stemple instrukcji zamówień) i dwie migracje z tym samym numerem (przenumerowane na 0389/0390 w jednym łańcuchu). Koordynator naprawił dodatkowo bliźniaki wskazane przez agentów poza ich obszarem.
- **Po scaleniu:** 4 przeglądy kodu (pieniądze, rekrutacja, integracje i auth, frontend) oraz pełne CI.

## Decyzje Artura

| Temat | Decyzja |
|---|---|
| Liga DL: placementy rekrutacji z nieaktywnym albo nie-DL-owym DL-em (N6-2) | Idą do głównego DL-a klienta, od razu, także w bieżącym kwartale; ta sama reguła w Insights (ranking DL, Portfele DL) |
| SSO przy synchronizacji ról z AAD (N13-2) | Jawna deaktywacja przez admina wygrywa z członkostwem w grupie AAD |
| Off-limits klienta (N4-8) | Funkcja usunięta w całości (karta klienta, przegląd, warunki umowy, API); kolumny w bazie zostają |
| Nadrabianie niezamrożonych konkursów (N6-6) | Tylko okresy kończące się ≥ 30.09.2026. Liga DL Q1 2026 i wyścig rekomendacji 07.2026 zostają niezamknięte; decyzja o nich należy do admina |

## Najważniejsze poprawki

- **CV (decyzja „nigdy nie kasujemy CV”):**
  - scalanie kandydatów kasowało starsze główne CV; teraz tylko zdejmuje „główne”;
  - usunięcie kandydata gubiło CV trzymane w bazie (BYTEA); teraz trafiają do magazynu, a klucze do `retained_candidate_files` (0390). Brak działającego magazynu = 409.
- **Transakcje:** `get_db` commitował dopiero po wysłaniu odpowiedzi i po zadaniach w tle (skutek FastAPI 0.141). Teraz commit idzie przed odpowiedzią, a błąd commitu daje 5xx zamiast 2xx. Wycofanie SAVEPOINT-u nie kasuje już flagi niezatwierdzonych zapisów.
- **Dostęp:**
  - admin i DL nie czytają już cudzych maili niepowiązanych z kandydatem;
  - klient OAuth z kontem, które później dostało rolę admina, zostaje odrzucony;
  - pytania z archiwum rozmów edytuje tylko admin albo HoR, bez przenoszenia do innego klienta;
  - „podgląd jako” nie zmienia niczego (powiadomienia, szkic umowy, dziennik pobrań z prawdziwym sprawcą).
- **Logowanie:** e-mail bez rozróżniania wielkości liter (koniec drugiego konta przy SSO); stan SSO związany z przeglądarką, a PKCE nie jedzie już w adresie; pierwsze logowanie odporne na wyścig; bcrypt poza pętlą zdarzeń.
- **Pieniądze:**
  - scalony klient nie przyjmuje zapisów zamówień;
  - kontrakt usuniętego klienta nie wraca ani przez szkic, ani przez podpis B2B;
  - „Przywróć anulowane” kończy tylko przywracane linie;
  - „Przywróć” zamówienia nie wskrzesza linii umów unieważnionych.
- **Pipeline:**
  - mail odrzucenia wychodzi ze skrzynki osoby, która odrzuca, a checkbox i serwer używają jednej reguły;
  - weto HM i przepięcia liczone z kolumny docelowej;
  - `/move` nie otwiera procesu za kolumną wejściową;
  - usunięcie z rekrutacji nie zdejmuje weta ani blokady 12 h.
- **KPI i konkursy:** klucz cache kamieni milowych bez mikrosekund (koniec liczenia CTE przy każdym wejściu i wycieku pamięci); raport mailowy przejmowany po awarii; okresy sortowane chronologicznie.
- **Powiadomienia:** maile czatu nie stoją za wyciszonymi; osoba online nie dostaje „jesteś offline”; WebSocket wysyła po commicie; drugi reset hasła tego dnia nie daje 500.
- **Pliki:** odczyt PDF w osobnym procesie z limitem pamięci (bomba PDF z formularza kariery); długie polskie nazwy plików; plik kasowany po commicie; GZip nie kompresuje ZIP-ów i obrazów.
- **Integracje:**
  - bezpiecznik masowego „exited” z Compassa (admini pomijani);
  - usunięte konto serwisowe nie wraca z bootstrapu;
  - importer Traffita bez danych osobowych w próbkach błędów;
  - sonda wygasania kluczy kont serwisowych.

## Znalezione, poza zakresem tej rundy

- Skaner zapisanych wyszukiwań nadal stronicuje przez listę z rosnącym OFFSET (R9-N14-1). Czyste wyjście to parametr keyset w `GET /api/candidates`.
- Odczyt PDF w `cv_generator_b2b/text_extractor.py` (i `legacy_v7`) bez procesu z limitem pamięci — wgrywa zalogowany rekruter, nie anonim.
- `SandboxedEnvironment` bez limitów czasu w `contract_templates.py:69` i `b2b_documents/render.py:53`.
- Nazwy plików bez przycięcia: `md_consumption.py:975`, `b2b_register_import.py:48`, `client_materials.py:246`, `client_framework_contracts.py:165`.
- `talent_radar_importer.py:606` nadpisuje `cv_extracted_data` (znikają fakty z notatek).
- `importer._record_candidate_index_intent` (faza candidates) bez savepointu.
- `MANAGER_MET_STAGES` rozpoznaje spotkanie z HM po kodzie etapu, nie po kolumnie.
- Flaga `ambiguous` przy wyborze pliku CV klienta (QC) nie jest jeszcze pokazana w UI.
- `kpi_coach_service.py:323/425` wysyła WS przed commitem.
- Scalanie klientów nie przenosi umów ramowych, aneksów, wymaganych dokumentów ani reguł CV.

## Sprawdzone i czyste

Wypłaty konkursów (kolejność nagród, remisy, zamrożenie, migawki progów); tokeny JWT i ich rozdzielenie; WebSocket (autoryzacja przy każdej ramce); IDOR tras dodanych od 20.09 (poza X2-1/X2-2); bramka zgody RODO na każdej trasie oddającej plik CV; rezerwacja wysyłki maili i ich idempotencja.
