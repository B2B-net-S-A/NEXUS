# Czat rekrutacji: dzwonek o wiadomości tylko dla przypisanych

Zgłoszenie z 18.11.2026 (zrzut czatu „Czat zespołu · zespół 12”):
powiadomienie o wiadomości na czacie requestu ma przychodzić tylko do osób
przypisanych do requestu.

- **Odbiorcy `job_chat_message`** (dzwonek, dymek na żywo i mail zastępczy,
  który bierze się z tych samych wierszy) to `list_job_assigned_ids`:
  rekruter prowadzący, Delivery Lead, osoby z aktywnym przypisaniem, ręcznie
  dodani współpracownicy, plan priorytetów i zastępca za nieobecnego.
  Poza autorem.
- **Nie dostają go:** admini spoza zespołu, uczestnicy kategorii (`auto_cc`)
  i „Poprzedni rekruterzy”. Wcześniej lista szła z `list_job_member_ids`
  (z adminami i `auto_cc`), czyli „zespół: N” z nagłówka czatu — stąd
  dzwonki u osób, które nad rekrutacją nie pracują.
- **Wzmianka działa jak dotąd:** oznaczona osoba (także admin spoza zespołu)
  dostaje `job_chat_mention`. Nie dostaje wtedy dodatkowo `job_chat_message`,
  jeśli nie jest przypisana.
- **Czat widzą dalej wszyscy członkowie** (`is_member_of_job`, nagłówek
  „zespół: N”, rozgłoszenie `chat:message:new` do otwartego okna). Zmiana
  dotyczy tylko powiadomień, nie dostępu.
- Ta sama lista co `@wszyscy` → `wzmianka-wszyscy-przypisani-do-rekrutacji.md`.
  Nie zamieniaj jej z powrotem na `list_job_member_ids`.

Test: `tests/test_job_chat.py::test_new_message_notifies_only_assigned_people`.
