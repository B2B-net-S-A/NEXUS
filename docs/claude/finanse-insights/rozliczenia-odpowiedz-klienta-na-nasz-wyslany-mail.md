# Rozliczenia: odpowiedź klienta bez pliku prowadzi do naszego maila z Wysłanych

<!-- indeks: Wysłane, SentItems, sent_messages, odpowiedź klienta, Potwierdzam zestawienie, Zestawienie godzin, BNP CIB, is_reply_to_sent, _answered_mail, _store_reply_to_sent, REPLY_WINDOW, In-Reply-To, conversationId, MessageCopyForSentAsEnabled, jedna osoba albo nikt -->

Decyzja Artura z 23.11.2026 (próba rozliczeń IX–X 2026, BNP Paribas CIB). Koordynator wysyła
z adresu rozliczeń „Zestawienie godzin 2026.09 B2B.net S.A. - Imię Nazwisko” z arkuszem godzin
do klienta. Klient odpisuje samym „Potwierdzam zestawienie”, a czasem akceptację przekazuje
dalej („FYI”) przełożony z tej samej domeny. Arkusz istnieje tylko w naszym mailu
wychodzącym, a odpowiedź przychodzi z obcego adresu, więc czytnik nie znajdował nikogo
i osoba nie miała rozliczenia.

## Reguła

Mail **bez pliku** z obcego adresu, z „RE:”/„Odp:” w temacie i słowem rozliczenia w temacie
wątku (`is_reply_to_sent`), czytnik rozliczeń (`consultant_portal/mailbox.py`) łączy
z naszym mailem z Wysłanych (`_answered_mail`). Nasz mail musi spełniać wszystkie warunki:

- ma ten sam temat po zdjęciu „RE:”, „FW:”, „[EXTERNAL]” itp.; inny miesiąc w temacie
  oznacza inny mail;
- poszedł z adresu firmy i ma plik;
- któryś adresat w „Do” albo „DW” jest z domeny nadawcy odpowiedzi;
- wysłano go najwyżej 45 dni przed odpowiedzią (`REPLY_WINDOW`).

Przy kilku kandydatach wygrywa ten sam `conversationId`, a potem najpóźniejszy mail.

Osobę wskazuje **temat naszego maila** (`identity.resolve_named_in_text`): jedna osoba albo
nikt. Temat odpowiedzi nikogo nie wskazuje, bo obcy adres może napisać dowolny temat.

Odpowiedź musi akceptować (`client_acceptance.accepts`) w tekście nad cytatem naszego maila,
czyli nad pierwszym „From:”/„Od:” z adresem firmy. Tak przechodzi też „FYI” przełożonego
nad akceptacją podwładnego. „Proszę o korektę” nie akceptuje, więc nic nie zapisujemy.

Zapis: pliki z naszego maila (rodzaj z `kind_of_file`, okres z naszego tematu) oraz `.eml`
odpowiedzi jako `report` tej osoby. Jak każdy dokument z maila czekają na decyzję Finansów.
Nic nie pasuje albo brak osoby: działa zwykła ścieżka (`_store_client_acceptance`), więc
klienci z regułą akceptacji mailowej (PKO, BIK) zachowują się jak przed zmianą.

Działa tylko w `internal` i `all` (`any_sender`). W pilotażu czytnik do Wysłanych nie zagląda.
Router E8 tego nie zmienia: odpowiedź dalej jest też sprawą, tak jak mail bez pliku
z adresu firmy.

## Dlaczego nie same nagłówki wątku

W archiwum rozliczenia@ (home.pl, Outlook 16 przez IMAP) kopia w Wysłanych ma inny
Message-ID niż mail, który poszedł do klienta. Na przykład odpowiedź za IX ma In-Reply-To
`01bb01dd5188…`, a nasza kopia ma `01c201dd5188…`. In-Reply-To nie trafił w kopię w żadnym
z ponad 20 miesięcy tego wątku. Odpowiedź za X przekazał dalej ktoś, do kogo nie pisaliśmy.
Po samych nagłówkach powiązałyby się 0 z 2 odpowiedzi. Po temacie i domenie powiązały się 2 z 2.

## Warunek w M365 (niepotwierdzone)

Czytnik czyta `mailFolders/SentItems` skrzynki z `CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX`.
Gdy koordynator wysyła „jako” wsparcie@ ze swojego Outlooka, Exchange domyślnie zapisuje
kopię w Wysłanych nadawcy, nie skrzynki wspólnej. Wtedy czytnik niczego nie znajdzie. Trzeba
włączyć `MessageCopyForSentAsEnabled` (i `…ForSendOnBehalfEnabled`) na skrzynce wsparcie@.
Na 23.11.2026 tego nie sprawdzono.

Powiązane: `finanse-insights/rozliczenia-akceptacja-w-tresci-maila.md`,
`ludzie/jedna-skrzynka-wsparcie.md` (sekcja „Router E8”).
