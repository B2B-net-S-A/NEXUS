# Marża na liście placementów i etap w nawiasie w „Kto się liczy”

Prośby Olafa z 27.11.2026, decyzje Artura z 27.11.2026 (warianty A3 i B2 z makiet).
Dotyczy listy „Kto się liczy” (`components/v2/kpi/WhoCountsList.tsx`) w Insights →
Zespół i w kafelku „Aktywność rekrutacyjna”; dane z
`GET /api/dashboard/v2/recruitment-activity/details`.

## Etap w nawiasie (A3)

- „Przed wysłaniem do klienta (QC CV) · 1 dzień”: w nawiasie nazwa etapu
  z procesu klienta (`pipeline_stage_defs.name`, np. „Wysłać do Cpro” u Nordei),
  po kropce czas w obecnym etapie (jak „Czeka na klienta · N dni”).
- „Inne zakończenia”: „Odrzucenie u nas (na QC CV) · powód” — etap, na którym
  para odpadła (ostatni wiersz pary przed odrzuceniem/rezygnacją).
- „Klient odrzucił”, „Czeka na klienta” i „U klienta” bez nawiasu — już mówią,
  gdzie para jest.
- Pole API: `state_stage_name` (`_DESCRIBED_CTE` w
  `services/recruitment_activity.py`). Para bez definicji etapu = bez nawiasu.

## Marża (B2)

- Trzy kolumny w liście placementów: Koszt, Klient, Marża (zł/h · %, pod spodem
  zł/mies.). Kolumna „Godzina” znika, gdy kolumny marży są widoczne (ekran
  1280 × 720); bez prawa do kwot lista wygląda jak przedtem.
- Liczenie jak eksport „Placementy” i Płace (`contract_margin`): kontrakt pary
  (najpóźniejszy start, bez unieważnionych), stawki z dnia startu, zł/h,
  waluta obca po kursie NBP. Miesięcznie = marża/h × 168 h. Minus zostaje
  minusem (czerwony) — to sygnał do sprawdzenia kontraktu, nie błąd ekranu.
- Kontrakt bez stawki klienta: stawka „do klienta” z rekrutacji
  (`candidate_stages.client_rate_value`) ze znaczkiem „z rekrutacji”. Brak
  kontraktu, stawki albo kursu = „—” z podpowiedzią, nigdy zgadnięta liczba.
- Pod podsumowaniem suma marży z całego okresu (wszystkie strony), z wierszy,
  które odbiorca widzi.
- Kod: `services/placement_margins.py`.

## Kto widzi kwoty

Bramka jest na serwerze — front tylko rysuje to, co przyszło.

- „Moduł Finanse” (admin, Finanse): wszyscy klienci, `margin_scope = "all"`.
- Konto rządzone portfelem Delivery Leada z „Stawki i kwoty: podgląd”: tylko
  klienci z portfela (`can_read_client_finance`), reszta wierszy
  `margin_hidden` i „—”; `margin_scope = "portfolio"`. Druga rola (HoR, TCM)
  nie rozszerza portfela.
- Head of Recruitment, TCM, rekruter i pozostali: bez kwot w odpowiedzi
  (`margin_scope = null`), także z podglądem kwot nadanym na ekranie uprawnień —
  reguła „HoR nie widzi pieniędzy w Insights” (24.09.2026,
  `insights-insights-parytet-z-dynareporterem-na.md`).
- Testy: `backend/tests/test_placement_margins.py`,
  `frontend/src/components/v2/kpi/__tests__/WhoCountsList.test.tsx`.
