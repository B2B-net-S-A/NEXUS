# Jeden formularz screeningu (0424, 07.10.2026)

Decyzje Artura D1–D10 z 07.10.2026 (makieta https://claude.ai/artifact/TNGomEmwM6ehsbdPDSaaBi). Rekruter rozmawia
na podstawie Profilu Championa i zapisuje wynik **dla Delivery Leada** — z NEXUSA nic nie idzie do klienta.
Kontrakt: `docs/screening-form-contract.md`, raport: `docs/screening-form-completion-report.md`.

- **Arkusz screeningu, ręczne pola karty rekomendacji i stawka kandydata to JEDEN formularz**
  (`api/screening_form.py`, `services/screening_form.py`, front `components/v2/screening-form/`). Zapis jest jedną
  transakcją: arkusz na NAJNOWSZY wiersz etapu pary, pola karty (`save_manual`, tylko różne od wartości efektywnej),
  stawka przez `candidate_rate_change.change_rate(source="screening")`, tekst z „Uzupełnij z notatki” jako notatka
  HUMAN. Stare trasy (`POST /pipeline/stages/{id}/screening`, `PUT /recommendation-cards`) zostają dla starych kart
  przeglądarki; ich zmiany łapie wersja `external`. Nowy ekran zapisujący arkusz albo kartę = ta trasa.
  Zapis i przywrócenie odsyłają `state_token` (odcisk stanu pary z `GET`): zmiana zrobiona obok formularza zmienia
  odcisk → 409, przeglądarka wczytuje nowy stan i zostawia niezapisane zmiany (odświeżenie w tle robi to samo,
  `keepDirtyValues`). Front wysyła tylko zmienione pola karty i `null` dla nieruszonego arkusza i stawki.
  „Cofnij” = tylko własny ostatni zapis; od „CV wysłane” podwyżka z „Cofnij” idzie do DL jak każda inna. `note_import` przy
  wyłączonym `RECOMMENDATION_CARD_ASSIST_ENABLED` = 422.
- **Historia wersji** `screening_form_versions`: każda realna zmiana = wersja z migawką i zmianami przed/po;
  „Przywróć” i „Cofnij” zapisują NOWĄ wersję. Tabela trzyma wartości (także narodowość) — czytają ją wyłącznie ludzie
  (strażnik w `test_recommendation_card_ai_privacy.py`). Przywrócenie stawki tylko przed „Zweryfikowany” — później
  zmianę stawki prowadzi Delivery Lead (0418).
- **Edycja na każdym etapie, dopóki proces trwa** (`assert_pair_editable`): tylko do odczytu przy zamkniętej
  rekrutacji albo zamkniętym/unieważnionym procesie pary. Blokada 12 h bez zmian (Nowi/Screening).
- **Panel osoby ma szerokość `split`** (`PersonPanelShell size`): kliknięcie osoby w Nowi/Screening otwiera od razu
  panel na całą szerokość okna — podgląd po LEWEJ na całą wysokość (CV oryginalne / CV firmowe / inne pliki,
  Wymagania, Po ludzku), profil przed rozmową albo formularz w stałej prawej kolumnie (460 px, od 1536 px okna
  520 px). „Zwiń” wraca do doku 380 px. Układ od 09.10.2026 — sekcja „Duży podgląd po lewej stronie panelu osoby”.
- **Pola „Warunków” i „Oceny” czyta się w widoku „Screening”** (dok, przegląd DL, profil) — od 09.10.2026 bez
  osobnej sekcji i nazwy „Karta rekomendacji” (sekcja „Jeden widok „Screening”…” niżej). Pole „Notatki
  rekrutera” (`screening_answers.notes`) zniknęło z formularza — stare wartości pokazujemy jako „Notatka z arkusza”
  z „Przenieś do Dlaczego ten kandydat”.
- **Nic do klienta (D2):** udostępnianie karty Championa usunięte — `POST …/share-token` i publiczny GET = 410,
  tokeny odwołane w 0424; `notes` zdjęte z `client_safe_screening`. Odpowiedzi nadal są źródłem treści CV firmowego.
- Wzmianki w sekcjach 0413 i 0421 o edycji karty w jej oknie, kafelkach importu notatki i `/note/apply` opisują
  stan sprzed 0424.
