# Auto-aktywacja zamówień Draft → Aktywne + zakładka Draft dla BIK/BNP

Data: 2026-08-24. Dwa tickety w jednym wdrożeniu (decyzja zamawiającego —
jeden PR): (1) bezterminowy okres nie blokuje aktywacji zamówienia,
(2) widok wielo-konsultantowy BIK/BNP dostaje zakładkę „Draft (do
uzupełnienia)", a Polkomtel przestaje dostawać automatyczne zamówienie po
„Oznacz jako podpisane".

## Hotfix (wykonany na prodzie od ręki, przed wdrożeniem kodu)

Artur Bogusiak / Contract 570 — klient 58 „BNP PARIBAS S.A ODDZIAŁ W POLSCE"
(widok standardowy; to NIE jest wielo-konsultantowy rekord 12). Zamówienie 96
miało komplet 4 pól (numer 20260101, start 2026-01-01, 1550/1260 dziennie)
i wisiało w Draft wyłącznie przez brak daty końcowej. Przełączone jawnym
`PATCH {"status":"active"}` (2026-08-24), zweryfikowane w UI: pigułka
„Aktywni (1)", Draft (0).

## Ticket 1 — bramka aktywacji

* Przyczyna potwierdzona 1:1 z hipotezą ticketu:
  `_order_has_required_activation_data` wymagała `end_date IS NOT NULL`.
