# Jeden widok „Screening” zamiast karty rekomendacji (09.10.2026)

Decyzja Artura 09.10.2026 („usuń nazwę wszędzie”). Po 0424 rekruter wypełniał jeden formularz, ale do odczytu te
same dane stały w dwóch albo trzech blokach pod różnymi nazwami (arkusz, „Karta rekomendacji”, w przeglądzie DL
jeszcze „Ocena rekrutera”). Raport: `docs/screening-one-view-completion-report.md`.

- **Nazwy „Karta rekomendacji” nie ma na ekranach**, w „Przesuń dalej”, w dzwonku zmiany stawki ani w etykiecie
  narzędzia Jarvisa. Nazwy techniczne zostają (tabela `recommendation_cards`, trasy `/api/recommendation-cards`,
  pole `card` na karcie Tablicy, akcja `open_card`, klucz plakietki `recommendation_card`,
  `lib/recommendation-card.ts`) — jak `/jobs` przy „Rekrutacjach”. Nowy napis dla człowieka mówi „screening”,
  „formularz screeningu” albo „z notatki”.
- **Jeden widok tylko do odczytu: `screening-form/ScreeningSummaryView`** (warunki → pytania → ocena) ze stanu
  `GET /api/screening-form`. Pokazują go: dok osoby (jedna sekcja „Screening”), przegląd DL (jeden blok między
  wymaganiami a ryzykami — zastąpił „Ocenę rekrutera”, kartę i zwinięty arkusz), zakończony proces i okno
  w profilu (`ScreeningSummaryDialog`, przycisk „Screening tej rekrutacji” przy notatce). Nie dokładaj drugiego
  widoku tych danych ani osobnej sekcji na pola „Warunków” i „Oceny”. Odpowiedzi nadal renderuje wyłącznie
  `ScreeningAnswersList` (pola wiersza `source` i `deal_breaker`).
- **Stan formularza niesie `questions`** (pytania scalone przez serwer: arkusz, a bez niego notatka; „Odpada,
  gdy…”, trafienie) **i `rate_text`** (stawka zapisana tekstem, gdy `rate` jest puste). Front pytań nie scala —
  `lib/screening-summary.ts` tylko układa wiersze: tekst pytania ze stempla odpowiedzi, a warunek „Odpada, gdy…”
  wyłącznie przy tym samym pytaniu co w profilu (identyfikatory pytań są pozycyjne).
- **„Brakuje N” liczy jedna reguła:** stawka na wierszu etapu to wypełnione pole
  (`recommendation_cards.with_stage_rate`, `stage_rate_pairs`) — w formularzu, na plakietce Tablicy, w kolejce DL,
  w „Przesuń dalej” i w `GET /api/recommendation-cards`. Do tej daty plakietka i „Przesuń dalej” liczyły brak
  stawki, gdy stała tylko na etapie (okno „Zweryfikowany”, „Zmień” w panelu). Para ze stawką na etapie i bez
  wiersza karty ma stan „częściowy”, nie „pusty”.
- **Plakietka na Tablicy i w kolejce DL:** „Screening: komplet” / „Screening: brakuje N” / „Screening: puste pola”
  — liczy pola warunków i oceny, nie odpowiedzi na pytania. Napis musi pasować do `/brakuje (\d+)/`
  w `compactCardBadge`.
- **„W starym formacie”** jest zwinięte w widoku i pobiera `GET /api/recommendation-cards` dopiero po rozwinięciu
  (`ScreeningLegacyText`). Okna „Otwórz całą kartę” i harnessu `/preview/recommendation-card` nie ma.
- **Widok pokazuje bieżącą próbę procesu**, jak formularz: wartości sprzed ponownego dodania osoby są podpowiedzią
  „brak — ostatnio: …”. Dok czyta stan pary (ten sam klucz co zakładka „Screening” po „Rozwiń”) i odświeża go raz,
  gdy karta zmieni wiersz etapu.
- Wzmianki w sekcjach 0413, 0421, 0424 i „Przegląd Delivery Leada v2” o sekcji albo oknie „Karta rekomendacji”,
  o „Ocenie rekrutera” w środkowej kolumnie przeglądu, o `SavedScreeningView` i o plakietce „Karta gotowa / Bez
  karty” opisują stan sprzed 09.10.2026.
