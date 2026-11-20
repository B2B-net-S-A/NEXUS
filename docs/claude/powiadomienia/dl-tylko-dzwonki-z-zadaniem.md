# Delivery Lead dostaje dzwonek tylko wtedy, gdy ma coś do zrobienia (19.11.2026)
<!-- indeks: wariant A, bez „CV wysłane” do DL-a od karty w „Nowych”, DL nie jest zapasem digestu, aplikacji z portalu i „Podobnego requestu”, P0 i terminy bez DL-a, informacja o stawce bez DL-a, co zostaje z wcześniejszą decyzją -->

Decyzja Artura z 19.11.2026: „DL też ma tylko dostawać info jak jest coś dla
niego do zrobienia, inaczej nie”. Wcześniej tego dnia: „nie chcemy żeby ktoś
miał powiadomienia jak to nie jego kandydat” (#3627, dzwonek Matcha). Inwentarz
dzwonków DL-i z 14 dni (kopia produkcji z 19.11, okno 06–19.11): pięć kont
„tylko DL” dostało 2 055 dzwonków, z czego 664 (32%) to czysta informacja.
Tabela, makieta dnia i warianty: https://claude.ai/artifact/LnCzRCcBjRwMbqt5xmsf4s.
Wybrany wariant A: wyciszyć informacje, które nie miały wcześniejszej decyzji.

## Co już do DL-a nie idzie

- **„CV wysłane: <osoba>”, gdy DL tylko wstawił kartę do „Nowych”** (Match,
  „Wyślij też do”), a CV wysłał rekruter. `stage_handoff_recipients.handoff_recipients`
  pomija osobę z `_handed_over_by`, jeśli to DL rekrutacji (`_dl_reviewers`),
  karta przed „CV wysłane” stała w „Nowych” (`_card_added_to_new`) i DL nie
  jest rekruterem kandydata. 206 dzwonków w 14 dni, w 203 DL był autorem karty
  w „Nowych”. DL, który przeprowadził screening albo weryfikację, dostaje
  dzwonek dalej (przekazał kartę do wysłania).
- **DL nie jest zapasem za brak prowadzącego:** „Top dopasowania tygodnia”
  (`match_digest._digest_recipients`, 181), „Nowa aplikacja z JustJoin.IT /
  RocketJobs” (`portal_application.notify_recruiter`, 90) i „Podobny request —
  gotowi kandydaci” (`similar_job_notify._recipients`, 8; DL nie dostaje go też
  jako twórca rekrutacji). Bez pracującego prowadzącego nie dostaje ich nikt.
  Rekrutację bez rekrutera zgłasza tygodniowy wpis „N osób czeka, przypisz
  rekrutera” (`kandydat-utknal-jeden-wpis-na-rekrutacje.md`), a karty z portali
  stoją w „Nowych” na Tablicy.
- **„P0: ultrapilne do …”** (`job_p0.team_recipients`, 19): dzwonek i mail
  obowiązkowy idą do rekruterów rekrutacji. DL widzi P0 na pulpicie i w pasku
  (`visible_to`), a prośbę o P0 składa sam. Zastępuje zdanie „i jej Delivery
  Leada” z reguły z 27.10 (`rekrutacja-tablica/p0-ultrapilne-24-h.md`).
- **„Deadline rekrutacji za N dni”** (`job_deadline_alerts._assigned_user_ids`,
  12): bez `jobs.delivery_lead_id`; DL ręcznie dopisany jako współpracownik
  dostaje go dalej.
- **„Zmiana stawki kandydata”, gdy zmiana nie czeka na decyzję**
  (`candidate_rate_change._recipients(requires_decision=False)`, 5). Zadanie
  „Kandydat podniósł stawkę po wysłaniu CV” zostaje. Zmienia D2 z 04.10
  (`screening-notatki/zmiana-stawki-kandydata-w-trakcie-procesu.md`); Head of
  Recruitment informację dostaje dalej.

DL, który jest też rekruterem rekrutacji albo kandydata, dostaje te dzwonki
jako rekruter. Typy w enumie zostają: wiersze sprzed zmiany muszą się dalej
wyświetlać. W 14 dniach przed zmianą wariant A zdjąłby 521 dzwonków u pięciu
kont „tylko DL” (25%).

## Co zostaje, bo miało wcześniejszą decyzję

Informacje, które idą do DL-a nadal; zmiana każdej to nowa decyzja Artura:

- „Pominięta uwaga blokująca QC” i „Przesunięte mimo uwag QC” (`cv_qc.py`, D5,
  `rekrutacja-tablica/qc-to-nieprawda-i-jakosc-qc.md`), 35 w 14 dni.
- „Prep zaplanowany / przyjęty / oceniony” (`prep_notifications.py`, 0453 na
  prośbę DL-a z 17.10), 64.
- „Nowa rekrutacja u Twojego klienta” (`client_job_opened`, decyzja 26.10:
  także gdy DL otworzył sam; `maile-obowiazkowe.md`), 22.
- „Debrief po rozmowie u klienta” — tylko gdy rekruter zaznaczy „Powiadom DL”, 16.
- „Profil Championa zaktualizowany” (N2 z 06.10: DL nadpisywał zmiany
  rekrutera nieświadomie), „Bliźniacza rekrutacja” i „Championi w rekrutacji”
  (`blizniacze-rekrutacje-jeden-screening-pod-kilka.md`), razem 4.
- Zgłoszenie z linku aplikacyjnego i strony kariery, gdy właściciel linku
  odszedł (`public_apply`, zapas „prowadzący, inaczej DL”): 0 u DL-i
  w 14 dniach, więc poza zakresem A.

„Rekrutacja zeszła z P1 / wróciła na P1” to dzwonek o własnym odpięciu
z rekrutacji, nie informacja dla DL-a jako DL-a. Ruchy etapów cudzych
kandydatów zdjął wcześniej #3570 (`ruch-etapu-do-rekrutera-kandydata.md`),
a dzwonek Matcha #3627 (`rekrutacja-tablica/dl-match-wyslij-tez-do.md`).

## Nowy dzwonek do DL-a

Zanim dopiszesz DL-a do odbiorców, nazwij czynność, którą ma wykonać
(przegląd, decyzja, odpowiedź klientowi, przydział). Bez niej DL nie jest
odbiorcą ani zapasem. Reguł etapów z odbiorcą „DL rekrutacji”
(`RecipientType.job_delivery_lead`) na kopii produkcji z 19.11 nie było
(10 aktywnych, wszystkie „rekruter rekrutacji”).

Testy: `tests/test_dl_bells_only_tasks.py`.
