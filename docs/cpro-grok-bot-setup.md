# Bot Cpro: uruchomienie rutyny „NEXUS Cpro” w Grok Bocie

Reguły: `docs/claude/integracje/cpro-bot-grok.md`. Ten plik mówi, co ustawić
po stronie bota i NEXUSA i jak sprawdzić, że rutyna wrzuca osobę sama.
Kod jest na produkcji po scaleniu PR-a z migracją 0732 i wieczornym oknie
wdrożeń; flaga `CPRO_BOT_ENABLED` jest wtedy jeszcze wyłączona.

Klucze i hasła wpisujesz tylko w ustawieniach bota i w sekretach repo, nigdy
w czacie bota, w plikach ani w briefie.

## 1. Wpis Vault „Nordea Cpro” (Artur)

W Grok Bocie (aplikacja desktopowa, konto Artura) → Vault → nowy wpis
**„Nordea Cpro”**: adres `https://nordea.onevms.se/`, login i hasło konta,
którym Sandra wrzuca do Cpro. Hasło wpisuje Artur (albo Sandra przy nim), nie
sesja Claude ani Codex.

## 2. Rutyna „NEXUS Cpro” (Artur)

1. Nowa rutyna z wyzwalaczem **„When a webhook fires”**, nazwa „NEXUS Cpro”.
2. Polecenie rutyny (całe, do wklejenia):

```text
Dostajesz w wejściu webhooka JSON z polami: run_id, kind ("cpro_offers"),
token, expires_at, callback_url, submit, task, report_format, items.

Wykonaj dokładnie instrukcję z pola task dla każdej pozycji z items, po kolei.
Dane do formularzy bierz wyłącznie z items. Plik CV każdej pozycji pobierz
z items[].offer.cv_url z nagłówkiem X-Run-Token: <token>.
Gdy submit = false, nie klikaj „Submit Offer” — zostaw szkic.

Na koniec wyślij JEDNO żądanie:
POST {callback_url}
Content-Type: application/json
X-Run-Token: {token}
z treścią w kształcie report_format (bez dodatkowych pól, bez komentarzy).
Token jest jednorazowy i ważny do expires_at; nie zapisuj go, danych osób
ani plików CV w plikach, notatkach ani pamięci.
```

3. Adres i klucz webhooka (pokazuje je tylko aplikacja desktopowa) od razu jako
   sekrety repo `GROK_BOT_CPRO_WEBHOOK_URL` i `GROK_BOT_CPRO_WEBHOOK_KEY`.
4. **Zgody w bocie:** przy pierwszej karcie zgody na
   `GET https://api.nexus.dynaminds.pl/api/integrations/cpro-bot/runs/…/cv/…`,
   `POST https://api.nexus.dynaminds.pl/api/integrations/cpro-bot/runs/…`
   i na `https://nordea.onevms.se/…` wybierz **„Always allow”**.

## 3. Zmienne w NEXUSIE (Codex albo Artur)

Workflow **„Coolify set env”** (jedyna droga zmiany env na produkcji):
`GROK_BOT_CPRO_WEBHOOK_URL` i `GROK_BOT_CPRO_WEBHOOK_KEY` z `value_from_secret`.
`CPRO_BOT_ENABLED` zostaje `false`. Wdrożenie w oknie 18:00–08:00 (pon–pt)
albo w weekend; potem `/api/health` → `version` = SHA z maina.

## 4. Próba (Codex albo Artur, kontener backendu na produkcji)

```bash
python -m scripts.cpro_bot_run
```

Pokazuje kolejkę Cpro tak, jak widzi ją bot: `ready` albo `blockers`, numer
requestu, `data_from`. Wybierz jedną kartę `ready` (`stage_id`) i zleć próbę
**bez wysyłki**:

```bash
python -m scripts.cpro_bot_run --start --stage-ids <stage_id>
```

Oczekiwane: `{"started": true, "status": "started", "submit": false, …}`,
po kilku minutach w Cpro szkic (DRAFT) oferty tej osoby, a w bazie:

```sql
SELECT id, status, report->'counts' FROM cpro_bot_runs ORDER BY id DESC LIMIT 1;
```

`status = received`, `counts.draft = 1`. Sandra otwiera szkic w Cpro
i porównuje z tym, co wpisałaby sama (stawka, CV otwiera się, Motivation,
Available from, Physical location, Former…, Matching „Perfect”). Uwagi →
poprawka w `services/cpro_bot/task_text.py` albo `offer_text.py`.

Nie przeszło (`expired`, `failed`, `counts.failed`): przeczytaj `report->'items'`
(`reason`, `message`) i historię biegu w Grok Bocie; najczęściej karta zgody
albo logowanie (`login_failed`).

## 5. Pierwsza wysyłka i włączenie (Artur)

1. Ta sama karta naprawdę: `python -m scripts.cpro_bot_run --start --stage-ids <stage_id> --submit`.
   Oczekiwane: `counts.submitted = 1`, `counts.moved = 1`, w Cpro status
   SELECTION, w NEXUSIE karta na „Wysłane do Cpro”.
2. `CPRO_BOT_ENABLED=true` workflowem „Coolify set env” i wdrożenie.
   Od tej chwili pętla co 5 minut bierze karty bez braków. W oknie „Do
   wrzucenia do Cpro” przy każdej osobie widać stan bota, a nad listą
   „Bot Cpro · … · wysłane dziś: N”.
3. Wyłączenie awaryjne: `CPRO_BOT_ENABLED=false` (Coolify set env) — pętla
   staje, ręczne „✓ Wrzucone” działa jak przed botem.
