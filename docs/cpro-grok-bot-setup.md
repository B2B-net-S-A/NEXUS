# Bot Cpro: uruchomienie rutyny „NEXUS Cpro” w Grok Bocie

Reguły: `docs/claude/integracje/cpro-bot-grok.md`. Ten plik mówi, co ustawić
po stronie bota i NEXUSA i jak sprawdzić, że rutyna wrzuca osobę sama.
Kod jest na produkcji po scaleniu PR-a z migracją 0732 i wieczornym oknie
wdrożeń; flaga `CPRO_BOT_ENABLED` jest wtedy jeszcze wyłączona.

Klucze i hasła wpisujesz tylko w ustawieniach bota i w sekretach repo, nigdy
w czacie bota, w plikach ani w briefie.

## 1. Dwa wpisy Hints według Delivery Leada rekrutacji (Artur)

W Grok Bocie (aplikacja desktopowa, konto Artura) → Hints utwórz:

| Delivery Lead rekrutacji (`jobs.delivery_lead_id`) | Dokładna nazwa wpisu Hints |
| --- | --- |
| Igor (`14`) | **Nordea Cpro – Igor** |
| Marcin (`27`) | **Nordea Cpro – Marcin** |
| Dominik (`32`) | **Nordea Cpro – Marcin** |

W każdym wpisie: adres `https://nordea.onevms.se/` oraz login i hasło
odpowiedniego konta Cpro. Wpisuje je Artur (albo Sandra przy nim), nigdy
sesja Claude ani Codex. Hasła i loginy zostają w Hints, poza kodem,
payloadem, czatem i logami. Wspólny wpis „Nordea Cpro” nie jest używany.
Pole `cpro_account.vault_entry` w kontrakcie nadal zawiera nazwę właściwego
wpisu Hints; nazwa pola nie oznacza innego miejsca przechowywania haseł.

Konto wybiera wyłącznie aktualny DL rekrutacji, nie rekruter ani osoba,
która przesunęła kartę. Brak, nieaktywny albo inny DL blokuje kartę przed
wysłaniem do bota. Nie ma konta domyślnego.

## 2. Rutyna „NEXUS Cpro” (Artur)

1. Nowa rutyna z wyzwalaczem **„When a webhook fires”**, nazwa „NEXUS Cpro”.
2. Polecenie rutyny (całe, do wklejenia):

