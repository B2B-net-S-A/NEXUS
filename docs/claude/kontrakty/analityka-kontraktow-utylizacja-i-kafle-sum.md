# Analityka kontraktów: utylizacja i kafle sum (18.09.2026)

- **Mianownik utylizacji to POPULACJA KONSULTANTÓW, nie baza CV.** Jedna
  definicja: `services/consultant_population.py` (czytają ją
  `GET /api/contract-analytics/utilization` i `analytics/metrics.finance_summary`).
  Populacja = osoby z kontraktem `active`/`ending`/`ended` o starcie ≤ dziś,
  fałdowane po tożsamości (`contractor_identity`), więc scalenie duplikatów nie
  podbija wskaźnika. Endpoint liczył wcześniej `outerjoin(Contract)` BEZ filtra
  statusu: 0,8% zamiast 91,3% (**błąd 114×**) i 56 647 osób „na ławce" zamiast
  45 — przy czym `avg_bench_days` obok liczyło się już po tych 45, więc ekran
  przeczył sam sobie. `utilization_pct = None` gdy nie ma kogo liczyć: zero
  znaczyłoby „nikt z naszych konsultantów nie pracuje".
- **Sumy firmowe mają własny endpoint `GET /api/contract-analytics/margin-totals`.**
  Kafle „Miesięczna marża" i „Miesięczny przychód" liczyły się na froncie
  z `margin-by-client`, a ta trasa oddaje 20 wierszy przyciętych po MARŻY —
  klient o wysokim przychodzie i niskiej marży wypadał z kafla PRZYCHODU
  (12 555 483 zamiast 12 772 543 PLN, brakowało 217 060 zł). Podniesienie
  limitu byłoby tym samym błędem, tylko dalej: **suma nie może zależeć od tego,
  ilu klientów mieści się w rankingu obok**. Ranking i suma mają wspólne
  źródło (`_margin_by_client_rows`), ale osobne trasy i osobne stany ładowania.
