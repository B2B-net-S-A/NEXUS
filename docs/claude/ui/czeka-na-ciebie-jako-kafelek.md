# „Czeka na Ciebie” jako kafelek pulpitu (23.10.2026)

Prośba Olafa (Head of Recruitment): móc usunąć z pulpitu każdą sekcję, także
„Czeka na Ciebie”. Do tej daty kafelki dało się usuwać, listy panelu chować
pojedynczo w „Listy nad pulpitem”, ale samego panelu nie dało się ani
przesunąć, ani usunąć. Artur wybrał wariant „panel jako zwykły kafelek”.

Kod: typ kafelka `board_tasks` (`dashboard_tiles.py`, `catalog.ts`),
`custom/BoardTasksTile.tsx`, `CustomDashboard.tsx`, klucz `board_tasks`
w `hidden_panels` (`dashboard-panels.ts`).

- **Tylko Head of Recruitment i admin** (`canCustomizeBoardPanel`, ta sama
  reguła co chowanie list). Rekruterowi, TCM-owi i DL-owi panel zostaje nad
  siatką na stałe — zadanie ma do nich dotrzeć. Kafelek w ich układzie
  pokazuje „Brak dostępu”, a panel stoi wtedy nad siatką.
- **Kafelek albo pas, nigdy oba.** Kafelek `board_tasks` na pulpicie = panel
  renderuje się tylko w nim, z tymi samymi ustawieniami pulpitu (ukryte listy,
  kafelek „Do uzupełnienia”, pas „Do wysłania do klienta”) przez
  `BoardTasksPanelProvider`. Kafelek nie ma własnej kopii panelu.
- **`board_tasks` w `hidden_panels` to nie lista, tylko miejsce panelu:**
  ukryty = panel nie stoi nad siatką. Usunięcie kafelka zapisuje ten klucz,
  więc panel nie wraca nad siatkę — znika z pulpitu. Wraca przez „Listy nad
  pulpitem” (cały panel nad siatką) albo katalog („Czeka na Ciebie”).
- **Menu panelu nad siatką** („⋯” w nagłówku): „Postaw jako kafelek na
  pulpicie” (`prependTemplate`, góra siatki, cała szerokość) i „Usuń
  z pulpitu”. Cichy widok panelu (same listy informacyjne) nagłówka nie ma —
  wtedy zostaje „Listy nad pulpitem”.
- Kafelek stoi na pulpicie raz (duplikat odmawia), najwęższy na 6 kolumn —
  panel układa listy w trzy kolumny od szerokości ekranu `lg`.
- Pusty panel w kafelku mówi „Nic na Ciebie teraz nie czeka.” zamiast pustej
  ramki (`inTile`).
