# Dzwonek przy przekazaniu karty: QC → DL, CV wysłane → rekruter (02.10.2026)

Zgłoszenie z testów: rekruter przesunął kandydata na „QC CV”, Delivery Lead
wysłał CV do klienta i nikt nie dostał powiadomienia. Reguły etapów
(`stage_notification_rules`, 0066) są przypięte do wiersza definicji etapu
i zasiane raz, w kwietniu — „QC CV” (0361) nie ma żadnej, a „CV wysłane”
znało tylko `jobs.recruiter_id` (osobę z automatu przydziału albo nikogo).

- **Trzy przekazania działają bez reguł** (`services/stage_handoff_recipients.py`,
  wpięte w `stage_notification_resolver.resolve_recipients`): „QC CV” poza
  Nordeą → Delivery Lead rekrutacji (lustro `board_tasks._sees_dl_review`:
  aktywny DL z rekrutacji, bez niego DL-e z portfelem klienta); kolejka Cpro
  u Nordei → osoba od Cpro (firmowa, bez niej zapasowa rekrutacji); „CV
  wysłane” → rekruter kandydata (`interview_slots.default_recruiter_id`:
  właściciel procesu → pierwszy weryfikator → prowadzący rekrutację) ORAZ
  osoba, która przekazała kartę do wysłania (autor poprzedniego ruchu, gdy
  karta stała w kolumnie sprzed „CV wysłane” — bywa nią ktoś inny niż pierwszy
  weryfikator). Tylko dzwonek, nigdy mail; osoba, która sama przesunęła kartę,
  nic nie dostaje; ruch wstecz nie powiadamia — z dwoma wyjątkami niżej.
- **Zwrot z kolejki Cpro do „QC CV” (Nordea) dzwoni do osoby, która kartę
  tam przekazała** (`REASON_CPRO_RETURNED`); resolver pomija wtedy reguły
  etapów, a zwykłe cofnięcie karty dalej nikogo nie powiadamia.
- **Karta cofnięta z „QC CV” do wcześniejszej kolumny poza Nordeą**
  (`REASON_QC_RETURNED`, 03.10.2026 — „Wróć do poprawy” w przeglądzie DL albo
  przeciągnięcie) dzwoni do osoby, która przekazała ją do QC, i do rekrutera
  kandydata: „Wróciło do poprawy”, z uwagą Delivery Leada, gdy ją zostawił.
  Oba zwroty to `BACKWARD_REASONS` — jedyne przekazania będące ruchem wstecz.
- **Zadanie ≠ informacja o ruchu (0408).** Przegląd DL, kolejka Cpro i oba
  zwroty do poprawy (`TASK_REASONS`) idą typem `board_task_waiting` — kategoria
  „Wzmianki”, której nie da się wyciszyć, bo na odbiorcę czeka kandydat.
  „CV wysłane” zostaje przy `stage_rule` („Ruchy w rekrutacjach”, do
  wyciszenia). Resolver sprawdza dostęp odbiorcy typem JEGO dzwonka — do 0408
  Delivery Lead z wyciszonymi ruchami nie widział próśb o przegląd.
- **Etapy-odznaki bez reguły też dzwonią** (`REASON_STAGE_REACHED`):
  „Preparation Meeting”, „Umowa wysłana” i „Umowa podpisana” (rozpoznawane
  po nazwie jak na Tablicy — `stage_badge_kind` `prep` / `contract_sent` /
  `contract_signed`, także odpowiedniki z szablonów Traffita) → prowadzący
  rekrutację, rekruter kandydata i Delivery Lead rekrutacji. To informacja
  (`stage_rule`, do wyciszenia), nie zadanie.
- **Reguła „Rekruter projektu i kandydata” (`job_recruiter`)** powiadamia
  prowadzącego rekrutację ORAZ rekrutera kandydata — na każdym etapie
  z regułą (rozmowa u klienta, akceptacja, odrzucenie…).
- Encja = wiersz etapu, a resolver scala odbiorców po osobie, więc reguła
  i przekazanie dla tej samej osoby dają jeden dzwonek. Treść przekazania mówi, co zrobić,
  i prowadzi na Tablicę z otwartą osobą (`/jobs/{id}?candidate=`).
- Nowy etap-przekazanie = gałąź w `handoff_kind` (po KOLUMNIE Tablicy, nie po
  id definicji), nie nowy wiersz reguły — reguły nie dochodzą do etapów
  dodanych po zasiewie ani do szablonów z Traffita.
- **Kolejka Cpro prowadzona w Traffit też dzwoni (08.10.2026, decyzja Artura).**
  Pomiar: 122 wejścia na „NORDEA: Wysłać do Cpro” w 14 dni, wszystkie
  w Traffit — import pisze surowym SQL-em, więc osoba od Cpro nie dostała ani
  jednego dzwonka. Po fazie `pipelines` (`traffit_sync._pipelines_phase`)
  `services/cpro_queue_reminder.py` liczy STAN: pary, których najnowszy wiersz
  to zaimportowany etap kolejki Cpro u klienta z kolejką Cpro, z ostatnich
  `TRAFFIT_CPRO_REMINDER_WINDOW_DAYS` (7) dni. Jedno `board_task_waiting` na
  osobę na dzień (encja = odbiorca), mail od razu jak przy `dl_review`, tylko
  w dni robocze. Nie rób z tego dzwonka na każdy zaimportowany wiersz — przy
  imporcie nocnym 93 ze 122 kart były już wysłane. Wyłącznik
  `TRAFFIT_CPRO_REMINDER_ENABLED`.
