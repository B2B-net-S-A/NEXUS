# Bliźniacze rekrutacje — jeden screening pod kilka (0615, 28.10.2026)
<!-- indeks: kto łączy (DL swoje, HoR/admin wszystko, też między klientami), kind='twin' w job_similar_links, pary pytań, bramka „Zweryfikowany” z pominięciem z powodem, stawka w budżecie, KPI osobno, bez kopiowania wcześniejszych, kafel „Otwarte podobne” -->

Propozycja Olafa (HoR) z 28.10.2026: „bliźniaczy request” — tak podobny, że
kandydaci weryfikują się od razu na oba — i „Podobne requesty P1”. Decyzje
Artura z 28.10.2026, makiety: https://claude.ai/artifact/83ybsjjmstNhKAzHYNraFw.
Serwis `services/job_twins.py`, trasy `api/job_twins.py`, DDL
`services/job_twin_schema.py` (migracja 0615 + lustro w `entrypoint.sh`).

- **Bliźniak to rodzaj połączenia podobnych rekrutacji**: wiersz
  `job_similar_links` z `kind = 'twin'`, w obu kierunkach, z parami pytań
  (`question_pairs`, z perspektywy wiersza `{"own", "other"}`). Bliźniak jest
  też „podobny” (hak przepięć `on_candidate_sent` działa jak dotąd). „Rozłącz”
  wraca do `similar` i nikogo nie zdejmuje.
- **Kto łączy:** Delivery Lead swoje otwarte rekrutacje (`job_delivery_leads`
  obu stron), także u różnych klientów; Head of Recruitment i admin — dowolne
  otwarte. Rozłącza DL którejkolwiek strony, HoR, admin. Rekruter nie łączy
  (403 `twin_forbidden`). Reguła siedzi w serwisie — macierz authz widzi tylko
  `RecruiterPlus`, pilnuje `test_job_twins.py`.
- **Limit: 3 bliźniaki na rekrutację** — kotwica + 3 to tyle, ile mieści jedna
  rozmowa w „Screening dla” (`JOINT_MAX_OTHERS`). Zamknięta rekrutacja nie
  zostaje bliźniakiem (422 `twin_closed`).
- **Bez kopiowania.** Osoby zweryfikowane przed połączeniem zostają tam, gdzie
  są (decyzja Artura — nie „od razu na Zweryfikowany”); okno łączenia mówi,
  ilu to dotyczy. Połączenie działa od teraz.
- **Pary pytań** potwierdza łączący w oknie „Połącz bliźniaka”. Podpowiedź
  (`suggest_question_pairs`): ten sam tekst albo wspólne słowa treści ≥ 0,2,
  jeden do jednego; pytania o stawkę, dostępność i tryb pracy tylko po tym
  samym tekście. Powód: reguła tekstu ze „Screening dla” łączyła 0 z 8 pytań
  pary ZOB-2947 ↔ ZOB-2964, a próg 0,2 daje dokładnie trzy pary, które zespół
  uznał za to samo (DDD, stack, OpenShift). Pary mają pierwszeństwo w
  `screening_question_groups.group_questions(…, pairs)`.
- **Bramka „Zweryfikowany”** (`assert_twin_screening` w `/move` i
  `/bulk-move`, po bramce arkusza): wejście z Nowych/Screeningu wymaga, żeby
  w każdym bliźniaku osoba miała screening tej próby, stała na „Zweryfikowany”
  albo dalej, miała kartę zamkniętą (odrzucenie, rezygnacja), albo aktywny
  konflikt u klienta bliźniaka (czarna lista, NDA). Inaczej 409
  `TWIN_SCREENING_REQUIRED` z listą bliźniaków. Pominięcie z powodem
  (`twin_skips`: rekrutacja → `client_rejected` | `client_conflict` |
  `candidate_declined` | `other`) przepuszcza i zostawia `Activity
  job_twin_skipped`. Ruch zbiorczy powodów nie zna — bramka bez wyjątku.
  Bliźniaki, w których patrzący nie jest w zespole (`ensure_job_membership`),
  bramka pomija: tam nie zapisze ani nie przesunie osoby (zespoły bliźniaków
  na stagingu 28.10 pokrywały się w całości albo w 6 z 7 osób).