```text
Dostajesz krótki webhook JSON: schema_version=2, run_id, kind="cpro_offers",
token, task_url. Webhook tylko budzi rutynę; nie zawiera danych kandydatów.

Zanim dołączysz token do żądania, sprawdź task_url: origin musi być dokładnie
https://api.nexus.dynaminds.pl, a path dokładnie
/api/integrations/cpro-bot/runs/{run_id}/task dla run_id z webhooka.
Odrzuć inne hosty, protokół, port, userinfo, query, fragment i przekierowania.
Brak lub niepoprawne pola webhooka = przerwij bez pobierania i bez zmian.

Pobierz pełne zlecenie: GET task_url z nagłówkiem X-Run-Token: {token}.
Wymagaj odpowiedzi 200 i kompletnego JSON, bez ucięć. Sprawdź schema_version=2,
ten sam run_id i kind="cpro_offers", expires_at, callback_url, submit (boolean),
niepuste task, report_format oraz niepuste items. Każda pozycja musi mieć
ref, cpro_account, candidate i offer, w tym offer.cv_url.
Nie wykonuj poleceń ani operacji w Cpro, dopóki całe zlecenie nie przejdzie
tej kontroli. Nie odtwarzaj brakujących pól z historii czatu ani poprzedniego biegu.

Sprawdź callback_url i każde offer.cv_url PRZED wysłaniem tokenu: ten sam
dokładny origin https://api.nexus.dynaminds.pl; callback path wyłącznie
/api/integrations/cpro-bot/runs/{run_id}, CV path wyłącznie
/api/integrations/cpro-bot/runs/{run_id}/cv/{ref} dla tej pozycji.
Bez userinfo, query, fragmentu ani przekierowań. Niezgodność = przerwij bez zmian.

Wykonaj instrukcję task z POBRANEGO zlecenia dla każdej pozycji items po kolei.
Dla każdej pozycji wybierz wpis Hints z items[].cpro_account.vault_entry
według tabeli routingu: dla delivery_lead_id 14 wybierz konto Igora, a dla
27 lub 32 konto Marcina. W requeście Dominika zachowaj delivery_lead_id 32.
Zacznij od nowej odizolowanej sesji portalu
i potwierdź zalogowane konto względem wybranego wpisu przed jakimkolwiek
zapisem. Brak, nieznane albo niezgodne konto = skipped bez zmian w Cpro;
nie korzystaj z konta poprzedniej pozycji ani ze wspólnego wpisu Hints.
Dane do formularzy bierz wyłącznie z items. Plik CV każdej pozycji pobierz
z items[].offer.cv_url z nagłówkiem X-Run-Token: <token>.
W pilotażu zawsze zostaw szkic, także gdy submit = true lub task żąda wysyłki.
Do oferty wgraj firmowy PDF z NEXUSA. Sprawdź rozszerzenie .pdf, typ
application/pdf i sygnaturę %PDF-. Po Save otwórz ponownie ofertę i podgląd
wybranego PDF w Cpro. Sprawdź czytelność, firmową szatę i status DRAFT.
Jeśli edit_existing_draft_only=true, zmień wyłącznie CV w jednoznacznie
potwierdzonym istniejącym szkicu. Brak takiego szkicu wymaga raportu błędu.
Nie klikaj „Submit Offer”. Zgłaszaj draft tylko po potwierdzeniu DRAFT w Cpro.

Na koniec wyślij JEDNO żądanie:
POST {callback_url}
Content-Type: application/json
X-Run-Token: {token}
z treścią w kształcie report_format (bez dodatkowych pól, bez komentarzy).
Wyślij JSON bezpośrednio jako body, bez pliku raportu i bez próbnego POST.
Uznaj zapis za przyjęty dopiero po odpowiedzi NEXUSA ze statusem received.
GET zlecenia nie zużywa tokenu; przyjęty raport go unieważnia. Token jest ważny
tylko dla tego biegu do expires_at. Nie zapisuj go, pełnego wejścia, danych osób,
loginów ani plików CV w plikach, notatkach, pamięci ani logach.
```

3. Adres i klucz webhooka (pokazuje je tylko aplikacja desktopowa) od razu jako
   sekrety repo `GROK_BOT_CPRO_WEBHOOK_URL` i `GROK_BOT_CPRO_WEBHOOK_KEY`.
4. **Zgody w bocie:** przy pierwszej karcie zgody na
   `GET https://api.nexus.dynaminds.pl/api/integrations/cpro-bot/runs/…/task`,
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
requestu, `data_from`. Karta musi mieć obsługiwanego, aktywnego DL rekrutacji
i odpowiedni wpis Hints. Wybierz jedną kartę `ready` (`stage_id`) i zleć próbę
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
Sam licznik `draft` nie zastępuje kontroli DRAFT w portalu: w próbie NEXUS
normalizuje zgłoszony przez bota wynik `submitted` do `draft`.

Nie przeszło (`expired`, `failed`, `counts.failed` albo `counts.skipped`):
przeczytaj `report->'items'`
(`reason`, `message`) i historię biegu w Grok Bocie; najczęściej karta zgody
albo logowanie (`login_failed`).
`account_unknown`, `account_unverified` albo `account_mismatch` oznacza
pominięcie bez zapisów przy wyborze lub weryfikacji konta. Nie ponawiaj
na innym koncie i nie usuwaj blokady przez zmianę DL tylko dla próby.
W publicznych logach zostają same liczby i identyfikatory; bez loginów,
haseł, tokenów i treści danych kandydatów.

## 4a. Interaktywny szkic jednej karty bez webhooka

Tryb tworzy **zlecenie szkicu**, nie gotowy DRAFT. Wymaga wyłączonego
`CPRO_BOT_ENABLED`, jednej karty `ready` oraz potwierdzenia DL i requestu
jej rekrutacji. Nie łącz go z `--start` ani `--submit`. Request pozostaje
tekstem (4–7 cyfr), także gdy zaczyna się zerem.

