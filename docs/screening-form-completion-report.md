# Jeden formularz screeningu — raport (PR1, 07.10.2026)

Decyzje Artura D1–D10 z 07.10.2026, makieta: https://claude.ai/artifact/TNGomEmwM6ehsbdPDSaaBi.
Kontrakt API: `docs/screening-form-contract.md`. To pierwszy z trzech PR-ów (PR2: ekran Delivery Leada,
PR3: stawki z rekrutacji w zamówieniu i umowie).

## Dlaczego
Rekruter rozmawia z kandydatem na podstawie Profilu Championa i zapisuje wynik dla Delivery Leada — z NEXUSA nic
nie idzie do klienta. Do 07.10 te same dane wpisywało się w 2–4 miejscach: arkusz pytań, kartę rekomendacji
(10 pól) i osobne pole stawki (stawka w czterech miejscach). CV i wymagania otwierały się w oknach zamiast obok,
arkusz od „Zweryfikowany” był tylko do odczytu, a historii zmian nie było. Przycisk „Karta Championa dla klienta”
był aktywny, choć nikt z niego nie korzystał.

## Co się zmieniło

**Jeden formularz** (`components/v2/screening-form/ScreeningFullForm.tsx`, `api/screening_form.py`,
`services/screening_form.py`):
- sekcje „Pytania z Profilu Championa”, „Warunki” (jedna stawka kandydata + pola karty), „Ocena”;
- „Uzupełnij z notatki” na górze (przy włączonym asystencie) wypełnia puste pola w miejscu, przy pełnych
  proponuje „Użyj”; nic nie zapisuje się bez „Zapisz”;
- „Zapisz” / „Zapisz i przekaż dalej → Zweryfikowany” / „Odrzuć”; zapis jest jedną transakcją;
- stawka idzie przez `change_rate(source="screening")` — przed „Zweryfikowany” bez powiadomień, później jak każda
  zmiana stawki w procesie (0418).

**Historia wersji** (`screening_form_versions`, migracja 0424): każda realna zmiana to wersja ze zmianami
przed→po; „Przywróć” i „Cofnij” zapisują nową wersję. Zmiany zrobione starą drogą łapie wersja `external`.

**Edycja na każdym etapie**, dopóki proces trwa; po jego końcu formularz, karta i historia są tylko do odczytu.

**Panel osoby `split`**: kliknięcie osoby w „Nowych” i „Screeningu” otwiera szeroki panel — po lewej profil przed
rozmową albo formularz, po prawej CV (oryginalne / firmowe / inne pliki), wymagania z Championa i opis „po ludzku”.
„Zwiń” wraca do doku.

**Karta rekomendacji** jest widokiem (dok, przegląd DL, profil) z „Edytuj w screeningu”. Pole „Notatki rekrutera”
zniknęło z formularza — stare wartości są „Notatką z arkusza” z przyciskiem przeniesienia.

**Nic do klienta**: udostępnianie karty Championa usunięte (410, tokeny odwołane), `notes` zdjęte z
`client_safe_screening`.

## Sprawdzenie
- Backend lokalnie (Python 3.12, bez bazy): reguły formularza, lustro migracji, strażnicy (note_sync, prywatność AI,
  czytelnicy karty, zakres tras, sekcje), wzorzec uprawnień, przewodniki ekranów — zielone. Testy z bazą
  (`test_screening_form.py` i zaktualizowane) biegną w CI.
- Frontend: `npm run type-check`, ESLint na zmienionych plikach, vitest na katalogach jobs, screening-form, person,
  KanbanBoardV2, help, inwentarz i harnessy — 1077 testów zielonych.
- Przeglądarka (1280×720): `/preview/screening-form?state=nowi|filled|history`, `/preview/job-detail` — klik w osobę
  z „Nowych” otwiera panel `split` z profilem i CV, „Zwiń” wraca do doku.

## Po wdrożeniu
1. `python -m scripts.eval_recommendation_card_note --limit 40` w kontenerze backendu.
2. Przy dobrym wyniku `RECOMMENDATION_CARD_ASSIST_ENABLED=true` workflowem „Coolify set env”.
3. Na produkcji „Wklej tekst” z fikcyjną notatką bez zapisu.

## Znane ograniczenia
- Stare trasy (`POST /pipeline/stages/{id}/screening`, `PUT /recommendation-cards`) zostają dla starych kart
  przeglądarki; do usunięcia po sprawdzeniu w logach, że ruch jest zerowy.
- „Zacznij screening” otwiera formularz, ale nie przesuwa karty do kolumny „Screening”.
- `useScreeningForm`/`makeSchema` w `ScreeningForm.tsx` używa już tylko test podpowiedzi przepięcia — do sprzątnięcia.
