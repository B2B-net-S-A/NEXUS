# Nazewnictwo: „Rekrutacja", nie „Oferta" (moduł `/jobs`)

Sekcja `/jobs` nazywa się w UI **„Rekrutacje"** (do 2026-08-10 część powierzchni
mówiła „Oferty", część już „Rekrutacje" — rail otwartych kart, zakładka profilu
kandydata). Ujednolicone: w interfejsie i w komunikatach API zlecenie
rekrutacyjne to **rekrutacja**.

- **Warstwa techniczna zostaje po angielsku** — route `/jobs`, `/api/jobs`,
  tabela `jobs`, kolumny `job_id`, nazwy plików (`JobsListV2.tsx`). Tak jak
  `/candidates` przy „Kandydaci". Nie zmieniaj URL-i: powiadomienia mają
  `link="/jobs/{id}"` **zapisane w bazie** (`job_deadline_alerts.py`,
  `job_chat.py`, `activities.py`) — zmiana routingu zepsułaby historyczne wpisy.
- **Słowo „oferta" ZOSTAJE tam, gdzie znaczy co innego** i nie wolno go tykać:
  etap pipeline'u złożenia propozycji kandydatowi (`offer_sent`,
  `offer_accepted`, „Oferta wysłana/zaakceptowana", „Wycofał się PO akceptacji
  oferty"), status kandydata `open_to_offers` („Otwarty na oferty"), szablon
  maila „Oferta współpracy", oferty handlowe w dynareporterze, oraz treść maila
  wychodzącego do kandydata („Oferta pracy: {tytuł}" — odbiorcą jest kandydat,
  nie rekruter).
- **Prompty LLM (`services/llm_prompts.py`) celowo nietknięte** — „Kontekst
  oferty:" zostaje. Zmiana treści promptu zmienia zachowanie modelu i
  unieważnia cache oparty o hash promptu, bez zysku dla użytkownika.