* Zmiana: „okres uzupełniony" = **data początkowa**; `end_date` pozostaje
  opcjonalne (`NULL` = bezterminowo). Pozostałe wymagania bez zmian: numer
  (nie „(bez numeru)"), stawka przychodowa zamówienia, stawka kosztowa umowy
  (harmonogram jest prawdą — `_activation_candidate_rate`).
* Auto-aktywacja działa jak dotąd na KAŻDEJ ścieżce zapisu (create, Flow B,
  PATCH — formularz i inline), z zachowanym pierwszeństwem jawnego statusu
  (`PATCH {"status":"draft"}` → `DELETE` nadal działa).
* **Cofania active → draft NIE MA** — wymóg 6 zdjęty decyzją zamawiającego
  w trakcie prac („system ma nie cofać do draft").
* Edycja inline w „Aktywni" działała już wcześniej (brak bramki statusu przy
  `InlineText`/`InlinePeriod`) — potwierdzone na prodzie; wymóg 5 spełniony
  bez zmian kodu.

## Ticket 2 — BIK/BNP/Polkomtel (widok wielo-konsultantowy)

* **Polkomtel (klient kosztowy)**: `_ensure_open_order` nie tworzy już
  ŻADNEGO zamówienia (`should_auto_create_order` — bramka po
  `COST_ORDER_CLIENT_IDS`, nie po zaszytym ID: auto-szkic jest niejednoznaczny
  dokładnie tam, gdzie istnieją dwa typy zamówień). `confirm-fully-signed`
  zwraca `order_id: null` i komunikat wskazujący ręczne dodanie („Nowy
  kontraktor / zamówienie"). Zakładki Polkomtela bez zmian.
* **BIK/BNP**: hook podpisu tworzy szkic jak dotąd (nazwisko, stawka kosztowa
  na umowie, start z umowy) — nowość polega na tym, że szkic wreszcie MA
  gdzie się wyświetlić: pigułka „📝 Draft (do uzupełnienia)" w
  `MultiConsultantOrdersTab` + „⚠️ Kończące się 30d" (grupy aktywne z końcem
  ≤30 dni). „Wyczerpane" ZOSTAJE także u BIK/BNP — świadome odstępstwo od
  literalnego zestawu z ticketu: budżety MD wyczerpują się właśnie u tych
  klientów, a zdjęcie pigułki ukryłoby istniejące grupy w tym stanie.
* **Materializacja**: uzupełniony szkic (4 pola z Ticketu 1) aktywuje się
  i staje LINIĄ GRUPY o numerze z pola „numer zamówienia" — dołącza do
  istniejącej otwartej grupy o tym numerze (BIK prowadzi grupy wieloosobowe)
  albo zakłada nową, zawsze `active`. Dzięki temu import zużycia MD
  (`active_md_lines`), alert `ALERT_MD_BUDGET_LOW`, eksport XLSX i cykl życia
  grup działają bez żadnych zmian. Stawki linii (`md_rate_*`, Numeric 12,2)
  są lustrem stawek szkicu z JAWNĄ kwantyzacją; korekta stawki przychodowej
  na szkicu z budżetem odświeża lustro, a wyczyszczenie stawki przy wpisanym
  budżecie dostaje 422 (nie IntegrityError).
* **„Liczba MD zamówienia"** (`md_quantity` w PATCH): opcjonalna, NIE
  wchodzi do 4 pól aktywacji; wymaga wcześniej stawki przychodowej (CHECK
  `ck_client_orders_md_coherence` — komunikat po polsku); `null` czyści
  budżet. W „Aktywne" liczba MD linii jest edytowalna jak dotąd
  (`update_line`); alert progu MD obejmuje zmaterializowane linie
  automatycznie.
* **Bez retroakcji (req 7)**: zakładka Draft pokazuje wyłącznie szkice
  z `created_at >= 2026-08-24` (`_DRAFT_ORDERS_TAB_SINCE` — stała w kodzie,
  data wdrożenia to fakt historyczny, nie pokrętło). Istniejące niekompletne
  szkice BIK/BNP pozostają niewidoczne (jak dotąd — żyją w alertach DL):
  BNP(12): 7 szt. (Zieleń, Płonka, Krawczyk, Brunka, Dynek, Trzeszczyński,
  Wójcik), BIK: 2 szt. niekompletne (Łuszczyński 143, Koc 149).

## Lista kandydatów do retro-migracji — DO AKCEPTACJI (nic nie wykonano)

Kompletne wg NOWEJ definicji (bez wymogu daty końcowej), wciąż w Draft:

| Klient | Kandydat | Order | Numer | Okres | Stawki (przych./koszt.) | Rekomendacja |
|---|---|---|---|---|---|---|
| Nordea (11) | Patryk Tatarek | 45 | 285668 | 2026-10-19 → 2026-12-31 | 157 / 95 | aktywować |
| Nordea (11) | Dawid Krzysztoń | 92 | 285787 | 2026-09-01 → 2026-12-31 | 213 / 170 | aktywować |
| BIK (18) | Daniel Madejski | 94 | „brak" | 2025-08-01 → bezterm. | 1400 / 1200 | **NIE aktywować** — Madejski ma już aktywną linię w grupie 4500030751 z tymi samymi stawkami (1400/1200), a aktywacja zmaterializowałaby grupę o numerze „brak"; prawdopodobny duplikat do usunięcia |
| BIK (18) | Maciej Koc | 95 | 4500030222 | 2026-06-01 → 2026-09-10 | 1700 / 1280 | **NIE aktywować** — duplikat aktywnej linii 148 w istniejącej grupie 4500030222 (identyczny okres); do usunięcia |

Migracja = ręczny `PATCH {"status":"active"}` per zamówienie (Nordea) po
akceptacji; pozycje 3-4 wymagają wcześniejszej decyzji/porządków.

## Pliki

Backend: `app/api/client_orders.py` (bramka, md_quantity, lustro stawki,
materializacja po aktywacji), `app/services/order_group_materializer.py`
(nowy), `app/services/b2b_contract_automation.py` (`should_auto_create_order`),
`app/api/b2b_contract_generator.py` (confirm bez zamówienia),
`app/api/client_order_groups.py` (`draft_orders` w liście grup),
`app/schemas/client_order.py`, `app/schemas/client_order_group.py`.
Testy: `tests/test_order_activation_gates_and_group_materializer.py` (29).

Frontend: `components/orders/InlineOrderFields.tsx` (ekstrakcja wspólnych
widgetów inline), `components/client-profile/orders/DraftOrdersSection.tsx`
(nowy), `MultiConsultantOrdersTab.tsx` (pigułki + zakładka),
`OrdersAndContractsTab.tsx` (import zamiast lokalnych kopii),
`lib/api/dlPortal.ts`, `lib/api/orderGroups.ts`. Testy: 3 nowe w
`MultiConsultantOrdersTab.test.tsx` (pełny suite FE zielony).

## Znane ograniczenia / świadome decyzje

* Bez migracji schematu — zmiana czysto aplikacyjna (kolumny istniały).
* Grupa z materializacji jest zawsze `active`, także przy starcie w
  przyszłości (semantyka Ticketu 1: komplet = Aktywne; `scheduled` chowałoby
  świeżo uzupełnione zamówienie przed pigułką „Aktywne").
* Pipeline-hook „hired" u Polkomtela też nie tworzy szkicu (ta sama bramka) —
  inaczej niewidzialne szkice wracałyby drugą ścieżką.
* Szkic z tytułem-nazwiskiem (auto) da się aktywować dopiero po wpisaniu
  numeru — ale bramka nie odróżnia numeru „prawdziwego" od dowolnego tekstu
  (jak w widoku standardowym; patrz Madejski „brak" powyżej).
