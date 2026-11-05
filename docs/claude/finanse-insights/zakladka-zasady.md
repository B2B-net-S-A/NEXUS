# Zakładka „Zasady” w Insights: co obowiązuje i kto to zmienił
<!-- indeks: admin i HoR, 9 zasad, przegląd z `GET /api/insights/rules-overview`, te same panele co w Ustawieniach, „Nigdy” zamiast przypomnienia, ekran punktów Ligi tylko admin -->

Decyzje Artura z 05.11.2026 (makiety: https://claude.ai/artifact/HMAfbAGeDULpmRAw4XjRd5).
Ustawienia, które decydują, jak NEXUS liczy i przydziela, leżały w pięciu miejscach
i ludzie o nich zapominali. Na kopii produkcji z 04.11.2026 sześciu z dziewięciu zasad
nikt nigdy nie zmienił.

Kod: `components/insights/views/ZasadyView.tsx`, `lib/insights-rules.ts`,
`api/insights_rules.py`, `services/insights_rules_overview.py`.

- **Miejsce:** zakładka między Źródłami a Raportami, kolejność Źródła, Zasady, Wnioski, Raporty
  (test „Wniosków” wymaga, żeby stały tuż przed Raportami). Widzą administrator i Head of
  Recruitment, lustro `RULES_ROLES` i `HeadOfRecruitmentPlus`.
- **Pozycje zostają też w Ustawieniach.** To jeden komponent w dwóch miejscach. Delivery
  Lead czyta Ranking, Prepy i Bliźniaki wyłącznie w Ustawieniach, a usunięcie ich stamtąd
  odebrałoby mu wgląd w zasady, według których pracuje. Nie rób kopii panelu dla zakładki.
- **Widoczność wiersza bierze się z rejestru Ustawień** (`canSeeSettingsItem`), więc bramka
  nie może się rozjechać. Head of Recruitment bez roli admina nie widzi Jakości QC, punktów
  Ligi ani Wykluczonych placementów, a trasa ich nie zwraca.
- **Przegląd nie ma własnej kopii reguł.** Wartości idą z tych samych odczytów co ekrany,
  a zdania układają czyste funkcje `*_now`.
- **„Ostatnia zmiana” to zapis człowieka.** Wiersze z migracji i przeliczenia automatu się
  nie liczą, dlatego QC czyta `manual_at` i `manual_by`, a nie `updated_at` wpisu, który
  automat nadpisuje co noc. Automat przydziału bierze późniejszy z dwóch śladów: wpisu
  `request_allocation_rules` i zdarzeń `allocation_*`. Wyjątek: Wykluczone placementy
  wpisuje automat, więc wiersz ma datę i słowo „automat”.
- **Przegląd odświeża się sam:** po każdej udanej mutacji w zakładce (`getMutationCache`)
  i przy zmianie ekranu, bo panele z Ustawień nie znają jego klucza. Automat zapisuje bez
  `useMutation`, więc unieważnia `RULES_OVERVIEW_QUERY_KEY` sam.
- **Pole punktów puste albo spoza zakresu blokuje zapis.** `Number("")` to 0, a zero mieści
  się w zakresie punktów i progów, więc serwer przyjąłby je bez słowa.
- **Przypomnienia nie ma.** Napis „Nigdy” w przeglądzie jest jedynym sygnałem. Kwartalny
  dzwonek Artur odłożył: da się go dołożyć, jeśli to nie wystarczy.
- **Punkty Ligi, Wyścigu i progi Ścieżki rozwoju** dostały pierwszy ekran edycji
  (`zasady/LeagueRulesPanel.tsx`). Trasa `/api/insights/scoring-config` działała od września
  bez żadnego ekranu. Zapis ma tylko administrator, bo punkty rozdzielają nagrody.
  Potwierdzenie pokazuje ostrzeżenie z serwera: próg Ścieżki działa wstecz, a punkty Ligi
  od najbliższego niezamkniętego kwartału.
- **Staging:** panel automatu pokazuje tam „Wyłączony”, bo `RECRUITMENT_ALLOCATION_ENABLED`
  jest wyłączone, choć w bazie jest `auto`. Przegląd pisze to samo, bo czyta
  `effective_allocation_mode`.
- **Pasek zakładek przy 1280 × 720:** dziewięć zakładek konta z Mój miesiąc mieści się w jednym
  rzędzie tylko przy zwężonych odstępach. Następna zrzuci tytuł „Insights” do osobnego wiersza (46 px).
