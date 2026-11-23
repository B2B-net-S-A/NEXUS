# Łańcuch umów po przeglądzie skrzynki umowy@ (23.11.2026)
<!-- indeks: aneks stawki → „stawka od dnia” → Rozliczenia, „Start przed podpisem”, „Próg stawki sprzed startu”, `date_warnings`, powód „Przejście do klienta”, klienci z 12 miesięcy przy zwolnieniu z zakazu konkurencji, oświadczenie o rezydencji (WHT) bez kodu -->

Przegląd skrzynki Delivery Leada z grupy umowy@ z 23.11.2026: cały łańcuch
umów szedł mailem, choć NEXUS ma Generator, aneksy, porozumienia i e-podpis.
Ta reguła mówi, co już było, czego brakowało i co zostało decyzją Artura.

## Aneks ze stawką → „stawka od dnia” → Rozliczenia

Większość łańcucha już działała. Nie dokładaj drugiej drogi:

- **Krok harmonogramu powstaje w `apply_contract_amendment`**
  (`api/contracts.py`): okno „Dodaj aneks → Zmiana stawki”, „Oznacz jako
  podpisany” aneksu stawki z Generatora (`b2b_documents/effects.py`) i wpis
  stawki z pliku w Dokumentach kontraktu (F52, `contract_rate_documents`,
  `stawki-z-dokumentow-kontraktu.md`) dopisują krok
  `contract_candidate_rates.effective_from`.
- **Rozliczenia czytają ten krok wprost** (`client_settlements/service.py`,
  `_rate_change_checks`): zmiana w trakcie miesiąca daje uwagę „Zmiana stawki
  DD.MM: stara → nowa”. Zamówienia okresowe dostają koszt w częściach
  (`order_cost_steps`), a zmianę kolumny stawki widać w Finanse → Zmiany
  w zamówieniach.
- **Aneks z Generatora nie zmienia kontraktu przy wygenerowaniu**, tylko przy
  podpisie (`rejestr-aneksow-i-aneks-w-kontrakcie.md`): krok przed podpisem
  liczyłby się w `order_facts`, analityce i Finansach jako obowiązujący.
  „Od razu” znaczy więc „od podpisu”, nie „od pobrania DOCX”.
- **Aneks z Worda wgrany do Dokumentów kontraktu** czyta F52. Krok zapisuje
  człowiek („Wprowadź do harmonogramu”) albo automat za
  `CONTRACT_RATE_DOCS_AUTO_APPLY` (włącza Artur).
- **Brakujące ogniwo: sygnał do Finansów** o nowym kroku stawki konsultanta
  z aneksu. Rozliczenia widziały zmianę dopiero przy przeliczeniu miesiąca.
  Dzwonek wymaga nowej wartości enuma powiadomień, więc idzie osobnym PR-em
  z migracją (pas migracji).

## Ostrzeżenia dat na kontrakcie

`services/contract_date_warnings.py`, pole `date_warnings` w
`GET /api/contracts/{id}`, pozycja `dates` w pasie „Co się dzieje”
(`lib/contract-happening.ts`). Same daty, bez kwot, więc widzi je każdy, kto
widzi kontrakt. **Informacja, nigdy blokada zapisu.**

- **„Start przed podpisem”**: najwcześniejszy `signed_on` (dzień podpisu
  konsultanta z PDF-u, e-podpisu albo wpisany przy podpisie odręcznym, 0654)
  umowy tego kontraktu podpisanej obustronnie jest późniejszy niż
  `contracts.start_date`. Nowa umowa z masowej wysyłki (E5b) się nie liczy, bo
  dostaje datę rozpoczęcia z poprzedniej umowy. W skrzynce: umowa podpisana
  8 dni po starcie.
- **„Próg stawki sprzed startu”**: w harmonogramie stawki konsultanta co
  najmniej dwa kroki obowiązują już w dniu startu (`effective_from` ≤ start).
  Wcześniejszy nigdy nie działa, bo resolver bierze najpóźniejszy krok ≤ dzień,
  więc to zwykle pomyłka w roku. Jeden krok sprzed startu (stawka od 1. dnia
  miesiąca) jest w porządku. Remis w dniu startu to aneks na start, nie błąd
  daty.
