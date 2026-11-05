# Sześć powodów odrzucenia zamiast ręcznego opisu pod „Inne” (04.11.2026)
<!-- indeks: not_looking_for_work, client_conflict, contract_form, no_contact, client_no_reason, client_chose_other, reasonFitsEndedBy, groupRejectedReasons, mapa powodów dla systemu -->

Decyzja Artura 04.11.2026, etap 1 uczenia NEXUSA z decyzji zespołu. Od 12.10
696 z 1808 odrzuceń to „Inne”, a 584 z nich opisał człowiek, powtarzając te same
powody. Wybór z listy zastępuje pisanie, a raporty pokazują prawdziwe przyczyny.
Liczba kliknięć nie rośnie i nie ma nowych obowiązkowych pól. Opis przy „Inne”
zostaje obowiązkowy.

| Klucz (`rejection_reasons.name`) | Etykieta | Odrzucamy my / DL | Odrzuca klient |
| --- | --- | --- | --- |
| `not_looking_for_work` | Nie szuka pracy lub niezainteresowany | tak | nie |
| `no_contact` | Brak kontaktu | tak | nie |
| `client_conflict` | Pracuje u klienta lub nie chce do klienta | tak | tak |
| `contract_form` | Forma umowy (UoP, B2B, etat) | tak | tak |
| `client_no_reason` | Klient nie podał powodu | nie | tak |
| `client_chose_other` | Klient wybrał kogoś innego | nie | tak |

- **Dlaczego tak przy kliencie.** Na 104 opisach „Inne” przy „Odrzuca klient” od
  12.10 żaden nie mówi „nie szuka” ani „brak kontaktu”, więc to sprawy osoby.
  Klient może natomiast powiedzieć, że osoba już u niego pracuje albo że chce
  tylko UoP. Dwa powody klienta są tylko przy „Odrzuca klient”, bo my ani DL nie
  mówimy w jego imieniu: rekruter, który przekazuje taką odmowę, wybiera „Odrzuca
  klient” i dzięki temu odmowa liczy się klientowi.
- **Jedna reguła na froncie:** `reasonFitsEndedBy` w `lib/rejection-reasons.ts`.
  Używają jej okno odrzucenia (`RejectionV2`), panel DL (jak „Odrzuca Delivery
  Lead”) i karta rozmowy (jak „Odrzuca klient”, bo zapisuje głos klienta). Serwer
  jej nie pilnuje: API integracyjne może podać dowolny powód z szablonu, a powód
  przy złej roli nie psuje danych. Zmiana „Kto kończy?” zdejmuje wybór powodu,
  którego nie ma na nowej liście, zamiast zostawiać go wybranego poza ekranem.
- **Schemat:** migracja 0646 plus lustro w `entrypoint.sh`, każdy szablon, tylko
  `rejected`, tuż przed „Inne”, jednorazowo przez marker
  `frequent_rejection_reasons_seeded`. `disqualifies_person = false`, bo powody
  opisują sytuację, nie osobę, więc nie uruchamiają weta z
  `hiring_manager_verdicts`. Starych wpisów nikt nie przepina; odczyt ich opisów
  to osobny temat.
- **Osoba od systemu:** `AUTOFILL_TEMPLATE_REASON` kieruje `not_looking` i
  `no_answer`, `wrong_phone` oraz trzy powody „klient” do nowych powodów.
  `autofill_feedback.bucket_for` się nie zmienia: kosz liczy serwer z powodu dla
  systemu. Przy `wrong_phone` i powodach „klient” powód z szablonu jest szerszy
  niż wybór, więc nazwa powodu dla systemu zostaje w opisie
  (`autofillReasonKeepsLabel`). Szablon bez nowego powodu (admin skasował) wraca
  do „Inne” z nazwą w opisie.
- **Okno przy 1280 × 720:** płaska lista chowała nowe powody pod zgięciem, więc
  okno ma `size="lg"`, dwie kolumny i grupy (`groupRejectedReasons`): Klient,
  Wymagania, Warunki, Sprawa osoby, Pozostałe. Powód dopisany przez admina trafia
  do „Pozostałe”. Rezygnacja zostaje bez grup. Wybór powodu z wymaganym opisem
  przenosi kursor do pola opisu, bo stoi ono pod listą.
- **Powiązanie z CPro bez zmian.** `cpro_mail._reason_id` zostaje przy „Inne
  (rejected)” z notatką `Z CPro: …`: 61 takich wpisów od 12.10 ma tekst od klienta,
  żaden nie jest pusty, a treści nie da się bezpiecznie przypisać do powodu bez
  odczytu modelem.
- **Raporty:** Insights i historia kandydata czytają powód przez
  `rejection_reason_label`. Powód spoza pierwszej trójki w Insights ma etykietę
  w dymku wiersza zbiorczego „Inne”, jak każdy inny.
