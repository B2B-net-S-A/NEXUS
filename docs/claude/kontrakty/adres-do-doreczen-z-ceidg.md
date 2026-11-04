# Adres do doręczeń z CEIDG — „pod adresem do doręczeń” w umowie, DPA i dokumentach
<!-- indeks: JDG bez stałego miejsca działalności, `address_kind` z karty firmy CEIDG, `partner_address_for_service`, przełącznik pod „Adres z CEIDG” -->

Decyzja Artura z 23.10.2026 (zgłoszenie działu umów). Partner JDG, który
w CEIDG nie ma stałego miejsca wykonywania działalności, a jedynie adres do
doręczeń, jest w umowie opisany „zarejestrowaną w Centralnej Ewidencji
i Informacji o Działalności Gospodarczej pod adresem **do doręczeń**: …”
(EN: „at the address **for service**: …”). Partner ze stałym miejscem
dostaje dzisiejsze „pod adresem: …” bez zmian.

## Dlaczego tak

- 23.10.2026 na stagingu (kopia produkcji): 24 z 75 Partnerów JDG z umów
  generatora ma w CEIDG tylko adres do doręczeń. W trzech umowach ludzie
  dopisywali „do doręczeń:” w polu adresu, przez co dokument mówił
  „pod adresem: do doręczeń: …”.
- **Biała Lista MF tego nie odróżnia**: adres do doręczeń zwraca jako zwykły
  `workingAddress`. Rodzaj adresu jest tylko na karcie firmy w CEIDG.

## Jak działa

- **Lookup** (`registry_lookup.py`): dla wpisu CEIDG z wyszukiwarki
  biznes.gov.pl generator pobiera kartę firmy (`GetCompanyDetails`) i zwraca
  `address_kind`: `place_of_business` (jest `placeOfBusinessAddress`),
  `service` (jest tylko `correspondenceAddress`) albo `None`. Ścieżka
  z tokenem CEIDG API pyta kartę osobno (`lookup_address_kind`). Awaria karty
  nie psuje nazwy ani adresu — rodzaj zostaje `None`.
- **Formularz umowy JDG**: pole nazywa się „Adres z CEIDG” (JDG nie ma
  siedziby; spółka zostaje przy „Adres siedziby firmy”), pod nim przełącznik
  „Stałe miejsce wykonywania działalności” / „Tylko adres do doręczeń”.
  Lookup go ustawia, człowiek może przestawić — wtedy pod spodem zostaje
  „Zmienione ręcznie — CEIDG mówi co innego”. Bez odpowiedzi rejestru
  domyślnie stałe miejsce, czyli dzisiejszy tekst. Wariant spółki nie ma
  przełącznika, a backend ignoruje flagę dla spółki.
- **Payload**: `partner_address_for_service` w `B2BRenderRequest`, zapisany
  w `render_payload`, więc ponowne pobranie i „Popraw umowę” biorą ten sam
  wybór. W kontekście szablonu `b2b.address_for_service`.
- **Szablony umowy** (`umowa_b2b_{pl,en}.{docx,html}`): komparycja
  i Załącznik nr 2 (DPA), warunek `b2b.address_for_service is defined and …`,
  bo podgląd HTML jedzie na `StrictUndefined`, a ścieżka renderu z rekordu
  `Contract` tego klucza nie ma.
- **Dokumenty pochodne** (decyzja z tego samego dnia): aneksy (stawka, data
  startu, podwykonawca), wypowiedzenie i porozumienie o rozwiązaniu (PL i EN)
  mają to samo zdanie z `partner.address_for_service`. Pole „W CEIDG tylko
  adres do doręczeń” przychodzi z `render_payload` umowy bazowej, a „Pobierz
  z CEIDG” ustawia je z `address_kind`. Po aneksie „dane firmy” prefill go nie
  przenosi (stary rodzaj opisywał stary adres). Aneks „dane firmy” sam
  opisuje NOWY adres wpisany w formularzu i tej flagi nie ma.

## Czego nie robić

- Nie wyprowadzaj rodzaju adresu z Białej Listy (`workingAddress` vs
  `residenceAddress`) — dla tych 24 Partnerów Biała Lista zwraca adres do
  doręczeń jako `workingAddress`.
- Nie dopisuj „do doręczeń” do samego adresu; zdanie buduje szablon.
- Umów już wydanych nie przeliczamy — zmiana działa od następnego pobrania.
