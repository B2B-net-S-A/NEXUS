# AI Search — notatki Traffita, trafność, propozycje (06–07.10.2026)

Audyt AI Search (06.10.2026, tylko odczyt produkcji) i plan pięciu PR-ów
zatwierdzony przez Artura 07.10.2026. Ten plik zbiera, co weszło, czym to
zmierzono i co świadomie zostało.

## Wdrożone

| Część | PR | Stan na produkcji | Dowód |
|---|---|---|---|
| Trafność wyszukiwania AI (bramka `critical-v10`) | #2057 | wdrożone (6406fe688) | pomiar niżej |
| Odpowiedzi z notatek do arkuszy screeningu (`note_sync`) | #2059, #2065, #2070, #2072 | wdrożone; 2 619 arkuszy zapisane; `SCREENING_NOTE_SYNC_ENABLED=true` od następnego deployu po 07.10 07:17 | paragon `screening_note_backfill_2026_10` |
| Wpis DL-a „X/Y” i fakty z notatek do pustych pól | #2062 | wdrożone; 2 676 stawek do klienta, 7 818 kandydatów z faktami | paragony `client_rate_notes_backfill_2026_10`, `notes_profile_fill_backfill_2026_10` |
| Propozycje z bazy bez limitu, `expired`, „dodane” tylko z człowieka | #2058 | wdrożone; korekta `added` z integracji: 0 par | paragon `proposal_added_from_integration_2026_10` |
| Warstwa „wcześniejsze rozmowy” (`prior_screening`) | #2063 | w kodzie, wyłącznik OFF | etap 0 pomiaru: no-go |

Każdy zapis danych szedł drogą próba → przegląd → zapis z `expected`; dane do
odwrócenia leżą pod kluczami `repair_details_*` w `app_settings`.

## Pomiar po #2057 (produkcja, tylko odczyt)

- Umiejętności krytyczne ukrywają **0,75%** par zweryfikowanych i **0,76%**
  wysłanych do klienta (11 838 / 9 665 par z 18 miesięcy). Stara reguła
  podpowiedzi na tym samym kodzie: 1,91% / 1,84%; audyt przed zmianami: 7,1%.
- Symulacja listy (150 rekrutacji, pula 3 000 + wysłani), produkcja przed →
  po: R@20 0,470 → 0,470, **R@100 0,751 → 0,772**, widoczni trafni
  **94,5% → 97,2%**, MRR 0,546 → 0,542. Cel R@20 +1 pp nie został
  osiągnięty — zysk jest głębiej na liście.

## Przegląd prób przed zapisem arkuszy (klient widzi arkusz z notatki)

- Przypięcia po treści pytania: próbki 30/30 i 10/10 poprawne.
- Ostatnia odpowiedź karty połykała sekcje wewnętrzne notatki (notatka,
  red flags, kosztorys ze stawką do klienta, @wzmianki, kolejne pytania) —
  ok. 60 z 8 245 odpowiedzi → `client_safe_response` (#2065).
- Przypięcia po numerze myliły pytania (inne pytanie jako odpowiedź, kawałek
  pytania na początku) → najpierw strażnik (#2070), potem wyłączenie zapisu po
  numerze (#2072, 215 z 8 100 odpowiedzi mniej).

## Świadomie poza zakresem / do decyzji

- **`prior_screening` zostaje OFF.** Etap 0 po zapisie arkuszy: z 1 752
  wysłanych par 364 mają jakąkolwiek wcześniejszą odpowiedź, ale tylko 10
  (0,57%) — na pytanie dopasowane do pytań tej rekrutacji (próg 5%).
  Rekrutacje zadają różne pytania; warstwa nie ma czego czytać.
- Etap 1b planu (odpowiedzi z notatek spoza kart, ok. 400 par) — niezrobiony.
- 485 notatek rodzaju `human` z „X/Y” nie jest zakrytych dla rekrutera
  (stan sprzed zmian) — do przeklasyfikowania na `dl_rate` osobnym PR-em.
- Stara notatka „od zaraz” daje datę dostępności z dnia tej notatki (bez
  progu czasowego, decyzja Artura) — profil pokazuje „stan na”, lista nie.