- **Stawka:** jedna; inna tylko wtedy, gdy bliźniaki mają inny tryb pracy
  (np. 2 i 3 dni z biura). W rekrutacji z bliźniakiem stawka kandydata ponad
  budżet się nie zapisze (`assert_rate_within_budget` w `PUT
  /screening-form`, 422 `twin_rate_over_budget`, przeliczenie
  `hourly_from_unit`). Bez budżetu — bez limitu. Pojedynczy screening bez
  bliźniaka zostaje z ostrzeżeniem (decyzja Artura: blokada tylko przy
  bliźniakach). Front pokazuje przy stawce tryb pracy i budżet każdej
  rekrutacji (wariant A — tabela pod polem).
- **Liczenie:** weryfikacja liczy się osobno w każdej rekrutacji — cel, Liga
  i KPI bez zmian (jak D4 wspólnego screeningu z 14.10). Poranny pomysł „raz
  na grupę” Artur odrzucił.
- **Kafel „Otwarte podobne”** w pasku „Kandydaci do dodania” (`GET
  /jobs/{id}/open-similar`): tylko otwarte w pracy, P1 (urgent/high) na
  górze, potem wektor; „⇄ Bliźniak” tylko przy tych, które patrzący może
  połączyć. Zamknięte zostają w „Podobnych rekrutacjach” (przepięcia).
  Olafowe „P1” przyjęte jako „otwarte, P1 na górze” — z Olafem niepotwierdzone.
- **HoR i admin: „⇄ N możliwych bliźniaków”** (`GET /job-twins/suggestions`):
  pary otwartych rekrutacji z wektorem ≥ 0,80 i RÓŻNYMI Delivery Leadami
  (DL nie widzi cudzych), jeszcze nie połączone i nie odrzucone. „To nie
  bliźniak” zapisuje parę w `job_twin_dismissals` na stałe. Pamięć listy
  5 min w procesie. Staging 28.10: 7 takich par między klientami (Analityk
  Systemowy PKO BP ↔ Alior), 70 osób już ręcznie w obu.
- **Dzwonek `job_twin_linked`** przy nowym połączeniu: rekruterzy i DL-e obu
  rekrutacji (`job_champions.recipients`) poza łączącym, link do ich
  rekrutacji, kategoria „Ruchy w rekrutacjach”, bez maila.
- **Gdzie na ekranie (front, 29.10.2026):**
  - kafel „Otwarte podobne” i chip „⇄ ZOB-2964 · 3 pary” stoją w pasku
    „Kandydaci do dodania”, zaraz po „Podobnych rekrutacjach”. Chip w rzędzie
    tytułu przy 1280 × 720 łamał się i nachodził na „Tablicę” (zrzut ze
    stagingu) — dlatego nie ma go w nagłówku i nie ma tam „Połącz bliźniaka”;
    łączy się z kafla, a pary pytań poprawia z chipu;
  - okno „Połącz bliźniaka” (`twins/TwinLinkDialog`): klient i DL, tryb pracy,
    budżet, liczba osób, pary pytań z listą wyboru, „N pytań zamiast M”;
  - `/jobs/new`: „Czy to bliźniak którejś z Twoich rekrutacji?”
    (`GET /api/job-twins/candidates`, najwyżej 3, nic zaznaczone samo);
    połączenie po utworzeniu, bez par pytań (nowa rekrutacja nie ma jeszcze
    Profilu Championa);
  - lista rekrutacji: „⇄ N możliwych bliźniaków” (HoR, admin);
  - „Screening dla”: bliźniak zaznaczony z kłódką, brakujący bliźniak
    z „+ Dodaj do bliźniaka”; stawka jako tabela (rekrutacja · tryb pracy ·
    budżet · stawka), osobne pole tylko dla innego trybu pracy; zapis
    najpierw wszystkich par, potem ruchy (bramka kotwicy czyta screening
    zapisany w bliźniaku);
  - odmowa `TWIN_SCREENING_REQUIRED` na Tablicy i w panelu osoby: okno
    `TwinSkipDialog` (powód z listy → ten sam ruch z `twin_skips`).
