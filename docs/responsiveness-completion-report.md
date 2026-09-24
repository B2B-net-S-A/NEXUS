# Responsywność NEXUS — raport wdrożenia (23.09.2026, PR #1749)

Audyt: `docs/responsiveness-audit-2026-09-23/` (README + 10 raportów).
Poprawki per obszar: `docs/responsiveness-audit-2026-09-23/fixes/W0…W7-*.md`. Każdy plik ma tabelę ustalenie · stan · plik:linia.

Decyzje Artura z 23.09:
- tabele przewijane z przyklejoną 1. kolumną, bez widoków kart;
- tekst 11 px tylko na dotyku (9 i 9,5 px wszędzie do 10 px);
- kalendarz poniżej `md` w widoku jednego dnia.

## Część · stan · dowód

| Część | Stan | Dowód |
|---|---|---|
| Reguły wspólne (`globals.css`): pola 16 px i tekst 11 px na dotyku, `hit-area`, 9 px → 10 px | zrobione | `globals.css`, blok „RESPONSYWNOŚĆ”; strażnik `responsive-guards.test.ts` |
| W0 shell + DS + prymitywy (`h-dvh`, topbar 375 px, dzwonek, szuflada na Sheet, dialog/popover/⌘K, przyciski 40 px na dotyku, pasek boczny od 1280 px) | zrobione | `fixes/W0-fundamenty.md`; `useSidebarPinned.test`, `button.test` |
| W1 Kandydaci (szerokość wiersza tabeli, jedna oś przewijania, pliki kandydata, paski zaznaczenia, szyna od `2xl`, DOCX na szerokość) | zrobione | `fixes/W1-kandydaci.md`; `candidate-table-columns.test` |
| W2 Rekrutacje (panel „Do przejrzenia”, dok tablicy na tablecie, podgląd listy, oceny feedbacku, tabela targu) | zrobione | `fixes/W2-rekrutacje.md` |
| W3 Klienci i zamówienia (pasek akcji kafelka, skrzynka zamówień, tabele z przyklejoną kolumną, okna z przewijaniem, kafle kwot) | zrobione (okna z `max-h` + przewijaniem zamiast migracji na `AppModal`) | `fixes/W3-klienci-zamowienia.md` |
| W4 Kontrakty i generatory (tabele dokumentów/faktur, generator B2B, X nad „Pobierz”, `@media` CV, ramka CV mierzona na resize) | zrobione | `fixes/W4-kontrakty-generatory.md`; `test_cv_html_mobile_layout.py`, `cv-frame.test.ts` |
| W5 Pulpit / Insights / Finanse (container queries w kafelkach, „Edytuj układ”, menu kafelka na dotyku, paski okresów, edycja komórki stuknięciem) | zrobione | `fixes/W5-pulpit-insights-finanse.md`; `EditableCell.test` |
| W6 Ustawienia / Kalendarz / Pomoc (widok dnia, szablony maili lista/edytor, UserModal, tabele Pomocy, cv-rules) | zrobione | `fixes/W6-ustawienia-kalendarz-pomoc.md`; `WeekCalendar.test` (+3) |
| W7 Strony publiczne (`/apply`, logowanie, kariera, share, `loading.tsx`) | zrobione | `fixes/W7-publiczne.md`; `ApplyForm.test` (+2) |
| Zabezpieczenie przed regresją | zrobione | `e2e/responsive-preview.spec.ts` (45 harnessów × 360/390/768/1024/1280, projekt `preview-chromium`), sekcja w `CLAUDE.md` |
| Type-check / lint | zielone | `tsc --noEmit` 0 błędów po merge z mainem; eslint zmienionych plików: 0 błędów |
| Vitest | zielone lokalnie w próbkach | 53 pliki padnięte w pełnym biegu przy obciążeniu ~440 przechodzą pojedynczo (796/796), pliki z konfliktów 117/117; pełny zestaw uruchamia kolejka merge'ów |
| Pomiar poziomego scrolla na produkcji | niepotwierdzone | lokalny build pominięty (zasada: bez `build` przy równoległych sesjach); wynik da nocny `preview-chromium` po deployu |
| Przeklikanie produkcji 390/768 px | niepotwierdzone | po deployu (`/api/health` → SHA z maina) |

## Świadome odstępstwa

- **Okna w zamówieniach (`ModalShell`, okna w Materiałach, umowy ramowe):** dostały `max-h` i przewijane wnętrze zamiast pełnej migracji na `AppModal`, bo migracja to większa zmiana z ryzykiem dla testów.
- **Boczny panel kalendarza** chowa się dopiero poniżej `xl`, nie `lg`: z paskiem bocznym przy `lg` każdy dzień miałby ok. 60 px.
- **Pasek faktów kandydata i „Zamówienia PDF”** zostały na mainie przepisane równolegle (#1738 i `auto-fit` w pasku faktów). Wzięto wersję z maina; na PDF-ach nałożone są tylko `max-h` list i `dvh` podglądu.
- **Kilka ekranów wciąż ma własne, lokalne toasty** (`CandidatesListV2`, `ClientsListV2`, `HelpPageV2`, `ContractsListV2`, `ClientContractRegister`). To P2 na później.

## Znalezione poza zakresem

- **Publiczne `/cv/{token}` i `/cv/i/{token}` trafiają do klienta bez stylów.** `sanitize_cv_html` wycina `<style>`. To nie responsywność, wymaga osobnej decyzji.
- Tooltipy (`ui/tooltip`) nie otwierają się stuknięciem. Treść kluczowa została przeniesiona obok (podpisy, „Pokaż wartości”), ale sam prymityw jest bez zmian.
