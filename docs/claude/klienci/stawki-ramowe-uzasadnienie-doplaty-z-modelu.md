# Stawki ramowe: uzasadnienie dopłaty premium z modelu (F5, 0723, 16.11.2026)
<!-- indeks: „Zaproponuj uzasadnienie”, klucz AI `premium_skill_justification` (F50, Sonnet 5.5 z Haiku 5.5), szkic EN do wniosku o dopłatę za technologię, tylko fakty bez nazwiska/klienta/stawek, liczby spoza faktów = ostrzeżenie, brak modelu = szablon F4, szkic niezapisywany -->

Decyzja Artura z 16.11.2026: zrobić opcjonalny etap F5 planu „Stawki ramowe
i addony” (Nordea pierwsza, model ogólny). Delivery Lead, który prosi klienta
o dopłatę za technologię premium z umowy ramowej (wniosek z F3), dołącza
uzasadnienie po angielsku. F4 składa je z szablonu (`frontend/src/lib/premium-skills.ts`,
`justificationDraft`), F5 dokłada przycisk „Zaproponuj uzasadnienie” w oknie
„Uzasadnienie (EN)” na karcie „Umowa ramowa” kontraktu.

Kod: `backend/app/services/premium_skill_justification.py`, trasa
`POST /api/contracts/{id}/premium-skills/claims/{claim_id}/justification-draft`
w `api/framework_rates.py`, okno `JustificationDialog` w
`components/contracts/PremiumSkillsSection.tsx`.

## Zasady

- **Szkic, nie decyzja.** Model daje tekst do poprawienia; DL czyta, poprawia,
  kopiuje i wysyła sam ze swojej poczty. NEXUS szkicu nie zapisuje (brak kolumny
  i tabeli, migracja 0723 dodaje tylko klucz AI). Nie dokładaj automatycznej
  wysyłki ani zapisu „zatwierdzonego” tekstu bez decyzji Artura.
- **Wejście modelu to tylko fakty uzasadnienia:** technologia i procent dopłaty
  z cennika, kategoria i poziom, źródła dowodu NEXUSA (CV, oś czasu CV z miesiącami,
  screening, karta techniczna projektu), inne technologie z karty technicznej,
  potwierdzenie DL-a „zna i korzysta codziennie” (wniosek istnieje tylko po tej
  decyzji) i przykłady wpisane przez DL-a. Bez imienia i nazwiska (z notatki DL-a
  kod zamienia je na „the consultant”, `scrub_names`), nazwy klienta, stawki,
  limitu i treści CV. Nowe pole w prompcie = wpis w `FEATURE_DATA_SENT`.
- **Model nie dopisuje faktów.** Prompt zakazuje lat, liczb, nazw projektów
  i opisu zadań spoza przykładów. Kod sprawdza szkic: liczba, której nie ma
  w faktach (np. „5 years”), i brak nazwy technologii wracają jako ostrzeżenie
  w oknie (`warnings_for`). Szkicu z ostrzeżeniem nie odrzucamy — DL widzi, co poprawić.
- **Wynik modelu jest dodatkiem.** Brak klucza, wyłączona funkcja, limit, błąd
  dostawcy albo pusta odpowiedź = HTTP 200 z `text: null` i komunikatem po polsku;
  w oknie zostaje szablon z F4 albo tekst, który DL już poprawił. Przycisk widzi
  tylko ten, kto może prowadzić wniosek (`ContractsOrdersOrAmountsEditUser`
  + DL swojego klienta), na otwartym wniosku (`approved`, `sent`); zamknięty = 422.

## Model (pomiar 16.11.2026)

Staging, 8 kontraktów Nordei z kategorią dopuszczającą dopłatę (Scala, Hadoop,
Kafka ×3, PEGA, Snowflake ×2), dowody z bazy, przykłady DL-a fikcyjne (2 bez
przykładów, 1 z imieniem do zdjęcia), progi z odczytu Appendix 6. Wszystkie
modele na tym samym prompcie (po poprawce dodającej potwierdzenie DL-a; przed
nią Sol pisał „nie ustalono codziennego użycia”, a Sonnety dopisywały opis roli).

| model | zdania bez pokrycia / przeinaczone (8 szkiców) | słowa (mediana) | USD/wywołanie | czas (mediana) |
|---|---|---|---|---|
| **Sonnet 5.5** (wybrany) | 1 (łagodny ozdobnik) | 121 | 0,0036 | 2,0 s |
| GPT-6.1 Sol | 0, ale sztywne zdania „meta” | 105 | 0,0024 | 4,5 s |
| Haiku 5.5 (zapas) | 3 (np. „No specific project examples are cited”) | 112 | 0,0002 | 1,5 s |
| Sonnet 5 | 4 (np. „Kafka used for debugging pods”) | 132 | 0,0038 | 3,1 s |
| GPT-6 Luna | — (5 z 8 krótszych niż 90 słów) | 79 | 0,0001 | 2,1 s |

Liczby spoza faktów: 0 u wszystkich; imię w szkicu: 0. Ocena zdań — ręczna
lektura wszystkich szkiców w sesji F5. Powrót bez deployu:
`PREMIUM_SKILL_JUSTIFICATION_MODEL`. Zmiana promptu = nowy pomiar wszystkich
kandydatów na nowym prompcie.
