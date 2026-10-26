# Mail „od razu” jak zadanie: temat, fakty i przyciski z gotową akcją (26.10.2026)
<!-- indeks: notification_mail_card.SPECS + build_card; render_card_email w email.py; ?do=&choose= w Rozmowach u klienta; ?leave=&decide= w Akceptacjach; nic z linku nie zapisuje się samo -->

Decyzja Artura z 26.10.2026 (PR 2 planu maili obowiązkowych, makiety
w `maile-obowiazkowe.md`): **same przyciski**. Bez
odpowiedzi mailem i bez kart Adaptive Cards w Outlooku — ramki „odpowiedz
1/2/ok” w makietach są nieaktualne. Zgody (`services/hr/approvals/mail.py`)
zostają ze swoim mailem i odpowiedzią „approved”.

## Wygląd

`services/notification_mail_card.py` składa kartę, `email.render_card_email`
ją rysuje (tabele i style inline, bo Outlook nie czyta CSS z nagłówka):

- temat `[NEXUS] co zrobić · czego dotyczy` (kandydat · klient, przy nowej
  rekrutacji tytuł · klient, w „Czasie i ludziach” osoba); każda część
  skracana osobno do 70 znaków;
- znaczek „Czeka na Ciebie” albo rodzaj sprawy;
- tytuł i opis z dzwonka, pod nimi do 4 faktów z tej samej sprawy
  (`load_facts`: rekrutacja, klient, Delivery Lead, termin, terminy od klienta,
  start kontraktora) — fakty są dodatkiem, ich błąd nie zatrzymuje maila;
- przyciski z gotową akcją;
- stopka „Ten mail przychodzi zawsze, bo ktoś czeka na Twój ruch.” dla
  `REQUIRED_KINDS`, inaczej „możesz wyłączyć sobie w Ustawienia → Moje konto”.

Nowy typ w kolejce „od razu” = wpis w `SPECS` (co zrobić, znaczek, przycisk);
pilnuje tego `test_every_bell_mail_type_has_an_action`. Typ bez wpisu (czat,
sprawy kadrowe bez decyzji) dostaje tytuł dzwonka jako „co zrobić” i jeden
przycisk do ekranu.

## Przyciski otwierają okno, nigdy nie decydują

Safe Links w M365 otwiera linki z maila, zanim zrobi to człowiek, a mail
przekazany dalej dawałby decyzję komuś innemu. Dlatego każdy parametr akcji
tylko otwiera okno potwierdzenia na ekranie (po zwykłym logowaniu) i znika
z adresu po obsłużeniu (F5 nie otwiera okna drugi raz):

- **Rozmowy u klienta**: `/calendar?cycle=<kandydat>-<rekrutacja>&do=<krok>`
  (`pick`, `confirm`, `reply`, `plan_prep`, `debrief`, `add_slots`), przy
  wyborze terminu `&choose=N` (od 1) zaznacza termin w oknie „Umów rozmowę
  i prepy”, ale tylko gdy `&req=<id wniosku>` zgadza się z otwartym wnioskiem
  pary — po nowych terminach od klienta „termin 2” ze starego maila to inna
  godzina (przegląd kodu 26.10.2026). Okno otwiera się tylko, gdy para stoi na tym kroku
  (`linkedStepAction`); inaczej panel pary i zdanie „krok już zrobiony albo
  czeka na kogoś innego”. Mail z terminami od klienta ma przycisk na każdy termin.
- **Akceptacje**: `/people/approvals?leave=<id>&decide=approve|reject` —
  wniosek zaznaczony, „Akceptuj” pyta oknem `useConfirmV2`, „Odrzuć” otwiera
  okno z powodem. Wniosek, o którym odbiorca nie decyduje, tylko się otwiera.
  Numer wniosku niesie link dzwonka `hr_leave_requested` od 26.10.2026
  (`leave_recipients.notify_requested(request_id=…)`); starsze wpisy mają sam
  `/people/approvals` i mail daje wtedy tylko „Otwórz akceptacje”.
- Reszta korzysta z parametrów, które ekrany już miały: przegląd DL
  `/jobs/{id}?candidate=…&review=1`, debrief `/calendar?cycle=…&debrief=…`,
  kontraktor bez zamówienia `/clients/{id}?tab=zamowienia&contract=…`
  (panel z „Uzupełnij zamówienie”).

Żaden przycisk nie prowadzi na `/api/**` (test `test_buttons_never_point_at_the_api`).

## Czas i ludzie

Tytuł i treść idą przez `hr_mail.mail_text` jak dotąd (bez rodzaju
nieobecności i kwot). Fakty tylko „Kto” i „Kiedy” wniosku o nieobecność —
fakty rekrutacji w mailu kadrowym nie pojawiają się nigdy.
