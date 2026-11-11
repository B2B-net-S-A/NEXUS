# Sprzedaż: mniej kliknięć — wynik rozmowy zapisuje krok, etap na pasku, krok z kafelka (decyzje Artura 11.11.2026)
<!-- indeks: wynik rozmowy zapisuje krok, outcomePreset, klawisze 1–5 w Moim dniu, klik w numer otwiera zapis, Umówione spotkanie z wiersza, BookMeetingDialog z firmą i osobą, pasek etapów StageStrip, + krok na tablicy QuickStep, Szanse domyślnie Moje, mine=0 -->

Powód: liczenie kliknięć 23 czynności w module (11.11.2026, makiety:
https://claude.ai/artifact/1MtfmCmGv6BypDp2AiVmZf). Na kopii z 10.11 handlowiec miał 217
z 227 otwartych szans bez kroku, a ręcznie wpisał w 30 dni 7 telefonów, 4 zadania i
13 notatek. Każda rozmowa ma zostawiać krok, a krok ma się dać zaplanować bez wchodzenia
w kartę.

## Wynik rozmowy to zapis rozmowy i kroku

- **Krok z podpowiedzi wyniku** (`outcomePreset` w `step.ts`) zapisuje się razem z rozmową,
  bez drugiego „Zapisz” i bez okna „Co dalej i kiedy”. Dotyczy „Mojego dnia”
  (`MyDayRowPanels.CallPanel`) i karty szansy (`OpportunityCard`, po `CallLogPanel`).
  Przycisk wyniku pokazuje pod nazwą, jaki krok zapisze. Decyzja Artura: tak, krok sam,
  bo inaczej szanse dalej wypadają bez kroku.
- **Termin idzie z wyniku**, także w „Moim dniu”: „Nie odebrał” to jutro. Wcześniej panel
  w „Moim dniu” dawał zawsze 3 dni, a karta szansy termin z podpowiedzi.
- **„Inny krok”** w „Moim dniu” przywraca wybór: wynik zaznacza, krok i termin wpisuje się
  ręcznie, zapis dopiero przyciskiem „Zapisz”. Na karcie inny krok to „Zaplanuj”.
- **Krok, który się nie zapisze po zapisanej rozmowie:** w „Moim dniu” panel się zamyka
  (rozmowa jest już w historii, drugi zapis by ją zdublował), na karcie wraca okno
  „Co dalej i kiedy”, żeby krok nie zginął.
- **Klawisze 1–5** w panelu „Mojego dnia”, jak w kolejce dzwonienia. Cyfra wpisana
  w notatkę niczego nie zapisuje.
- **Klik w numer** w wierszu „Mojego dnia” otwiera od razu panel wyniku: numer klika się
  i tak, żeby zadzwonić.
- **„Nie kontaktować”** bez zmian: pyta o potwierdzenie i nie zakłada kroku.

## „Umówione spotkanie” w wyniku rozmowy

Przycisk w panelu „Mojego dnia” otwiera „Umów spotkanie” (`BookMeetingDialog`) z firmą,
szansą i osobą z wiersza, zamiast pustego formularza z nagłówka. Sam przycisk nie zapisuje
rozmowy: spotkanie i szansę zakłada formularz, jak dotąd (`przekazanie-spotkania-i-werdykt.md`).

## Karta szansy: pasek etapów

Otwarte etapy lejka stoją jako pasek pod paskiem kroku, w przyklejonym obszarze. Klik w etap
to `/move`, ten sam co przeciągnięcie na tablicy. Wygraną i przegraną zamykają dalej
przyciski „Wygrana” / „Przegrana” w nagłówku (i lista „Etap” niżej), bo przegrana pyta
o powód. Pasek tylko dla „Sprzedaż: edycja”.

## Szanse: domyślnie „Moje”, krok z kafelka

- **Wejście na Szanse** bez `?mine=` i `?opiekun=` pokazuje szanse zalogowanej osoby, gdy
  ma „Sprzedaż: edycja”. „Każdy opiekun” zapisuje w adresie `mine=0`, żeby wybór przeżył
  odświeżenie. Podgląd bez edycji dalej widzi wszystkich.
- **„+ krok”** zamiast „brak kroku” na kafelku tablicy otwartej szansy bez kroku i bez
  zaległości: „Jutro / Za 3 dni / Za tydzień” zapisuje zadanie „Zadzwonić” przy tej szansie.
  Klik nie otwiera karty i nie zaczyna przeciągania. Inny opis kroku: karta, „Zaplanuj”.

## Bez zmian

- Brak paska postępu, celu i rankingu w „Moim dniu”; moduł podpowiada, nie blokuje.
- Powód przegranej opcjonalny; etap tylko przez `/move`; wygrana i przegrana z karty.

Testy: `frontend/src/components/sales/__tests__/my-day.test.tsx` („przyciski wiersza”),
`sales-stage-and-pipeline.test.tsx` (pasek etapów, krok po rozmowie, domyślnie „Moje”),
`sales-board-quick-step.test.tsx`.

## Druga partia (decyzje Artura 11.11.2026, drugi PR)

- **Siedem zakładek zamiast dziesięciu** (`SalesShell.tsx`): Mój dzień, Dzwonienie, Szanse,
  Oferty, Firmy, Spotkania, Leady. Kontakty to „Firmy | Osoby” w Firmach, Zadania to
  „Dziś | Wszystkie zadania” w „Moim dniu”, Podsumowanie to „Lejek | Podsumowanie” w Szansach
  (`SUB_VIEWS`, `tabOf`). Adresy `/sales/contacts`, `/sales/tasks`, `/sales/summary` zostają,
  żeby stare linki i zakładki przeglądarki dalej działały. Nowa strona Sprzedaży, która nie jest
  zakładką, dostaje rodzica w `tabOf` i widok w `SUB_VIEWS`.
- **Jedne terminy kroku** (`STEP_WHEN` w `CallLogDialogs.tsx`: jutro, 3 dni, tydzień,
  2 tygodnie, miesiąc) w oknie „Co dalej”, „Zaplanuj” w „Moim dniu”, „+ krok” na tablicy
  i „Przełóż” w Zadaniach. Nowe miejsce planowania kroku bierze terminy stąd.
- **„Przełóż” na liście Zadania** zmienia termin otwartego zadania (`PATCH` aktywności),
  zrobione zadanie go nie ma.
- **„Zaloguj rozmowę” na karcie firmy** (`CompanyCallPanel.tsx`): te same wyniki, klawisze
  i krok co w „Moim dniu” (`CallPanel` przyjmuje `CallTarget`). Osoba: kontakt firmy
  z numerem i bez sprzeciwu, do wyboru, gdy jest ich kilka. Firma z jedną otwartą szansą
  zapisuje rozmowę przy niej, w innym przypadku przy firmie. Bez osoby z numerem panel mówi,
  gdzie go dodać.
- **„Umówione spotkanie” w kolejce dzwonienia** otwiera „Umów spotkanie” z firmą, osobą
  i nazwą kampanii jako usługą, zamiast formularza szansy. Szansa powstaje u prowadzącego
  na etapie „Spotkanie kwalifikujące” ze źródłem `handoff`, jak każde przekazanie, a nie
  ze źródłem „Dzwonienie”. Skuteczność liczy spotkania z wyniku rozmowy, nie ze źródła
  szansy, więc liczby się nie zmieniają.

Testy: `sales-shell-tabs.test.tsx`, `sales-tasks-reschedule.test.tsx`,
`sales-company-call.test.tsx`, „Umówione spotkanie” w `sales-calling.test.tsx`.
