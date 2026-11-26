# Wygląd bez motywu: „Klocki + ciemne menu”
<!-- indeks: wariant D z makiet 26.11.2026, tokeny `--edge`/`--edge-soft`, granatowe `--sidebar`, `[data-app-topbar]`, `a[aria-current="page"]` w menu, tylko `:not([data-world]):not([data-kids])`, strażnik `theme-soft-blocks-contract.test.ts` -->

Decyzja Artura z 26.11.2026: NEXUS bez wybranego świata ma być tak wyraźny jak
tryb gry — przyciski, karty, menu i ekran mają się od siebie odcinać, a nie
wyglądać jak „narysowane ołówkiem”. Z czterech wariantów (makiety ze stagingu:
https://claude.ai/artifact/4h1Yzxr7QetgCi4Sm5rnsq) wybrany D.

- **Co daje wyrazistość, wzięte z Gry:** grubsza krawędź karty (wewnętrzny
  cień 1 px na krawędzi 1 px, więc nic nie zmienia rozmiaru), twardy spód pod
  kartą i przyciskiem (`--edge`, lżejszy `--edge-soft` dla karty w karcie),
  płótno ciemniejsze od karty z drobnymi kropkami, przycisk, który się wciska.
  Bez różu, tęczowych nagłówków, czcionki Gry i podskakiwania kart.
- **Granatowe menu, biały górny pasek.** Tokeny `--sidebar*` w bloku jasnym;
  aktywna pozycja (`a[aria-current="page"]`) wypełniona `--primary`. Górny
  pasek ma znacznik `data-app-topbar` — nie celuj w `header`, bo nagłówki stron
  w `<main>` też są `header`.
- **Tylko bez świata i bez Gry.** Każda reguła ma `:not([data-world])`
  i `:not([data-kids="true"])`; światy i Gra wyglądają jak wcześniej. Pilnuje
  `frontend/src/lib/__tests__/theme-soft-blocks-contract.test.ts` (także
  kontrast tekstu menu ≥ 4,5:1).
- **Okna dialogowe** zostają przy własnym cieniu (wykluczone `role="dialog"`).
- **Czerwień dalej tylko dla „pilne”.** Wariant nie dodaje czerwonych akcentów.
- Przejścia między ekranami (wejście ekranu, uniesienie karty) nie weszły:
  wymagałyby zmian w komponentach, a nie tylko w arkuszu.
