# Zakładka „Kończące się 30d" — tylko zamówienia bez kontynuacji (22.09.2026)

Jedna reguła, `endingOrderWithoutSuccessor` / `endingGroupWithoutSuccessor`
w `lib/client-order-list.ts`, zasila pigułkę, jej licznik, filtr „kończy się
w ciągu N dni" i plakietkę karty. Zamówienie kończące się w oknie odpada, gdy
inne zamówienie tego kontraktu (grupy MD: tej samej rodziny przedłużeń po
`predecessor_group_id`, spłaszczonej z `future_orders`) trwa po jego końcu —
lustro `covers_after` z `order_facts.py` (szkic się liczy, anulowane nie,
zamknięte bez daty nie). Każde zamówienie w łańcuchu ocenia się osobno, więc
krótkie przedłużenie kończące się w oknie zostawia kartę z plakietką
„przyszłe zamówienie … kończy się za N dni". **`days_to_latest_end` z API nie
jest już czytany przez tę zakładkę** — liczył po zamówieniu z najpóźniejszym
startem i wskazywał plakietką złe zamówienie. Rodzinę grup buduj z PEŁNEJ listy
(`buildOrderGroupFamilies`), nie z podzbioru po filtrze pigułki.
Filtr „kończy się w ciągu N dni” czyta `next_ending_without_successor_days`
z serwera (najbliższe zamówienie bez kontynuacji, bez górnej granicy dni), nie
lokalną regułę — ta widziała zredagowane `rate_client` (audyt 24.09.2026).
Pigułka „Anulowane” obejmuje kontraktora tylko wtedy, gdy nie ma żadnego
zamówienia aktywnego, wstrzymanego ani szkicu.