- „Data na dokumencie ≠ dzień podpisu” (3 przypadki w skrzynce) nie ma
  osobnego ostrzeżenia: od 0654 premia 200% i „Placementy” liczą dzień podpisu
  konsultanta, a nie datę wpisaną w umowie (`data-podpisu-z-podpisu-konsultanta.md`).
- Testy: `tests/test_contract_date_warnings.py`,
  `lib/__tests__/contract-happening.test.ts`. Spis: `k.date-warnings`.

## Konsultant przechodzi do klienta

- **Powód już jest**: „Przejście do klienta” (`poached_by_client`) w oknie
  „Zakończ współpracę”. Ustawia zakaz konkurencji na „zdejmujemy” dla klienta
  kontraktu, w Generatorze mapuje się na `internalization`, a analityka odejść
  liczy go osobno. Nie dokładaj drugiej wartości „przejęty przez klienta”:
  rozjechałaby analitykę i mapowanie do Generatora. Fee za przejęcie to
  osobna decyzja handlowa, NEXUS go nie liczy.
- **Klienci tej osoby z 12 miesięcy** (`services/b2b_documents/non_compete_clients.py`):
  prefill porozumienia o rozwiązaniu (B2B i zlecenie) daje zdanie pod polem
  „Klient, którego dotyczy zwolnienie” (`notes["non_compete_client_name"]`):
  klienci kontraktów tej osoby, które trwały w ciągu 12 miesięcy przed dniem
  rozwiązania, z „trwa” albo „do DD.MM.RRRR”. Bez szkiców, umów do podpisu
  i unieważnionych. Pole dalej podpowiada klienta umowy bazowej, a o zwolnieniu
  decyduje człowiek. Zakaz konkurencji z umowy B2B (wzór 2026) trwa 12 miesięcy po rozwiązaniu
  i dotyczy klienta z Załącznika nr 3.
- Lista niesie tylko nazwy klientów tej osoby, bez kwot; dostęp jak do
  prefillu (umowa bazowa, kontrakt albo rekrutacja wołającego).
- Testy: `tests/test_b2b_non_compete_recent_clients.py`.

## Oświadczenie o rezydencji (WHT) — bez kodu

Kontraktor z firmą zarejestrowaną za granicą (w skrzynce: JDG w Norwegii,
klient Polkomtel) dostaje „oświadczenie odbiorcy należności”, którego treść
negocjują Rozliczenia. NEXUS nie ma wzoru. Wzory w Generatorze są dwojakie:
dokumenty z rejestru typów (`services/b2b_documents/registry.py`, szablony
z wzorów działu) i puste wzory do pobrania (`mandate_forms.py`, tylko umowa
zlecenie). Żaden nie pasuje bez nowego wzoru od Finansów, więc zostaje opis:

- wzór od Rozliczeń (po uzgodnieniu treści z księgową, WHT), potem pusty wzór
  do pobrania przy umowie B2B albo pozycja „Dokumentów do startu” klienta,
  gdy dotyczy jednego klienta;
- pole „kraj rezydencji podatkowej” na kontrakcie, które czytałyby Rozliczenia
  (WHT, certyfikat rezydencji, termin ważności), to osobna praca z Finansami.

## Decyzje Artura (nie budować bez nich)

- **Pilot e-podpisu dla umowy@** (`app_settings['b2b_esign']`): w skrzynce nie
  ma ani jednego podpisu przez link NEXUSA, a stan przełącznika na produkcji
  jest niepotwierdzony.
- **„Zleć umowę” z rekrutacji**: rekruterzy wysyłają na umowy@ mail-formularz
  (z PESEL-em i telefonem w treści). Propozycja: przycisk przy osobie, dane
  z kandydata i rekrutacji, kolejka dla działu umów i „Podsumowanie
  placementu” z „Szczegółów administracyjnych” zamiast maila.
