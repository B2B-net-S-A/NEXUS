# Strona kontraktu: „Co się dzieje” i 7 zakładek (wariant A, 19.11.2026)
<!-- indeks: pas „Co się dzieje” (`lib/contract-happening.ts`), 10 → 7 zakładek z aliasami starych `?tab=`, Przegląd zamiast „Szczegółów”, Historia po ludzku (`lib/contract-history.ts`), akcje rzadkie w „Więcej akcji” -->

Decyzja Artura z 19.11.2026 po makietach 18 ekranów modułu (AskUserQuestion:
strona kontraktu w wariancie A, wdrożenie etapami od strony kontraktu). Powód:
treść zakładki zaczynała się na 82 % wysokości ekranu 1280 × 720, a informacja
o końcu współpracy stała ok. 1000 px niżej, na dole „Szczegółów”.

- **Pas „Co się dzieje”** pod nagłówkiem zbiera to, co trzeba zrobić:
  zaplanowany koniec współpracy (powód, dopisek, nierozwiązana umowa B2B),
  zakończoną współpracę z nierozwiązaną umową, koniec zamówienia w 60 dni
  (z decyzją o przedłużeniu), powody „Uwaga”/„Ryzyko” z karty opieki i brak
  stawki klienta. Regułę liczy `buildContractHappening` (czysta funkcja, testy
  w `lib/__tests__/contract-happening.test.ts`); akcje mają te same bramki co
  reszta strony (`renderHappeningAction` w `app/contracts/[id]/page.tsx`).
  Nowy rodzaj sprawy dopisuj tam, a nie jako osobną kartę nad zakładkami.
- **7 zakładek:** Przegląd · Pieniądze · Dokumenty · Aneksy · Opieka
  i rozmowy · Start i sprzęt · Historia. Dawne klucze adresu zostają aliasami
  (`LEGACY_CONTRACT_DETAIL_TABS`), bo niosą je linki w bazie: `notes&note=` →
  `care` (z zachowaniem `note=`), `equipment`/`onboarding` → `start`,
  `invoices`/`rateHistory` → `money`, `timeline` → `history`, `details` →
  `overview`. Backend może dalej wysyłać stare klucze.
- **Przegląd** (dawne „Szczegóły”): pasek okresu umowy i bieżącego zamówienia
  z kreską „dziś”, fakty bez powtórek z nagłówka (kandydat, klient, typ, okresy
  są wyżej), kontakt, szczegóły administracyjne, zakończenie; po prawej
  pieniądze po ludzku, ostatnie zmiany ręczne i dokumenty. Marży między różnymi
  walutami nie liczymy (Bosch: klient w EUR, konsultant w PLN).
- **Historia** (dawny „Timeline”): `lib/contract-history.ts` — zdanie na
  zdarzenie, rodzaj do filtrów, automatyczne (bez autora, migracje,
  synchronizacje) wyszarzone, serie tej samej osoby z tego samego dnia zwinięte.
  Bez JSON-a, angielskich nazw pól i adresów e-mail jako autora.
- **Nagłówek:** „Dodaj aneks”, „Edytuj” i „Więcej akcji” (szablon, kolejny
  projekt, przepięcie, usunięcie). Karty „Premie” i „Stawka z dokumentu”:
  premie w „Pieniądzach”, stawka z dokumentu pod pasem (znika, gdy nie ma czego
  potwierdzić).
- Makiety wszystkich ekranów modułu (warianty A/B, wzorzec dalszych etapów):
  gałąź `claude/contract-module-redesign-f8f030`, katalog
  `frontend/src/components/makiety-kontrakty/`.
