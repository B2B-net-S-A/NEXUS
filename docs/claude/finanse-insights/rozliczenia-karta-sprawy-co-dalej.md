# Rozliczenia: karta sprawy „Co dalej” i lista spraw — NEXUS przygotowuje, człowiek wysyła
<!-- indeks: karta sprawy, co dalej, lista spraw, Sprawy w Rozliczeniach, kto działa, gotowy mail, telefon, skrypt rozmowy, terminy, dzień 0, przypomnienie +3, telefon +5, eskalacja +7, DL/KAM, Wyślij, Zadzwoniłem, client_settlement_case, settlement_cases, nic nie wychodzi samo -->

Próby na kopiach produkcji 25.11.2026 (bez Nordei): automat przyjmuje sam 208 z 239
rozliczeń w IX–X i 208 z 258 w VI–VIII. Reszta to głównie wady, które poprawia ktoś
poza Finansami. Cel Artura: ręcznie tylko pojedyncze przypadki, a każdy przypadek bez
automatu ma gotowe „co dalej”: do kogo, jakim kanałem, z jaką treścią i z terminami.
Makieta zaakceptowana 25.11.2026: https://claude.ai/artifact/JSGctBxtYquU6P6o9ArSrR.

Kod: `backend/app/services/client_settlements/cases.py`, trasy
`/api/finance/settlements/cases` (`app/api/settlement_cases.py`), front
`CaseNextSteps.tsx` (sekcja na karcie osoby) i `CasesView.tsx` (zakładka „Sprawy”).

## Sprawa i kto działa

- **Sprawa = rozliczenie (kontrakt × miesiąc) × kto działa.** Rozliczenie może mieć
  kilka spraw naraz (np. konsultant i Delivery Lead). „Bez uwag” i „Przyjęte” nie
  mają spraw.
- **Konsultant i akceptujący u klienta:** wady z katalogu informacji zwrotnej
  (`feedback.CATALOG`, `rozliczenia-informacja-zwrotna-o-wadach.md`). Adresat i treść
  z `feedback.target_for` i `compose_mail`, liczone tak, jakby wysyłka poza firmę była
  włączona. Wpis „wysłałbym” w `sends` przy `external=off` to dzwonek opiekuna, a nie
  mail do konsultanta, więc karta nie bierze treści z dziennika. Tekstów wad nie
  piszemy drugi raz: nowa wada = wpis w katalogu, karta pokaże ją sama.
- **Delivery Lead:** ponad pulę, zamówienie zakończone w NEXUS-ie, stawka linii inna niż
  kontrakt albo faktura, linia bez stawki MD, brak linii w miesiącu — jak karty
  `dl_alerts_scanner`. Mail do DL-a klienta **bez kwot** (tytuł uwagi „Stawka linii”
  je niesie, więc powód składa się z rozjazdu). Kwota inna niż w protokole klienta
  (`amount.protocol`) idzie do opiekuna (`reminders.pick_owner`).
- **Finanse:** reszta uwag `warn`/`fail` i nieodczytany plik („Czeka na liczbę MD”).
  Bez maila i telefonu; decyzja na karcie (przyjmij z uwagami albo do poprawy).
- **Klient z raportem T4T (Nordea):** nieodczytany plik konsultanta nie jest sprawą,
  bo MD przyjdą z raportu klienta. Na klonie próby za październik to było 14 z 23
  spraw Finansów.

## Telefon i skrypt

- Konsultant: `contracts.candidate_phone`, potem kartoteka (`contract_candidate_contact`).
- Akceptujący: kontakt klienta (`contacts`) po adresie z prośby o akceptację, potem PM
  z kontraktu (`client_pm_contact_id`); konsultant zawsze jako drugi numer.
- Delivery Lead i opiekun: `employee_profiles.phone`.
- Brak numeru to na ekranie wprost „brak numeru”, nigdy puste pole.
- Skrypt: 2–4 zdania (kto dzwoni i w jakiej sprawie, co jest źle, co zrobić, kiedy
  poszedł mail). Bez kwot.

## Terminy

Dni robocze kalendarza firmy, od dnia 0: wpływ ostatniego raportu (`report_document_id`),
przy sprawie DL-a dzień pierwszej karty DL tego epizodu. Mail od razu, +3 przypomnienie,
+5 telefon, +7 eskalacja do opiekuna (DL/KAM). Finanse: jeden krok, decyzja w 3 dni
robocze.

- Krok zrobiony później przesuwa następne o tę samą liczbę dni, liczone od
  najpóźniejszego z poprzednich kroków (telefon przed przypomnieniem nie przyspiesza
  eskalacji). Gdy bieżący krok jest zaległy, następne liczą się od dziś.
- „Teraz” = pierwszy niezrobiony krok; zaległość w dniach roboczych od jego terminu.
- Karta DL z automatu zalicza krok „Mail” swoją datą.
- **Nowy raport zaczyna sprawę od nowa** (ślad sprzed dnia 0 się nie liczy).

## Nic nie wychodzi samo (decyzje Artura z 25.11.2026)

- „Wyślij” wysyła przygotowany mail **dopiero po potwierdzeniu w oknie** (adresat, kopia,
  temat). Treść i adresat liczą się na serwerze od nowa; front ich nie wysyła.
- Nadawca: ten sam co informacja zwrotna przy `external=all` (`portal_mail.default_mailer`,
  skrzynka wsparcia, `HR_M365_MODE`), „Odpowiedz do” = adres rozliczeń, żeby poprawka
  wróciła do poczty, którą NEXUS czyta. Brak nadawcy = 409 z prośbą o wysyłkę z Outlooka.
- **Wysyła mimo panelu konsultanta „Tylko zespół”** (decyzja Artura z 25.11.2026): to
  wysyłka człowieka, nie automatu. Ustawienia informacji zwrotnej (`mode`, `external`)
  tych tras nie dotyczą i karta ich nie zmienia; automat zostaje na sucho.
- Jeden mail dziennie do tej samej osoby (409 przy drugim kliknięciu); eskalacja do
  opiekuna liczy się osobno.
- „Zadzwoniłem” zapisuje wynik (rozmowa, nie odebrał(a), zły numer) i notatkę.
- Ślad: `hr_audit_events` (`entity_type = client_settlement_case`, `entity_id` =
  rozliczenie), z osobą i datą. Ręczny mail przy wadzie z katalogu dopisuje też wpis
  `mode: manual` w `client_settlement_feedback.sends` i ustawia `last_sent_on`, żeby
  automat po włączeniu nie wysłał tego samego drugi raz tego dnia i liczył dalej
  przypomnienia.

## Kto widzi

Moduł Finanse (`FinanceModuleUser`) i sekcja Finanse, jak całe Rozliczenia (decyzja
Artura z 25.11.2026). Rola Back office (`orders_work`) nie ma Rozliczeń i nie dostaje
spraw bez osobnej decyzji. Wyłączony moduł `client_settlements` = 404 (admin widzi).
Bez prawa zapisu (podgląd jako) karta nie ma „Wyślij” ani „Zadzwoniłem”.

## Czego karta nie robi

- Brak RCP (rozliczenia jeszcze nie ma) to dalej przypomnienia 3., 5. i 7. dnia
  roboczego (`rozliczenia-przypomnienia-o-raporcie.md`).
- Nie wysyła niczego sama i nie włącza informacji zwrotnej.
- Nie zmienia wykrywania wad (`feedback.py`) ani silnika rozliczeń.
