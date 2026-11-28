# „Zostań trenerem” i „Poleć inżyniera” ze strony B2B Network (0806)
<!-- indeks: trener z rynku, kandydaci na trenerów, market_trainer_applications, polecenie inżyniera, candidate_referrals, premia za polecenie 1–5 tys. zł, website-trainer-applications, website-referrals, bez maila do polecanego -->

Decyzje Artura z 28.11.2026: na /dla-specjalistow trenerem może zgłosić się każdy z rynku
(tylko z firmą, rozliczenie fakturą, umowa szkoleniowa bez zmian), a polecić inżyniera
może każdy. Konsultant dopisuje premię do faktury, osoba spoza B2B dostaje ją na podstawie
krótkiej umowy; premia to 1–5 tys. zł zależnie od profilu. Obie osoby zwykle nie mają
kontraktu, więc nie pasują do `cp_trainer_applications` (wymaga `contract_id`) ani do
dodatku „Polecenie” na fakturze konsultanta.

Kod: trasy w `app/api/public_website_applications.py` (ten sam serwer strony, ten sam
token i moduł co aplikacje kandydatów → `strona-www-aplikacje-kandydatow.md`), logika
w `services/website_trainer_applications.py` i `services/website_referrals.py`, pola
w `services/website_forms.py`, schemat w `services/website_intake_schema.py`
(migracja 0806, lustro w `entrypoint.sh`, sondy w `/api/health/deep`). Ekrany:
Szkolenia → „Zgłoszenia trenerów” (TCM) i Zgłoszenia → „Polecenia” (`/applications`).
Testy: `tests/test_website_trainer_applications.py`, `tests/test_website_referrals.py`.

## Kontrakt ze stroną

Oba: `POST`, `Authorization: Bearer <WEBSITE_APPLICATIONS_TOKEN>` (= `NEXUS_APPLY_TOKEN`
strony), `multipart/form-data` albo `application/x-www-form-urlencoded`, bez plików
(plik = 400). Odpowiedź `201 {"ok": true, "status": "received"}` także przy powtórce,
bez śladu, czy osoba była już w NEXUSIE. 401 = zły albo pusty token, 422 = pole
(`detail[0].loc = ["body", "<pole>"]`). Pola jednowierszowe z nową linią dostają 422
(trafiają do opisów jako „Etykieta: wartość”). Limit trasy 20/min i 120/h na cały
serwer strony; per osoba limituje strona. NEXUS nie wysyła żadnego maila; potwierdzenie
do nadawcy wysyła strona.

`/api/public/website-trainer-applications`:

| Pole | Wymagane | Limit | Uwagi |
|---|---|---|---|
| `full_name` | tak | 120 | |
| `email` | tak | 254 | składnia e-mail |
| `linkedin` | nie | 300 | „LinkedIn albo strona”, dowolny tekst; ekran linkuje tylko http(s) |
| `topic` (powtarzane) | tak, albo `other_topic` | — | tylko z `TRAINER_TOPICS`, bez powtórek |
| `other_topic` | nie | 120 | własny temat |
| `first_training` | tak | 200 | |
| `experience` | tak | 5000 | wiele linii |
| `sample_url` | nie | 500 | pełny adres `http(s)://` |
| `consent` (powtarzane) | tak, 1–5 | 2000 | dosłowna treść zgody |

`/api/public/website-referrals`:

| Pole | Wymagane | Limit | Uwagi |
|---|---|---|---|
| `referrer_name` | tak | 120 | polecający |
| `referrer_email` | tak | 254 | |
| `referred_name` | tak | 120 | polecany; „Ewa Maria Nowak” → imię „Ewa Maria”, nazwisko „Nowak” |
| `referred_contact` | tak | 300 | e-mail albo `linkedin.com/in/<profil>`; inny adres i adres polecającego = 422 |
| `referred_role` | nie | 200 | „Czym się zajmuje” |
| `knows` | tak | 2000 | dosłowne oświadczenie „Ta osoba wie, że ją polecam…” |
| `consent` (powtarzane) | tak, 1–5 | 2000 | zgoda polecającego, dosłownie |

