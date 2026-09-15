# Panel „Moi klienci" — raport ukończenia

Ticket: reorganizacja powiadomień na dashboardzie Delivery Lead (09.2026).

## Co zmieniono

**Backend**
- `alembic/versions/0310_dl_alerts_my_clients_panel.py` + lustro `entrypoint.sh`: `dl_alerts.event_key`, `priority`, `email_send_started_at`, `email_sent_at`, status `resolved`, 5 nowych typów.
- `app/services/dl_alerts.py`: `emit` ze `stage`/`priority`/`email`, epizody po automatycznym zamknięciu, `resolve_stale`, `resolve_entity_alerts`, `date_cycle_stage`, `emit_new_contractor_draft`, `send_pending_alert_emails`.
- `app/services/order_burn_rate.py` (nowy): dni robocze, tempo zużycia MD/kosztów, próg wysokiego priorytetu.
- `app/tasks/dl_alerts_scanner.py`: reguły `periodic_order_ending`, `framework_contract_expiring`, `contract_ending`, `cost_budget_low`, `new_contractor_draft`, `order_mail_review`; `md_budget_low` z progiem 21 i etapem `high`; auto-zamykanie we wszystkich regułach stanowych; maile po skanie.
- `app/api/dl_alerts.py`: `GET /api/dl-alerts/cards`, odhaczenie całej sprawy + `Activity`, status `resolved` w historii.
- `app/api/notifications.py`: `exclude_section` (lista + `unread_count`).
- `app/services/b2b_contract_automation.py`: karta „Nowy kontraktor" po obustronnym podpisie.
- `app/services/order_mail_ingest.py`, `app/api/order_mail_queue.py`: treść karty weryfikacji z klientem i osobą, odbiorcy z uprawnieniami, zamykanie przy zastosowaniu/odrzuceniu.
- `app/core/config.py`: `DL_ALERT_MD_THRESHOLD=21`, `DL_ALERT_COST_BUDGET_THRESHOLD`, `DL_ALERT_HIGH_PRIORITY_WORKDAYS`, `DL_ALERT_ENDING_WINDOW_DAYS`, `DL_ALERT_EMAIL_ENABLED`.

**Frontend**
- `components/v2/dashboard/MyClientsAlertsPanel.tsx` (nowy), montaż w `RoleDashboard.tsx` dla presetu Delivery Lead.
- `MyTasksDashboard.tsx`: tylko powiadomienia rekrutacyjne (`notificationsApi.listRecruitment`).
- Deep linki `?order=`, `?group=`, `?framework=`: `app/clients/[id]/page.tsx`, `MultiConsultantOrdersTab.tsx`, `OrdersAndContractsTab.tsx`, `FrameworkContractsTab.tsx`, `lib/client-order-list.ts` (`resolveOrderFocus`), `lib/client-tab.ts` (`positiveIntParam`).
- Harness `/preview/dl-alerts` z panelem.

**Dokumentacja**: instrukcja zamówień w Pomocy (sekcja powiadomień, progi) — przestemplowana; `CLAUDE.md`.

## Weryfikacja
- Backend: `tests/test_dl_alerts_my_clients_panel.py` (13 testów) + szeroki przebieg celowany (dl_alerts, order mail, B2B, notifications, route authz): zielono.
- Frontend: `tsc` czysty, eslint czysty, vitest dashboard + zamówienia + lib zielone.
- Wizualnie: `/preview/dl-alerts` w Chrome — układ zgodny z makietą z ticketu.

## Znane ograniczenia
- Dzwonek nadal dostaje powiadomienia o końcu zamówień/umów (decyzja: bez zmian) — DL widzi je w obu miejscach, ale odhacza w panelu.
- Odhaczenie wycisza sprawę w bieżącym epizodzie łącznie z progami T-14/T-7/wysoki priorytet (zgodnie z ticketem). Nowy epizod zaczyna się dopiero, gdy przyczyna ustąpi (`episode_closed_at`).
- **Pierwszy skan po wdrożeniu** wystawi karty (i maile T-14/T-7/high) dla wszystkiego, co już jest w oknie, oraz powtórki dla zaległych dokumentów z maila w kolejce — to realny stan, ale może to być skok liczby maili jednego dnia. Awaryjnie: `DL_ALERT_EMAIL_ENABLED=false`.
- Chwilowa utrata przypisania DL do klienta zamyka jego karty; po przywróceniu przychodzą jako nowy epizod (z mailami progów ponownie).
- Adversarial review (14 punktów): naprawione H1, H3, M3, M4, M5, L1–L6; H2 zostawione jako decyzja ticketu; M1/M2 opisane wyżej.
- Tempo zużycia jest miesięczne (raporty z Finansów) — w bieżącym, niezaraportowanym miesiącu próg opiera się na historii.
- Mail wymaga skonfigurowanego kanału (M365 app mail / SMTP / skrzynka systemowa); bez niego karty działają, maile nie wychodzą.
