# Audyt NEXUS — runda 11 (27.09.2026, domknięcie)

Baza: `734c4fa6d` (main po PR #1874). Bez nowego audytu: runda domyka pozycje „Znalezione, poza zakresem” z [runda-10.md](runda-10.md), na prośbę Artura (punkty 1–6). Naprawa: PR rundy 11 (gałąź `claude/audit-r11-fixes`), 4 agentów naprawczych + przegląd kodu + pełne CI.

## Co naprawiono

| Punkt z rundy 10 | Stan | Co zrobiono |
|---|---|---|
| `/bulk-move` bez `entry_source` | naprawione | Świeża para dostaje `entry_source` i blokadę 12 h tą samą funkcją co `/move` (`_fresh_pair_entry_kwargs`); integracja OAuth — `auto_match` bez blokady |
| `request_status_expr` — champion przykrywał „Klient milczy”/„Zakończony” | naprawione | Gałąź `champion` wymaga `work_state` innego niż `client_silent`/`finished` (lustro `request_stage_expr`) |
| Umiejętności ze screeningu poza korpusem słów kluczowych | naprawione | Trigger korpusu czyta `screening_notes.verified_skills` (tylko `confirmed`, sama nazwa), trigger na `screening_notes`, `CORPUS_SOURCES_VERSION` 3, migracja 0396; `verified_tech` nietknięte (scoring bez zmian) |
| PKCE M365 w `state` | naprawione | `state` niesie tylko nonce, verifier = HMAC klucza po stronie serwera, jednorazowe zużycie (`app_settings['m365_oauth_consumed_states']`); stare `state` odrzucane |
| Szablony umów bez limitów operacji | naprawione | Ten sam `_BoundedSandbox`/`_render_bounded` co szablony maili; przekroczenie = 422; też szkic kontraktu i podgląd generatora B2B |
| `window.confirm` we froncie | naprawione | 18 wywołań w 15 plikach → `useConfirmV2()` (okno aplikacji, anulowanie = nic, potwierdzenie raz); strażnik `native-confirm-guard.test.ts` |
| F23 — CV znika z karty po zmianie etapu | naprawione (odczyt) | GET CV firmowego etapu bez własnego CV wskazuje `pair_source_stage_id`; karta „CV do klienta” czyta, pobiera i edytuje dokument pary. Pliki nie są kopiowane ani przenoszone |

## Znalezione, poza zakresem

- `CvHandoffWorkbench.tsx` (linki klienta, wyłączone flagą) i `candidate-profile/RecruitmentsTab.tsx` czytają CV tylko z bieżącego wiersza etapu — mogą przejść na `pair_source_stage_id`.
- Request „Do przejrzenia” z championem zostaje ze statusem `champion` (status nie ma wartości „Do przejrzenia”).
- Zakres `q_scope=skills`, filtr „Umiejętności” i wycinki pod wynikiem nie widzą umiejętności ze screeningu (pełny korpus widzi). Na produkcji to 26 umiejętności u 6 kandydatów, wszystkie historyczne.
- `contracts._render_draft_body` renderuje na pętli zdarzeń (teraz najwyżej ~2 s dzięki limitom).
- `consume_state` M365 powtarza logikę JJIT zamiast ją współdzielić.
- Natywne `alert()` we froncie (np. `NotificationsTab`, `PipelineTemplatesTab`) — ten sam problem zamrażania automatyzacji co `confirm`.
- F07 (zakładka prospektu) nadal czeka na decyzję Artura.

## Porządki

Usunięte lokalne kopie repo (78) i gałęzie (81 agentów + 19 integracyjnych) po rundach 6–10 — każda gałąź sprawdzona jako zawarta w scalonym PR-ze. Gałęzie na GitHubie nietknięte.
