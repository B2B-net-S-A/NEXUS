# Szczegóły administracyjne umowy — rekruter i DL z reguły premii, replacement, FTE i kandydat od klienta (0524, 0654)
<!-- indeks: kafelek w Generatorze (B2B i zlecenie), rekruter/DL tylko do odczytu = odbiorcy premii, replacement + FTE obowiązkowe przy rekrutacji, kopia do kontraktu przy podpisie, dzwonek i przypomnienia dla prowadzącego, kandydat wskazany przez klienta bez premii (0654), kafelek w kontrakcie z powodem po podpisie -->

Zgłoszenie 26.10.2026: kafelek „Szczegóły administracyjne” w Generatorze pod
„Źródłem danych” (Rekruter, Delivery Lead, Replacement, Wymiar FTE), dane
przenoszone do kontraktu. Decyzje Artura z 26.10.2026 zmieniły zgłoszenie
w trzech miejscach.

## Kto robi umowę i komu placement

- Docelowo umowę generuje **rekruter, który prowadzi kandydata** w rekrutacji:
  wysyła ją kandydatowi i pilnuje podpisu za firmę. Generować może każdy (DL,
  TCM, finanse, admin), gdy prowadzącego nie ma — dostęp do Generatora się nie
  zmienia (`generator-umow-b2b-trzy-zakladki-cyklu-zycia-umowy.md`).
- Na kopii produkcji z 22.10.2026 0 ze 104 umów z ostatnich 120 dni wygenerował
  rekruter, a osoba prowadząca była autorem umowy w 4 ze 107 par. Dlatego
  domyślne „osoba tworząca umowę” ze zgłoszenia byłoby złe niemal zawsze.

## Rekruter i Delivery Lead są tylko do odczytu

- To **odbiorcy placementu i premii po 168 h**, liczeni tą samą regułą co
  automat premii (`services/hr/placement_bonuses.load_context`, przez
  `services/b2b_contract_generator/admin_details.placement_people`): rekruter =
  „Prowadzi”, a bez przypisania pierwsza zaakceptowana weryfikacja; DL = DL
  rekrutacji, potem prowadzący rekrutację z rolą DL, potem główny DL klienta.
  Wolny wybór na umowie dawałby drugą, rozjechaną z Ligą i Płacami wersję tego,
  kto zrobił placement.
- Zmiana: rekrutera — „Prowadzi” w panelu osoby (admin, Head of Recruitment,
  z powodem); DL-a — w rekrutacji. Kafelek pokazuje skąd jest osoba
  (`source_label`) i link do miejsca zmiany.
- Gdy generuje ktoś inny niż prowadzący, kafelek mówi to wprost, a prowadzący
  dostaje dzwonek `b2b_agreement_ready` (kategoria „wzmianki”, ikona „Umowy”).
  `b2b_generated_contracts.recruiter_user_id` (dotąd tylko z importu Excela)
  trzyma prowadzącego z chwili wygenerowania — przypomnienia o podpisie na
  pulpicie (`board_flow._unsigned_contracts`, `agreement_tasks`) idą do autora
  ORAZ prowadzącego. Zmiana „Prowadzi” przepina niepodpisane umowy pary
  (`pair_owner.assign_owner`).

## Replacement i FTE

- Obowiązkowe **przy umowie z rekrutacją** (`/render`, `/mandate/render`,
  `/rerender`: 422 bez nich). Umowa ręczna bez rekrutacji zapisuje to, co
  przyszło. W schemacie pola są opcjonalne (`AgreementAdminDetails`), bo
  `render_payload` sprzed 0524 odtwarza się przy każdym ponownym pobraniu DOCX.
- **Replacement** domyślnie „Nie”; tytuł rekrutacji ze „zastępstwo” albo
  „replacement” daje od razu „Tak”, a osobę — tylko gdy u klienta jest
  dokładnie jeden pasujący kontraktor (175 takich rekrutacji w roku na kopii
  produkcji). „Za kogo”: kontraktorzy klienta, najpierw ci, którzy odeszli,
  potem cały NEXUS (`GET /api/b2b-generator/replacement-options`, bez kwot).
  Osoba nie może zastępować samej siebie (422).