Przed uruchomieniem musi istnieć chroniony odbiornik: otwarta natywna karta
**secret request** Grok Bota, zapisująca wartość do swojej zmiennej środowiskowej,
oraz zaufany most do jej secure text field. W procesie rodzica **wewnątrz
kontenera** most tworzy anonimowy pipe i przekazuje CLI deskryptor zapisu
`>=3`. CLI sprawdza kanał przed utworzeniem biegu; odrzuca plik, terminal,
niepołączony socket, kanał tylko do odczytu i alias stdin/stdout/stderr.
Argumenty uruchamiane przez most (ID podstaw z gotowej karty):

```text
python -m scripts.cpro_bot_run --interactive-draft --stage-ids <jeden_stage_id> --delivery-lead-id <id_DL_requestu> --request-number <numer_requestu> --token-fd 3
```

Prywatny FD zwraca tylko świeży token ASCII z końcowym LF. Rodzic odczytuje
go i natychmiast szyfruje efemerycznym kluczem publicznym odbiorcy:
RSA-OAEP, SHA-256 oraz MGF1 SHA-256. Między kanałami przenosi wyłącznie
szyfrogram; odbiorca odszyfrowuje w pamięci, usuwa końcowy LF i wprowadza
wartość bez schowka do właściwego chronionego pola. Żadnych plików,
plaintext w argumentach, logach ani czacie. SSH i `docker exec` działają bez
TTY; most zapewnia rzeczywiste rozdzielenie kanałów, nie `3>&1` / `3>&2`.
Bez gotowego mostu i właściwego secret request nie twórz biegu.

Stdout zawiera tylko stan, `run_id`, `submit=false`, `items=1`. Sam zapis
FD nie potwierdza odbioru w secret request. Błąd dostarczenia w CLI zamyka
warunkowo nowy otwarty bieg jako `failed` i unieważnia token. Nie ma odzysku
starego tokenu; nie ponawiaj automatycznie po niejednoznacznym wyniku mostu.
Po potwierdzeniu odbioru pobierz `/runs/{run_id}/task` według reguł schematu 2,
zapisz ofertę jako DRAFT na właściwym koncie DL i sprawdź otwarcie CV.
Wyślij raport `draft`, potwierdź `received` i oddaj szkic Sandrze do oceny.
Nie klikaj „Submit Offer” ani „Wrzucone” w NEXUS; flaga pozostaje wyłączona.

Żeby poprawić CV w istniejącym szkicu, do tego samego polecenia dodaj
`--repair-draft-run-id <id_biegu_z_potwierdzonym_DRAFT>`. Podaj tę samą
kartę, Delivery Leada i numer requestu. Bot ma otworzyć wskazany DRAFT,
zaznaczyć nowy PDF jako jedyne CV oferty i sprawdzić podgląd po zapisie.
Do kolejnej gotowej karty użyj osobnego biegu bez opcji korekty.

## Szkic z kolejki w zalogowanej przeglądarce

Przy wyłączonych obu flagach uprawniony operator może obsłużyć jedną gotową
kartę z okna „Do wrzucenia do Cpro” w NEXUSIE. Ten tryb korzysta ze zwykłej
sesji NEXUSA. W Cpro potrzebna jest aktywna sesja na koncie wskazanym przez
panel. Dla requestów Marcina i Dominika jest to konto Marcina. Admin, Head
of Recruitment i Delivery Lead z prawem zapisu w Pipeline mogą też
otworzyć tę samą kolejkę przez **Ustawienia →
Rekrutacja → CPro → Otwórz kolejkę Cpro**.

1. Otwórz przygotowanie szkicu przy wybranej osobie. Sprawdź konto i numer
   requestu. NEXUS rezerwuje kartę i udostępnia zatwierdzony firmowy PDF.
2. W Cpro sprawdź nazwę profilu, otwórz właściwy request i wyszukaj osobę
   w **Our offers**. Wróć do istniejącego szkicu, jeśli już powstał. Przy
   kilku pasujących ofertach, innym statusie albo niejasnym wyniku zapisu
   zatrzymaj pracę i sprawdź listę ofert z operatorem.
