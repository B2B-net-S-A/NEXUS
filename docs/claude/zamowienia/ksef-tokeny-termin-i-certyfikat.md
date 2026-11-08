# KSeF: termin tokenów i uwierzytelnienie certyfikatem (08.11.2026)

## Termin, sprawdzony w źródłach 08.11.2026

- **Prawo obowiązujące: token do 31.12.2026.** § 13 ust. 1 pkt 1 rozporządzenia Ministra Finansów
  i Gospodarki z 12.12.2025 (Dz.U. 2025 poz. 1815, [tekst](https://api.sejm.gov.pl/eli/acts/DU/2025/1815/text.pdf),
  s. 10). Jedyna zmiana aktu to Dz.U. 2026 poz. 169 (dotyczy Węzła krajowego, nie tokenów).
- **Zapowiedź MF: utrzymać tokeny.** [Podręcznik KSeF 2.0 cz. I z 06.08.2026](https://ksef.podatki.gov.pl/media/dmrfdixs/podrecznik-ksef-20-cz-i-rozpoczecie-korzystania-z-ksef-06082026.pdf)
  (s. 26) i [strona „Certyfikaty KSeF”](https://ksef.podatki.gov.pl/informacje-ogolne-ksef-20/certyfikaty-ksef/)
  mówią o czasie nieokreślonym i o nowelizacji rozporządzenia.
- **Projekt nowelizacji nie jest prawem.** [RCL 12416152](https://legislacja.rcl.gov.pl/projekt/12416152), z 27.10.2026,
  etap uzgodnień. Zespół API MF w [ksef-api#885](https://github.com/CIRFMF/ksef-api/issues/885) (propozycja,
  dyskusja do 20.11): tokeny sprzed 01.01.2027 ważne do 30.11.2027, nowe najwyżej 365 dni i z zatwierdzaniem.
- Wniosek: dopóki nowelizacja nie wyjdzie w Dzienniku Ustaw, wiąże 31.12.2026. Nawet po niej token
  skończy się najpóźniej 30.11.2027, więc certyfikat jest potrzebny w każdym wariancie.
  Sprawdzenie: `https://api.sejm.gov.pl/eli/acts/DU/2025/1815`, sekcja `Akty zmieniające`.

## Jak działa w NEXUSIE

- Gdy jest certyfikat, `KsefClient` loguje się nim (`xades.py`, `POST /auth/xades-signature`), a token
  zostaje zapasowy. Odmowa certyfikatu albo certyfikat po terminie = przejście na token i log ERROR, bo
  cicha praca na tokenie ukryłaby zepsuty certyfikat do dnia wygaśnięcia tokenu. Awaria MF (5xx) i limit
  (429) nie przełączają metody.
- Zepsuty certyfikat przy działającym tokenie nie wyłącza integracji. Stan widać w `status_payload`:
  `certificate_configured`, `certificate_invalid`, `certificate_valid_until`.
- Odnowić przed `certificate_valid_until` (certyfikat KSeF: najwyżej 2 lata).

## Który certyfikat na produkcję

- **Certyfikat KSeF typu Authentication osoby, która ma w kontekście spółki wyłącznie „Odczyt faktur”**
  (`InvoiceRead`). Uprawnienia idą za osobą, nie za certyfikatem: certyfikat właściciela albo pieczęci
  dałby serwerowi pełny dostęp, a dzisiejszy token ma tylko odczyt.
- Klucz musi być plikiem, bo leży na serwerze. Kwalifikowany podpis na karcie albo w chmurze tu nie zadziała.
- Wniosek składa się po zalogowaniu podpisem albo Profilem Zaufanym. Tokenem się nie da (`certyfikaty-KSeF.md`).
- Sekrety repo i workflow „Coolify set env” (`value_from_secret`, `redeploy=false`, na końcu jeden Deploy):

| Sekret repo | `key` w workflow |
| --- | --- |
| `KSEF_CERTIFICATE_PROD` | `KSEF_CERTIFICATE` |
| `KSEF_CERTIFICATE_KEY_PROD` | `KSEF_CERTIFICATE_KEY` |
| `KSEF_CERTIFICATE_KEY_PASSWORD_PROD` (gdy klucz ma hasło) | `KSEF_CERTIFICATE_KEY_PASSWORD` |

  Wartość: Base64 z pliku PEM w jednej linii (`base64 -i plik.pem | tr -d '\n'`); `xades.load_identity`
  przyjmuje też sam PEM.

## Test na środowisku TEST MF

`KSEF_TEST_MF=1 python -m pytest tests/test_hr_ksef_xades_mf.py -v` z `backend/`. Losowy NIP, certyfikat
samopodpisany (wolno wyłącznie na TEST), potem wniosek o certyfikat KSeF i logowanie nim, także osobą
z samym `InvoiceRead`. Domyślnie pominięty, bo CI nie ma wołać MF. Zielony 08.11.2026 (4 przebiegi).
`/testdata/permissions` dla PESEL-u dało przy logowaniu kod 415; uprawnienia nadawaj przez
`/permissions/persons/grants`.
