# Proces u klienta: etapy po wysłaniu CV i czas zmierzony (18.11.2026)
<!-- indeks: `client_process` w JSON Championa poza sekcjami, PUT /api/jobs/{id}/client-process, GET /api/jobs/client-process (podpowiedź + mediany), fakt w nagłówku, pole w /jobs/new → Warunki -->

Decyzja Artura z 18.11.2026, wariant A z makiet
(https://claude.ai/artifact/5qHgBtJ8PrGb9wWN6yfwcj). Zgłoszenie z zespołu:
przy rekrutacji ma się dać wpisać długość procesu u klienta („jedna rozmowa
zdalna” albo „rozmowa + test do wykonania”). Do tej daty proces był tylko
wolnym tekstem w trzech miejscach (opis klienta, notatki AI w Championie,
stałe trzy linie ogłoszenia), a kandydaci skarżyli się na brak informacji
o terminie decyzji i kolejnym etapie.

- **Gdzie leży:** `champion_profile.client_process` = `{steps: [{kind,
  format, duration}], decision_workdays, set_by_id, set_by_name, set_at}`
  (`schemas/champion.py`: `ClientProcessIn`, `ChampionClientProcess`).
  Rodzaje etapów: rozmowa techniczna, z managerem, z klientem, zadanie do
  wykonania, test online, spotkanie w biurze; forma zdalnie / na miejscu;
  najwyżej 6 etapów, czas do 80 znaków, termin 1–60 dni roboczych.
- **To nie jest sekcja profilu.** Zapisuje go tylko
  `PUT /api/jobs/{id}/client-process` (bramka jak zapis Championa:
  `JobEditUser` + zakres DL + `ensure_champion_job_editor`) i
  `POST /api/jobs` z polem `client_process`. Zwykły `PUT …/champion-profile`
  go nie podrobi ani nie skasuje (`user_edit` scala tylko sekcje). Zapis nie
  przelicza dopasowań, nie robi wersji „Co się zmieniło” i nie budzi
  dzwonków Championa, bo proces nie mówi, kogo szukamy.
- **Poza odciskami:** klucz jest w `RANKING_IGNORED_KEYS` i
  `_NON_REQUIREMENT_KEYS` (`champion_view`), a `ChampionProfile.model_dump`
  zdejmuje `client_process: null`. Profile bez procesu mają ten sam skrót
  i odcisk co przed zmianą; zmiana procesu nie unieważnia pełnego przeglądu
  bazy (409).
- **Czas zmierzony** (`services/job_client_process.py`): pierwsze wejścia
  osoby w rekrutacji w „CV wysłane”, „Rozmowa u klienta” i decyzję
  („Akceptacja” albo „Zatrudniony”), u klienta, z 18 miesięcy, w dniach
  kalendarzowych; mediana dopiero od 5 decyzji, inaczej `measured: null`.
  Karta cofnięta wstecz nie daje ujemnego czasu. Tygodnie w nagłówku liczą
  się tylko z czasu zmierzonego, nigdy z deklaracji.
- **Podpowiedź:** `GET /api/jobs/client-process?client_id=&job_id=` zwraca
  `suggested` = proces najnowszej INNEJ rekrutacji klienta, która go ma
  (bramka odczytu jak lista rekrutacji). Nic nie wypełnia się samo: na
  `/jobs/new` pusta strona nie może zapisać formularza, więc podpowiedź ma
  „Użyj”.
- **Ekran:** czwarty fakt nagłówka „2 etapy · ~4 tyg.” / „proces: nie podano”
  (`JobClientProcessFact`), okienko z etapami, obietnicą klienta, paskiem
  „Jak jest naprawdę u …”, ostrzeżeniem, gdy decyzja trwa dłużej niż
  obietnica (×7/5 dni roboczych, zapas 20%), i zdaniem „Powiedz kandydatowi”
  z „Kopiuj”. „Zmień” / „Wpisz etapy” / „Użyj” tylko dla osoby edytującej
  Championa. Przy 1280 px fakt się nie kurczy; nazwa klienta ma minimum
  `min-w-28`, tryb pracy skraca się pierwszy (pełny tekst w dymku).
- **`/jobs/new`:** pole w „Warunkach” (`NewJobClientProcessField`), ten sam
  edytor (`ClientProcessEditor`). `IntakeForm.clientProcess` jedzie
  w autozapisie, a wpisany proces wyklucza „nietknięty formularz”
  (`isPristineIntake`), więc odczyt requestu go nie nadpisze.
- Przewodnik Jarvisa `job.champion` ma komplet pytań (5) i pułapek (4), więc
  tej funkcji nie opisuje; kolejny opis to decyzja, co z niego wyrzucić.