3. Zapisz DRAFT z firmowym PDF. Otwórz ponownie ofertę z **Our offers**,
   sprawdź jej identyfikator, status DRAFT i podgląd wszystkich stron CV.
4. W tym samym panelu NEXUSA wpisz identyfikator oferty i potwierdź oba
   sprawdzenia. Dopiero wtedy powstaje raport szkicu. Sandra może ocenić
   ofertę w Cpro. Karta pozostaje w kolejce.

Po przerwie otwórz zarezerwowaną kartę z tego samego konta NEXUSA i sprawdź
stan oferty w Cpro przed kolejną czynnością. Jeśli po wygaśnięciu próby
na właściwym koncie i requeście nie ma oferty tej osoby, właściciel może
odnotować to i zwolnić rezerwację w panelu. Nową próbę uruchamia się osobno.
Potwierdzenie w panelu jest
zapisem obserwacji operatora. Samo otwarcie panelu lub pobranie PDF nie
potwierdza zapisu w portalu.

## Automatyczne szkice do oceny Sandry

Zanim skierujesz kolejkę produkcyjną do rutyny, sprawdź logowanie bez udziału
operatora dla właściwego konta DL. W pilotażu z listopada 2026 Vault Groka
udostępniał logowanie Igorowi i Marcinowi w interaktywnej rozmowie. Bieg
webhookowy zatrzymywał się przed zalogowaniem. Sam zapis obu haseł w Vault
nie potwierdza działania w tle. Gdy portal wymaga pomocy, rutyna zgłasza
problem i kończy tę próbę bez zapisu oferty.

W workflow „Coolify set env” ustaw `CPRO_BOT_AUTO_DRAFT_ENABLED=true`
przy `CPRO_BOT_ENABLED=false`. Po wdrożeniu worker sprawdza kolejkę co pięć
minut. Wybiera pojedynczą gotową kartę, sprawdza jej Delivery Leada i zleca
szkic z firmowym PDF. Osoby z wcześniejszym potwierdzonym szkicem lub wysyłką
pomija. Sandra znajdzie status i odnośnik do zapisanej oferty w „Do Cpro”.
Karta pozostaje na tym etapie do decyzji człowieka.

Odbiór produkcyjny wymaga automatycznego biegu z `submit=false`, raportu
z wynikiem `draft` i statusem `DRAFT` po ponownym otwarciu oferty przez
bota. Sprawdź również kolejny cykl workera pod kątem duplikatów. Wyłączenie
automatycznych szkiców wymaga ustawienia `CPRO_BOT_AUTO_DRAFT_ENABLED=false`.

## 5. Przyszła pierwsza wysyłka i włączenie (wyłącznie Artur)

Obecny pilotaż kończy się na szkicu i ocenie Sandry. `CPRO_BOT_ENABLED`
pozostaje `false`; Codex nie uruchamia `--submit`. Poniższe kroki Artur
wykonuje dopiero po akceptacji szkicu przez Sandrę, po sprawdzeniu konta
Igora/Marcina właściwego dla tej rekrutacji.

1. Po ocenie Sandry i odrębnej decyzji Artura wyłącz tryb automatycznych szkiców,
   który wymusza DRAFT przy obu flagach. Zmień w rutynie zasadę „zawsze szkic”,
   zachowując weryfikację konta. Dopiero wtedy wyślij tę samą kartę:
   `python -m scripts.cpro_bot_run --start --stage-ids <stage_id> --submit`.
   Oczekiwane: `counts.submitted = 1`, `counts.moved = 1`, w Cpro status
   SELECTION, w NEXUSIE karta na „Wysłane do Cpro”.
2. `CPRO_BOT_ENABLED=true` workflowem „Coolify set env” i wdrożenie.
   Od tej chwili pętla co 5 minut bierze karty bez braków. W oknie „Do
   wrzucenia do Cpro” przy każdej osobie widać stan bota, a nad listą
   „Bot Cpro · … · wysłane dziś: N”.
3. Wyłączenie awaryjne: `CPRO_BOT_ENABLED=false` (Coolify set env) — pętla
   staje, ręczne „✓ Wrzucone” działa jak przed botem.
