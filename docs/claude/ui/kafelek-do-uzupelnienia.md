# Kafelek „Do uzupełnienia” (21.10.2026)

Prośba Olafa (Head of Recruitment): umowy do zamknięcia, rekrutacje do
dokończenia albo zamknięcia i wymagania do poprawy jako osobna strefa, którą
da się przesunąć w inne miejsce pulpitu. Decyzje Artura 21.10.2026: wariant A
z makiet (https://claude.ai/artifact/2UPJU2mB69Xf25QdtH8KuY) — kafelek na
siatce, dla każdego, kto widzi te listy, z „Przenieś na pulpit” w panelu.
Kod: `custom/ToCompleteTile.tsx`, `ToCompleteMovePrompt.tsx`,
`lib/dashboard-to-complete.ts`, typ `to_complete` w `dashboard_tiles.py`.

- **Kafelek albo panel, nigdy oba.** Kafelek `to_complete` na zapisanym
  pulpicie → `BoardTasksPanel` dostaje `toCompleteOnGrid` i wycina trzy listy
  (`withoutToCompleteLists`). Bez kafelka listy stoją w „Czeka na Ciebie” jak
  przed zmianą. Usunięcie kafelka oddaje je panelowi — nic nie znika.
  Kafelek w układzie konta bez dostępu do „Rekrutacji” (pokazuje „Brak
  dostępu”) się nie liczy — listy zostają wtedy w panelu.
- **Umowy: tylko „do zamknięcia”.** „Umowy do potwierdzenia” (podpis) to
  zadanie i zostają w „Czeka na Ciebie”; prośby rekrutera — w „U innych”.
- **Te same sekcje co w panelu** (`AgreementTasksSection`,
  `PendingJobsSection`, `RequirementFixesSection`), te same dane z jednego
  `GET /api/board-tasks` — bez nowej trasy. Listy odznaczone w „Listy nad
  pulpitem” są w kafelku puste, jak w panelu.
- **Szerokość:** od 880 px kafelka listy stoją obok siebie, węziej —
  przełącznik „Umowy / Rekrutacje / Wymagania” i jedna lista naraz.
- **Stany:** „Nic do uzupełnienia.” tylko przy pustych listach; awaria
  kolejki = `WidgetErrorBlock` z ponowieniem; `requirement_fixes: null` =
  zdanie o awarii w kafelku (panel wtedy milczy).
- **„Przenieś na pulpit” / „Zostaw tutaj”** — linia nad listami w panelu, gdy
  kafelka nie ma, a któraś lista ma wiersze. Przeniesienie = `prependTemplate`
  (góra siatki, cała szerokość) i zapis od razu; „Zostaw tutaj” zapamiętuje
  przeglądarka razem z odrzuconymi ogłoszeniami kafelków. Panel czeka na
  odczyt układu pulpitu, żeby listy nie mignęły w nim przed kafelkiem.
- **Bez kafelka w układach ról** — kto go nie dodał, ma panel jak dotąd.
