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
  wyłączonym `RECOMMENDATION_CARD_ASSIST_ENABLED` = 422. `note_import.note_id` (D3, 14.10.2026) wiąże zapis
  z notatką zapisaną już w doku zamiast zakładać drugą — reguły w `karta-rekomendacji-z-notatki-i-uloz-w-zdanie.md`.
- **Historia wersji** `screening_form_versions`: każda realna zmiana = wersja z migawką i zmianami przed/po;
  „Przywróć” i „Cofnij” zapisują NOWĄ wersję. Tabela trzyma wartości (także narodowość) — czytają ją wyłącznie ludzie
  (strażnik w `test_recommendation_card_ai_privacy.py`). Przywrócenie stawki tylko przed „Zweryfikowany” — później
  zmianę stawki prowadzi Delivery Lead (0418).
- **Edycja na każdym etapie, dopóki proces trwa** (`assert_pair_editable`): tylko do odczytu przy zamkniętej
  rekrutacji albo zamkniętym/unieważnionym procesie pary. Blokada 12 h bez zmian (Nowi/Screening).
- **Panel osoby ma szerokość `split`** (`PersonPanelShell size`): kliknięcie osoby w Nowi/Screening otwiera od razu
  panel na całą szerokość okna — podgląd po LEWEJ na całą wysokość (CV oryginalne / CV firmowe / inne pliki,
  Wymagania, Po ludzku), formularz w stałej prawej kolumnie (460 px, od 1536 px okna 520 px), a nad nim blok
  „Co już wiemy”. „Zwiń” wraca do doku 380 px. Układ od 09.10.2026 — sekcja „Duży podgląd po lewej stronie
  panelu osoby”.
- **Formularz od razu, także w „Nowych” (P2, 14.10.2026, `droga-rekrutera-do-dl.md`).** Bez kroku „Zacznij
  screening” i bez „Biorę — 12 h” przed formularzem: zapis, który dodał wersję, w kolumnie „Nowi”/„Screening”
  i otwartym procesie bierze wolną osobę na 12 h jak „Biorę” (`screening_form._claim_on_save`: blokada
  i `Activity("candidate_claimed")` z tymi samymi szczegółami co trasa `claim_candidate`, potem odświeżenie
  Tablic zespołu). Cudzej aktywnej blokady nie przejmuje (rekruter dostaje 423 jak dotąd, DL/admin/HoR
  zapisują bez przejęcia), własnej nie przedłuża, przywrócenie wersji nikogo nie bierze.
- **Stawka na start (D2, 14.10.2026).** Etap bez stawki: pole stawki dostaje — jako zmianę formularza, więc
  zapisuje się z „Zapisz” — najpierw najnowszą stawkę z notatek z dosłownym cytatem (`suggestions_from_notes.
  rate`, tylko PLN i znana jednostka), potem stawkę z karty (`rate_hints.card` + `card_raw`), na końcu „Stawkę
  od” (`lib/screening-form.ts` `ratePrefill`). Pod polem jedna linia „z notatki 2.04.2025: „…” · zmień” /
  „z karty rekomendacji: „…” · zmień” / „Stawka od · najniższa z 18 mies. · zmień”; podpowiedź „Użyj” z tą
  samą wartością co w polu znika. Bez prawa do stawek (`can_edit_rate`) nic się nie wpisuje; ręcznie
  ruszona stawka nie wraca po odświeżeniu; stawka z notatki z rozmowy zastępuje wpis na start. Do tej daty
  zapis porównywał pole ze stawką z karty i gubił ją — etap zostawał bez stawki (`buildSavePayload`
  porównuje teraz tylko ze stawką etapu, jak serwer).
- **Pola „Warunków” i „Oceny” czyta się w widoku „Screening”** (dok, przegląd DL, profil) — od 09.10.2026 bez
  osobnej sekcji i nazwy „Karta rekomendacji” (sekcja „Jeden widok „Screening”…” niżej). Pole „Notatki
  rekrutera” (`screening_answers.notes`) zniknęło z formularza — stare wartości pokazujemy jako „Notatka z arkusza”
  z „Przenieś do Dlaczego ten kandydat”.
- **Nic do klienta (D2):** udostępnianie karty Championa usunięte — `POST …/share-token` i publiczny GET = 410,
  tokeny odwołane w 0424; `notes` zdjęte z `client_safe_screening`. Odpowiedzi nadal są źródłem treści CV firmowego.
- **Pominięcie pytań sprawdza zapis (14.10.2026).** `PUT /screening-form` (i stara trasa arkusza)
  odrzuca `answers[*].skipped` bez powodu „Pomiń brakujące” (`screening_reassign.skip_missing_reason`)
  kodem 422 `SCREENING_FORM_INVALID`. Pominięcie zapisane wcześniej w arkuszu pary przechodzi przy
  ponownym zapisie. Powód: audyt 13.10 pokazał zapis samych `skipped` z pominięciem ekranu, który
  spełniał bramkę „Zweryfikowany”. Bramka liczy teraz tylko odpowiedzi
  (`move_requirements.sheet_answered`), szczegóły w „Rekrutacja bez pytań…”.
- Wzmianki w sekcjach 0413 i 0421 o edycji karty w jej oknie, kafelkach importu notatki i `/note/apply` opisują
  stan sprzed 0424.
