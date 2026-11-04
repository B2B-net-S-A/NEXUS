# Podsumowanie aktywności kandydata (AI)

Karta „Podsumowanie aktywności" w szynie „Podsumowanie AI" profilu kandydata
(`CandidateActivitySummaryCard.tsx`) — krótka notatka AI kondensująca historię
(wysyłki, feedbacki, preferencje, stawki, dostępność). PR #1003, migracja
`0204_candidate_activity_summaries`. Pełny opis:
`docs/candidate-activity-summary-completion-report.md`.

- **GET nigdy nie generuje** (`/api/candidates/{id}/activity-summary` = cache-only) —
  karta jest na domyślnej zakładce, auto-generacja przy 49k kandydatów = koszt.
  Pierwsza generacja i aktualizacja wyłącznie przyciskiem → `POST …/refresh`.
- **Refresh płaci tylko przy zmianie historii**: `input_hash` sekcji + wersji promptu
  + modelu (wzorzec match justification). Bez zmian → `refreshed=false`, FE toastuje
  „Podsumowanie jest aktualne". Bump wersji promptu `CANDIDATE_ACTIVITY_SUMMARY`
  inwaliduje wszystkie cache.
- **Kwoty**: `AIFeatureKey.candidate_summary` (slot zarezerwowany od 0085, teraz
  użyty) — liczy zużycie, niczego nie blokuje (NEXUS bez limitów AI). Oba endpointy za
  `OperationalUser`. Model override: env `CANDIDATE_SUMMARY_MODEL`.
- Wyjście plaintext (nie JSON) + `thinking={"type": "disabled"}` (trap truncacji
  Sonnet 5). Tabela ma lustro DDL w entrypoint.sh (jak każda zmiana schematu).