Tematy (`TRAINER_TOPICS`) są w trzech miejscach: `website_intake_schema.py`,
`PanelScreens.tsx` (panel konsultanta) i `src/lib/engineerForms.ts` strony. Zgodność
z panelem pilnuje test; stronę zmienia się razem z nimi.

## Trener z rynku

- Jedno zgłoszenie na adres (unikat `lower(email)`): ponowne wysłanie poprawia ten sam
  wiersz i zwiększa `submissions`; odrzucone wraca do „Nowe”, notatka TCM zostaje.
- Statusy ustawia TCM albo admin (`require_hr_trainings_manager`):
  nowe → rozmowa → w bazie trenerów / odrzucone; odrzucone da się przywrócić, trenera
  z bazy wycofać. Każda zmiana zostawia ślad w `hr_audit_events`.
- Adres z działającym kontraktem (`active`, `ending`) dostaje `contract_id`: na liście
  „nasz konsultant”, bo konsultant zgłasza się zwykle w panelu.
- TCM nie ma dzwonka o nowym zgłoszeniu; licznik nowych stoi na zakładce.
- **Wejście trenera z bazy do panelu** to osobny krok (decyzja Artura 28.11.2026: osobne
  wejście trenera z danymi firmy, bez kontraktu w rejestrze). Do tego czasu trener z rynku
  nie dostaje zamówień w panelu.

## Polecenie

- Polecany **nowy** = kandydat ze źródłem `polecenie` (`source_enum = referral`), zdarzenie
  źródła „Polecenie” z polecającym w notatce, bez CV i **bez zgód**: zgoda z formularza
  jest polecającego. Polecany **w bazie** (e-mail albo `linkedin_slug`) = profil bez zmian
  (P0-CAND-01). Adres **usunięty wcześniej na prośbę osoby** = bez profilu; wpis w kolejce
  bez dopasowania, „Utwórz kandydata” pyta o potwierdzenie jak przy każdym usuniętym adresie.
- Nagrobek usuniętej osoby jest tylko po e-mailu, więc polecenie samym profilem LinkedIn
  osoby usuniętej wcześniej założy jej profil od nowa (ograniczenie mechanizmu nagrobków,
  nie tej ścieżki).
- Każde polecenie ma wpis `pending_review` w kolejce „Zgłoszenia” (opis: kto polecił,
  konsultant czy spoza B2B, czym się zajmuje, że nie było maila). Drugie wysłanie tego
  samego polecenia (ten sam polecający i ta sama osoba) nic nie dubluje.
- **Żadnego maila do polecanego.** Trasa nie ma zadań w tle, a z trzech maili do
  kandydatów (`CANDIDATE_KINDS` w `notification_delivery.py`) żaden nie startuje bez
  własnego zgłoszenia osoby: „Twoje warunki” z aplikacji z linku albo portalu, raport
  kompetencji z formularza strony, potwierdzenie z `/apply`. Nie dopisuj do polecenia
  wysyłki ani kolejki maila. Pilnuje `tests/test_website_referrals.py` (każde wyjście
  HTTP, SMTP i funkcje maili NEXUSA w teście przerywa).
- Premia: rekruter (`CandidateWriteAccess`, sekcja Sourcing) prowadzi status
  nowe → rozmowa → zaczął projekt / odrzucone i kwotę 1000–5000 zł (API; baza tylko
  `> 0`, żeby widełki zmieniać bez migracji). „Zaczął projekt” wymaga kwoty.
  „Wypłacona” to osobna trasa za sekcją Finanse i uprawnieniem „Moduł Finanse”
  (`POST /api/candidate-referrals/{id}/paid`), potem polecenie jest zamknięte.
- Polecający konsultant = działający kontrakt pod jego adresem (`referrer_contract_id`,
  profil z kontraktu); inaczej premia „na podstawie krótkiej umowy”. Umowy i dopisku do
  faktury jeszcze nie ma: to kolejny krok, gdy będą warunki.
- Usunięcie kandydata zostawia polecenie z `candidate_id = NULL` (jak zgłoszenia,
  decyzja Artura 26.09.2026).
