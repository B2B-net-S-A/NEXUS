# Ręczne wykluczenie placementu ze statystyk

Decyzja Artura z 05.11.2026. Placement osoby, która nie podjęła pracy albo
którą klient odprawił zaraz po starcie, nie liczy się w Insights, Radzie, KPI,
Lidze ani wyścigach. Admin dodaje taką parę (kandydat, rekrutacja) w
Ustawieniach → System → Wykluczone placementy, z powodem.

- Działa przez tę samą tabelę `placement_exclusions` co reguła serii (0343),
  powód `manual` (0651). Historia etapów zostaje.
- Tylko wykluczenie `manual` da się przywrócić. Wykluczeń z reguły ekran nie
  zdejmuje, bo reguła dodałaby je z powrotem.
- Para musi mieć etap „Zatrudniony”, inaczej 422: pomyłka w numerach nie
  tworzy wiersza.
- Okres wyścigu albo Ligi zamrożony wcześniej się nie zmienia (zapis jest
  jednorazowy). Wykluczenie zmienia okresy jeszcze otwarte i okresy
  zamykane później.
- Premie za ten placement to osobna czynność w Płacach. Wykluczenie ich nie
  anuluje.
- Repo jest publiczne: numerów kandydatów ani rekrutacji z produkcji nie
  wpisujemy do kodu ani migracji. Wiersz dodaje admin na ekranie.
