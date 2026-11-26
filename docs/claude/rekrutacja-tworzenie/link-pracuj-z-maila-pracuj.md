# Link do Pracuj.pl z maila Pracuj.pl — bez wklejania (26.11.2026)
<!-- indeks: `job_ad/pracuj_inbox.py`, pętla `pracuj_mail_links`, `extranet@pracuj.pl`, „Publikacja ogłoszenia na …”, `groupId`, `from_mail`, `pracuj_mail_suggestions`, „To nie to ogłoszenie”, „To ta rekrutacja”, link z panelu `publikacja.pracuj.pl` / `strefa.pracuj.pl`, migracja 0793 -->

Zgłoszenie DL-a 26.11.2026: „za każdym razem trzeba ręcznie dodawać link do
Pracuja? Bo mi się nie zaciąga”. Do tego dnia tak — link wklejał człowiek
(decyzja z 27.10, `ogloszenie-pracuj-mailem-do-opiekuna.md`). Decyzja Artura
26.11.2026 (makiety https://claude.ai/artifact/KoLmrJj6VdA6sD4jbdGdRw):
wariant A — NEXUS bierze link sam, z zamianą linków z panelu.

Pomiar na produkcji 26.11: 96 z 96 linków wklejonych ręcznie; Pracuj.pl po
wstawieniu ogłoszenia wysyła z `extranet@pracuj.pl` mail „Publikacja
ogłoszenia na <tytuł>” z linkiem `www.pracuj.pl/praca?groupId=<id>`, a takich
maili było w NEXUSIE 59 (synchronizacja skrzynek DL-ów); `groupId` z maila był
tym samym, który DL wklejał potem ręcznie, a mediana opóźnienia ręcznego
oznaczenia to 50 h. 47 z 96 zapisanych linków prowadziło do panelu
pracodawcy, którego nikt bez logowania na konto firmy nie otworzy.

Kod: `services/job_ad/pracuj_inbox.py`, pętla `tasks/pracuj_mail_links.py`
(co 10 min), trasy `PUT/DELETE /api/jobs/{id}/portal-ad/pracuj-mail-links/{email_id}`
(`api/job_ads.py`), front `AdPublications.tsx`, harness
`/preview/job-ad?state=pracuj-mail`.

- **NEXUS czyta wyłącznie automatyczny mail Pracuj.pl** (nadawca
  `extranet@pracuj.pl`, temat „Publikacja ogłoszenia na …”, jeden `groupId`
  w treści). Korespondencji z opiekunem nadal nie czyta. Inne maile Pracuj.pl
  („… kończy się za 2 dni?”) mają link `,oferta,<nr>`, ale nie potwierdzają
  publikacji — nie bierz ich.
- **Oznacza sam tylko pewne dopasowanie:** mail w skrzynce osoby, która
  z NEXUSA wysłała prośbę do opiekuna najwyżej 14 dni wcześniej, OTWARTA
  rekrutacja bez aktywnego oznaczenia Pracuj.pl i dokładnie jedna taka rekrutacja z tym
  samym tytułem po `title_key` (bez dopisku płci „(k/m/x)”, liczby wakatów
  „x4”, rodzaju myślnika i spacji przy „/”). Tytuł porównuje się z nazwą
  rekrutacji i z tytułem ogłoszenia. Treść z blokującym znaleziskiem nie
  oznacza się sama. Maile idą od najnowszego: ponowna publikacja ma nowy
  `groupId`, więc wygrywa ostatni mail (staging 26.11: dwa maile „Tester
  Automatyczny” 20.11 i 24.11 do jednej rekrutacji). Okno pokazuje najwyżej
  jedną propozycję na rekrutację.
- **Reszta to propozycja w oknie** (`pracuj_mail_suggestions`): kilka
  rekrutacji z tym samym tytułem, jedyna prośba z tytułem podobnym w więcej
  niż połowie słów albo treść z blokadą. Mail, którego tytuł dokładnie pasuje
  do innej rekrutacji tej osoby (już oznaczonej albo zamkniętej), należy do
  niej i nie jest proponowany nigdzie indziej — ścieżka na stagingu 26.11
  pokazała po „To nie to ogłoszenie” przy „Tester” propozycję starszego maila
  „Tester Automatyczny” (strażnik w `test_job_ad_pracuj_inbox.py`). „To ta rekrutacja” oznacza (blokada = 409), „Nie” zapisuje
  odrzucenie. Rekruter widzi propozycję bez przycisków.
- **„To nie to ogłoszenie”** przy linku z maila usuwa wiersz oznaczenia
  (nikt go nie potwierdzał, przypomnienia wracają) i zapisuje odrzucenie pary
  rekrutacja–mail; ta para nie wraca ani jako oznaczenie, ani jako propozycja.
  Ręcznie wklejonego linku to nie rusza.
- **Ślad = Historia zdarzeń, bez nowej tabeli:** `job_ad_pracuj_link_from_mail`
  (`email_id`, `url`, `subject`, `received_at`, `mode` auto/confirmed) i
  `job_ad_pracuj_mail_rejected` (`email_id`). Z pierwszego okno składa
  „Link z maila Pracuj.pl z …” (`from_mail` przy publikacji, dopasowane po
  adresie). Link już użyty przy innej rekrutacji nie trafia do drugiej.
- **Pokrycie zależy od skrzynki:** Pracuj.pl pisze do konta, które zamawia
  ogłoszenie. DL bez podłączonej skrzynki albo z maili na innym adresie wkleja
  link ręcznie jak dotąd — nie dorabiaj zgadywania po samym tytule bez prośby.
- **Link z panelu pracodawcy (`clean_url`)**: `publikacja.pracuj.pl/showjoboffer/<id>`
  zapisuje się jako `www.pracuj.pl/praca?groupId=<id>` (ten sam identyfikator);
  inne strony `publikacja.`/`strefa.pracuj.pl` (podgląd, lista kandydatów,
  przekierowanie logowania z kodem w adresie) = 422 z podpowiedzią, skąd
  wziąć link. Migracja 0793 (lustro w `entrypoint.sh`,
  `job_ad_publication_schema.PRACUJ_PANEL_LINKS_DML`) zrobiła to samo ze
  starymi linkami; oznaczenie „opublikowane” zostaje, link znika.
- **Pętla działa na stagingu** (`STAGING_ALLOWED_TASKS`): czyta zapisane maile
  i pisze do bazy, bez Graph i bez wysyłek.
