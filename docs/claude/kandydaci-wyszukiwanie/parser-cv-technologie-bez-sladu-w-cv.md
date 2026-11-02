# Parser CV: technologia bez śladu w CV nie trafia do profilu

Od 02.11.2026 `cv_technology_grounding.drop_untraced_technologies` usuwa z odczytu
parsera technologie, których nie ma w tekście CV: w `skills`, `technologies`,
`experience[].technologies` i `projects[].technologies`. Bo taka pozycja podnosi
osobę w wyszukiwaniu po umiejętności, a rekruter dowiaduje się o tym dopiero przy
rozmowie.

- Sprawdzenie jest łagodne: wystarczy znaczące słowo nazwy, alias z taksonomii albo
  bliska pisownia. Model poprawiający literówkę z CV nic nie zmyśla.
- Krótkie nazwy (Go, R) muszą stać jako osobne słowo, bo inaczej pasują do wszystkiego.
- Bez mapy aliasów filtr nic nie usuwa. Skrypt poza aplikacją wywołuje najpierw
  `refresh_alias_map`, inaczej filtr po prostu nie działa.
- Pomiar na zapisanych odczytach z audytu modeli (ok. 94 CV): odrzuca 0,09 technologii
  na CV u Sonneta 5, 0,21 u Sonneta 5.5 i 0,29 u Haiku 5.5, a lista zostaje praktycznie
  ta sama (28,63 → 28,42 u Sonneta 5.5). Fałszywe firmy w doświadczeniu zostają poza
  tym filtrem.
- Nazwa, która mimo śladu w CV wypada, idzie do `_MORE_SPELLINGS` albo do taksonomii.
  Ile pozycji odpada, widać w logu: `[cv_parser] odrzucone technologie bez śladu w CV`.
