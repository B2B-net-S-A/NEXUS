# Praca nieobecnej osoby idzie do zastępcy (09.11.2026)
<!-- indeks: emit przekazuje wiersz zastępcy, CURRENT_WORK_TYPES / PERSONAL_TYPES, on_behalf_of_user_id, addressee_id w skanerach, kolejka DL za zastępstwem, DL za rekrutera -->

Zgłoszenie 09.11.2026: Delivery Lead dodał terminy od klienta, rekruterka była na
urlopie, a jej zastępca nie dostał ani dzwonka, ani maila. Silnik zastępstw
(`workforce_availability`) znał tę parę, ale przekazanie było wpięte ręcznie
w około 10 źródłach; ponad 50 pisało do osoby nieobecnej. Od 24.10 do 09.11 poszło
tak 376 powiadomień. Makiety i decyzje Artura:
https://claude.ai/artifact/JGLe9uz3RDwYsU7skyVZbR

- **Jedno miejsce.** `notification_triggers.emit` pyta
  `notification_substitution.notification_route`. Nie dopisuj przekazania
  u producenta. Dzwonek, dymek i mail idą za wierszem, więc też do zastępcy.
- **Każdy typ ma decyzję.** `CURRENT_WORK_TYPES` przechodzi, `PERSONAL_TYPES`
  zostaje u osoby (kadry, premie, godziny, własne konto, wzmianki, czat; Cpro
  i opieka mają własne zastępstwo). Nowy typ bez wpisu wywraca
  `tests/test_notification_substitution.py`.
- **Dzwonek o bieżącej pracy tylko u zastępcy** (decyzja Artura 02.11.2026).
  Wiersz nie zostaje u nieobecnej osoby. Autor akcji nie dostaje dzwonka o własnym
  ruchu: `ACTOR_KEY` ustawia `get_current_user`; pętle w tle nie mają autora.
- **`Notification.on_behalf_of_user_id`** (0675 + lustro w `entrypoint.sh`)
  pamięta, za kogo przyszło; ekrany i mail mówią „w zastępstwie za …”.
- **Skaner „już wysłano tej osobie” pyta o `Notification.addressee_id`,** nie
  o `user_id`. Inaczej po przekazaniu wysyłałby powiadomienie codziennie od nowa.
- **Zastępca widzi kolejki nieobecnej osoby:** `reviews_as_dl`,
  `reviewer_scope_clause`, `dl_review_portfolio`, `board_flow`, `cv_in_transit`,
  `cv_topic` liczą osoby przez `operational_owner_ids`. Pętla w tle musi wcześniej
  wywołać `workforce_context(db)`, bo bez niego ta funkcja zna tylko samo konto.
- **Kto może zastąpić** (`SUBSTITUTE_CAPABILITIES`, decyzja Artura 09.11.2026):
  rekrutera także Delivery Lead, Delivery Leada tylko Delivery Lead, bo rekruter nie
  wysyła CV do klienta. Formularz ostrzega przy parze, której silnik nie przyjmie
  (`substitute_role_gap`), zamiast zapisać zastępcę, który po cichu nie zadziała.
- Rodzaj nieobecności nigdzie nie wychodzi (D6): ekrany mówią tylko „zastępstwo”
  i datę końca (`GET /api/interview-cycle/slots/recipient`).