- **Gwarancja** (decyzje Artura 26.10 i 05.11.2026): gdy kontrakt osoby zastąpionej
  trwał krócej niż rok i zatrudnił ją ten sam DL, za placement-zastępstwo premia
  DL się nie należy. Rekruter gwarancji nie ma. Automat premii liczy to od
  05.11.2026 (`ludzie/premia-200-tcm-gwarancja.md`).
- **FTE** 1 / 0,75 / 0,5 / 0,25, domyślnie 1 — rekrutacja nie ma pola FTE
  (pełny etat ma 4495 z 4495 rekrutacji). Premia „po 168 h” przy FTE < 1
  przychodzi później: termin = start + 21 / FTE dni roboczych (decyzja Artura
  26.10.2026). Kafelek podaje liczbę dni; automat premii jeszcze liczy zawsze 21.

## Kontrakt

- Kolumny `is_replacement`, `replaced_contract_id` (FK do `contracts`,
  `ON DELETE SET NULL`), `fte` (`Numeric(3,2)`, CHECK na cztery wartości)
  w `b2b_generated_contracts` i w `contracts`. „Oznacz jako podpisaną” kopiuje
  je **fill-only** (`copy_admin_details_to_contract`) — od podpisu źródłem jest
  kontrakt; lista uzupełnionych pól idzie do Activity `fully_signed_confirmed`
  (`admin_details_filled`).
- Kafelek w zakładce Szczegóły kontraktu (z edycją i terminem premii) to
  osobny PR; tak samo zmiany automatu premii (FTE, gwarancja).

## Kandydat wskazany przez klienta (0654, 06.11.2026)

- Zgłoszenie Płac, decyzja Artura z 06.11.2026: klient sam wskazuje osobę,
  a my ją tylko przepuszczamy przez siebie (ERSTE, kontrakt 687). **Premii
  z placementu nie dostaje nikt**, ani rekruter, ani Delivery Lead,
  a kontrakt nie liczy się do premii 200% (`ludzie/premia-200-tcm-gwarancja.md`).
- Kolumna `is_client_referral` (bool, NULL = nie wiadomo, liczy się jak „Nie”)
  w `b2b_generated_contracts` i `contracts`. Trzecie pole kafelka w Generatorze
  (Tak/Nie, domyślnie „Nie”, nieobowiązkowe: umowa sprzed 0654 odtwarza się
  bez niego). „Oznacz jako podpisaną” kopiuje je fill-only jak FTE.

## Zmiana po podpisie: kafelek w kontrakcie (06.11.2026)

- Decyzja Artura z 06.11.2026: Płace muszą oznaczyć zastępstwo i kandydata
  od klienta przy kontraktach podpisanych wcześniej (pole w kontrakcie miało
  1 z 86 kontraktów od września). Kafelek „Szczegóły administracyjne” nad
  „Premiami z tego kontraktu” (`ContractAdminDetailsCard`): Replacement,
  „Za kogo” (ten sam wybór co w Generatorze, `replacement-options`) i „Kandydat
  wskazany przez klienta”.
- Trasa `GET|PUT /api/hr/payroll/contracts/{id}/admin-details`
  (`api/hr_contract_admin_details.py`, za przełącznikiem programu i modułu Płac).
  Kto: „Płace” albo „Umowy B2B: oznaczanie jako podpisane”
  (`require_any_permission`); konto rządzone portfelem DL-a tylko u swoich
  klientów, TCM i Płace u wszystkich. Pola nie idą przez zwykły PATCH kontraktu.
- PUT niesie komplet trzech pól i **obowiązkowy powód** (min. 3 znaki, 422 bez
  niego). „Tak” bez osoby i osoba zastępująca samą siebie (ten sam kontrakt
  albo ten sam kandydat) = 422. Ślad: `admin_details_changed` w historii
  kontraktu (pola „przed → po” i powód) i w `hr_audit_events`
  (`sensitivity='payroll'`).
- Zapis od razu uzgadnia premie kontraktu
  (`placement_bonuses.on_admin_details_changed`): gwarancja DL anuluje premię
  DL z powodem `guarantee`, kandydat od klienta — wszystkie z `client_referral`.
