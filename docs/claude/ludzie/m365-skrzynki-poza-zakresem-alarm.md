# Skrzynki poza zakresem „NEXUS Kadry”: alarm dla adminów (02.11.2026)

Grupę RBAC aplikacji `nexus-kadry-skrzynki@b2bnetwork.pl` prowadzi się ręcznie
w Exchange, a NEXUS nie może sam dopisywać do grup (decyzja Artura 22.10.2026 przy
grupie Teams). 02.11.2026 wszystkie 4 konta założone 18–29.10 miały 403 przy
odczycie skrzynki i nikt nie dostał sygnału. Osoba poza grupą wychodzi na urlop bez
autoodpowiedzi, wydarzenia i kopii poczty do zastępcy.

- **Bez drugiego odczytu Grapha.** Uzgadnianie o 7:00 czyta każdą skrzynkę i zapisuje
  `last_error`. Alarm (`services/hr/m365/scope_alerts.py`) czyta wiersze
  `forbidden (403)` zaraz po udanym przebiegu dziennym, w `hr_m365_reconcile_job`,
  bez własnej pętli. Nieudany przebieg nie daje alarmu: następny przyjdzie nazajutrz.
  „Uzgodnij teraz” alarmu nie wysyła.
- **Kto wchodzi:** aktywne konto z kartoteką inną niż `exited`. Tylko 403, bo grupa
  naprawia tylko brak dostępu. 404 (brak skrzynki, zły adres) zostaje na liście
  „Skrzynki z błędem” w karcie.
- **Typ `hr_m365_scope_missing`:** tylko admini, dzwonek „Konto i system”, mail od
  razu (rodzaj obowiązkowy `system_failure`). Najwyżej raz dziennie: dedup `emit`
  z id encji 0. Wyłącznik `HR_M365_SCOPE_ALERTS_ENABLED=false`, grupa w treści:
  `HR_M365_SCOPE_GROUP`. Na produkcji zmienia je wyłącznie workflow „Coolify set env”.
  Działa tylko w trybie `live`, bo poza nim uzgadnianie nie zapisuje `last_error`.
- **Treść** mówi, kogo dopisać i jak: `Add-DistributionGroupMember`, potem
  `Test-ServicePrincipalAuthorization` (ma być `InScope = True`). Przy `InScope = True`
  i dalszym 403 przyczyna jest inna: uprawnienia w Entra działałyby na całą firmę,
  więc ich nie dodajemy.

## „Zostaw poza grupą”: świadomy wyjątek

Decyzja Artura z 02.11.2026: osoby z Zarządu mogą zostać poza grupą, więc alarm nie
może o nich mówić codziennie. Wyjątek ustawia się przyciskiem przy skrzynce z 403
w karcie Microsoft 365 („Skrzynki z błędem”), a nie zmienną env, bo alarm dostaje
admin i ma to zrobić bez wdrożenia.

- `POST /api/hr/admin/m365/mailboxes/{id}/scope-exempt` z `{exempt}`, bramka karty
  (`people_admin`). Inny błąd niż 403 przy `exempt: true` = 409, brak wiersza = 404.
  Ślad `m365_scope_exempt_set` / `m365_scope_exempt_cleared` w `hr_audit_events`.
- Znacznik `scope_exempt` leży w `hr_m365_mailbox_state.state` obok mapy wydarzeń
  wykonawcy, dlatego trasa blokuje wiersz (`FOR UPDATE`) i nie nadpisuje całości.
- Osoba **zostaje na liście** z dopiskiem „poza grupą świadomie” i przyciskiem
  „Cofnij”: wyjątek ma być widoczny, nie znikać.
- Wyjątek działa tylko dla alarmu. Urlop takiej osoby nadal nie dostanie
  autoodpowiedzi z NEXUSA.
