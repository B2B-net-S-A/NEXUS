# Nocny przegląd: bramki bez regexa w Postgresie (08.11.2026)

Przegląd skanuje całą bazę (ok. 68 tys. osób w paczkach po 256) i bramkami zajmował
większość czasu. Pomiar na kopii produkcji (30 paczek, jedna rekrutacja, czas ściany):
`content ~* wzorzec` po notatkach paczki 150–260 ms, samo pobranie tych notatek 1 ms.
Regex w Postgresie kosztuje ok. 1 ms na notatkę, a bramka szuka literalnych słów.

- **Wstępny filtr notatek stoi w Pythonie** (`must_text_evidence._load_notes(forms=…)`,
  `_loose_forms`): jedno zapytanie po notatki paczki, potem `forma in content.lower()`.
  Formy są dosłowne i bez wielkości liter (`_loose_pg_pattern` to ten sam zbiór), więc
  to ta sama decyzja co `content ~* pattern`. Inne ścieżki (`hidden_by_critical`,
  przegląd DL, testy z własnym regexem) dalej używają `pattern` w SQL.
- **Dowód tylko tam, gdzie go ktoś czyta.** Ocena potrzebuje dowodu dla wszystkich
  must i nice, bramka tylko dla krytycznych. `attach_gate_evidence(only=…)` liczy dowód
  samej bramki, a `candidate_search_worker` dokłada pełny dowód osobom, które bramkę
  przeszły. Wyjątek: `score_excluded` (Tablica liczy wynik też ukrytym).
- **Zbiór notatek zawsze z pełnej listy etykiet**, także przy `only`. Wstępny filtr ma
  dziury: fraza „spring boot” nie łapie „Spring-Boot”, a wzorzec bramki już tak
  (`_PHRASE_GAP_PY`). Notatka wchodzi wtedy tylko dzięki innej etykiecie, więc węższy
  zbiór zmieniłby, kogo bramka ukrywa. Nie zawężaj tego „przy okazji”.
- **Bramka nie wczytuje kandydatów drugi raz** (`_gate_and_dealbreakers(candidates_loaded=True)`,
  `evaluate_candidates_for_job(candidates=…)`), bo wołający ma świeże pełne wiersze
  z CV. Pozostałe ścieżki bez zmian.
- **`text_met_labels`** sprawdza słowa filtra raz na osobę po wszystkich tekstach
  (`_tokens_of`, zbiór obecnych słów) zamiast dla każdego wzorca w każdym źródle.

Sprawdzenie przy zmianie tych funkcji: porównanie starego i nowego kodu na kopii produkcji
(pełna baza, 24 przeglądy): `evaluate_batch` bez wektora, ten sam zbiór dopuszczonych,
powody wykluczeń, wynik i dowody; 1,6 mln par bez różnicy (08.11.2026). Eligibility: mediana
z 5 przeglądów 102 s → 31 s.
Testy jednostkowe: `tests/test_full_scan_gate_speed.py`.
