# Dzwonek Finansów przy aneksie stawki konsultanta (0764, 23.11.2026)
<!-- indeks: `contract_rate_annex`, `services/contract_rate_annex_signal.py`, `rate_signal_source` w `apply_contract_amendment`, odbiorcy Finanse i Back office, bez kwot -->

Przegląd skrzynki umowy@ z 23.11.2026: zmiana stawki trafiała do Rozliczeń
tylko jako PDF aneksu mailem. Krok harmonogramu
(`contract_candidate_rates.effective_from`) dopisywały już wszystkie drogi
aneksu stawki, a Rozliczenia czytały go dopiero przy przeliczeniu miesiąca
(uwaga „Zmiana stawki DD.MM”). Brakowało sygnału w chwili zmiany.

- **Jedno miejsce:** `apply_contract_amendment` (`api/contracts.py`) po
  zapisie aneksu, który dopisał krok stawki konsultanta, woła
  `notify_finance_rate_annex`. Każda droga dostaje ten sam dzwonek: okno
  „Dodaj aneks” (`rate_signal_source="manual"`), „Oznacz jako podpisany” aneksu
  stawki z Generatora (`"generator"`, `b2b_documents/effects.py`) i wpis z pliku
  w Dokumentach kontraktu, ręczny albo automat F52 (`"document"`,
  `contract_rate_documents/service.py`). Nowa droga aneksu podaje swoje źródło,
  a nie drugie wywołanie dzwonka.
- **Sama stawka klienta nie dzwoni:** Rozliczenia płacą konsultantowi, a stawkę
  klienta w zamówieniu ustawia `order_revenue_steps`.
- **Odbiorcy:** aktywne konta Finansów i Back office'u
  (`hired_order_status.finance_recipient_ids`), bez autora aneksu. Typ
  `contract_rate_annex`, kategoria „Kontrakty”, grupa wyciszeń
  `contracts_rate_annex`, sekcja Delivery, zastępstwo w urlopie jak
  `settlement_report_missing`. Encja dzwonka to aneks (`contract_amendment`),
  więc stawka progresywna z kilkoma krokami daje dzwonek na krok.
- **Bez kwot w treści:** dzwonek może iść mailem, a kwota jest na kontrakcie
  pod bramką stawek. Treść: osoba, klient, dzień zmiany i skąd aneks; link do
  zakładki „Aneksy” kontraktu.
- **Fail-soft:** savepoint, błąd to log. Aneks jest ważniejszy niż dzwonek.
- „Cofnij” wpisu automatycznego F52 usuwa aneks, a dzwonek zostaje. Link
  prowadzi do kontraktu, gdzie widać, że kroku już nie ma.
- Migracja 0764 (`ALTER TYPE notificationtype ADD VALUE`) z lustrem
  w `entrypoint.sh`; downgrade odmawia przy istniejących dzwonkach tego typu.
- Testy: `tests/test_contract_rate_annex_signal.py`.