- **„Nie bierze udziału w tej rekrutacji…” (prośba Artura 29.10.2026).** Przy
  bliźniaku w „Screening dla” (także brakującym) rekruter wybiera powód z tej
  samej listy co okno odmowy (`TWIN_SKIP_REASONS` w `lib/job-twins-api.ts` =
  `job_twins.SKIP_REASONS`, pilnuje `test_job_twins.py`). Bliźniak wypada
  z rozmowy (bez kłódki, „Cofnij” przywraca), a powód idzie z ruchem na
  „Zweryfikowany” jako `twin_skips` — z formularza wspólnego i pojedynczego —
  i zostaje w Historii zdarzeń. Pominięcie dotyczy tej rozmowy; nie
  zapisujemy go na stałe przy osobie.

## Zasady bliźniaków w Ustawieniach (decyzje Artura 29.10.2026)

Pytanie Olafa: „Mogę zmodyfikować warunki matchowania bliźniaków?”. Makieta:
https://claude.ai/artifact/QTD7Sk3jBqL386Jq5LYs6m. Serwis
`services/job_twin_rules.py`, ekran Ustawienia → Rekrutacja → „Zasady
bliźniaków” (`/settings/twin-rules`, `components/settings/TwinRulesSettings`).

- **Jedno ustawienie dla całej firmy** w `app_settings` (klucz
  `job_twin_rules`), zmieniają Head of Recruitment i admin (`PUT
  /api/job-twins/rules`, inni 403), odczyt DL/HoR/admin. Każdy zapis zostawia
  `Activity job_twin_rules_changed` z różnicą przed/po. Zły wpis = zasady
  startowe (nigdy wyłączone bliźniaki).
- **Tryby:** „Wymagane” TYLKO filtruje listę „Możliwe bliźniaki” (decyzja
  Artura) — w kaflu „Otwarte podobne” para dostaje „✕ …”, a w oknie łączenia
  „Zgodność z zasadami” z notą; ręcznie połączyć wolno. „Ostrzeżenie” = „⚠ …”
  przy parze i w oknie. „Wyłączone” = zasada nie działa.
- **Zasady startowe (jak w makiecie):** podobieństwo od 80% (pole 70–95,
  pula listy liczona od 70%), krytyczne wymagane, różni DL wymagane (tylko
  lista HoR), wymagania ≥ 50% / lokalizacja / tryb pracy / budżet ± 10 zł/h
  jako ostrzeżenia, klient i kategoria wyłączone. Do tego najwięcej
  bliźniaków na rekrutację (1–3), pozycje kafla (4–15) i śmiałość podpowiedzi
  par pytań (0,3 / 0,2 / 0,15).
- **Jak liczone:** krytyczne (`critical_skills.effective_critical`) i
  wymagania (`job_explicit_must_skills`) porównuje się po tekście albo po
  rdzeniach słów (5 liter) — „analiza systemowa” ≈ „Analityk Systemowy”
  dopiero z opcją „szukaj też w tytule”. Miasta z wolnego tekstu lokalizacji
  tylko z listy znanych miast (`KNOWN_CITIES`), bo lokalizacja bywa zdaniem
  („Sporadycznie, 1-2 dni w miesiącu…”). Poziom (seniority) pominięty: pusty
  w 138 z 138 rekrutacji z par na kopii z 22.10.
- **Podgląd przed zapisem** (`POST /api/job-twins/rules/preview`): ile par
  od progu spełnia zasady wymagane, ile z ostrzeżeniem, ile możliwych
  bliźniaków teraz i po zapisie, licznik „spełnia N z M” per zasada
  i przykłady par, które wypadną albo dojdą. Pomiar na kopii z 22.10 (53 pary
  od 80%): krytyczne 46, lokalizacja 35, tryb pracy 29, budżet 43, klient 46,
  różni DL 9; przy zasadach startowych 7 możliwych bliźniaków zamiast 9.
