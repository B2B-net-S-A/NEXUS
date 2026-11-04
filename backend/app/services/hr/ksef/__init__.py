"""KSeF 2.0 — faktury od osób na B2B (Rozliczenia zespołu, R1 i R7).

Integracja tylko do odczytu: spółka uwierzytelnia się tokenem KSeF
(``KSEF_TOKEN``, kontekst ``KSEF_CONTEXT_NIP``) i pobiera faktury, w których
jest nabywcą (``subjectType=Subject2``). Klient obsługuje też ``Subject1``
(spółka jako sprzedawca) — kolejny etap czyta nim faktury sprzedażowe.

* ``environment`` — tryb (``KSEF_MODE``), adresy środowisk, konfiguracja,
* ``numbers`` — numer KSeF i suma kontrolna CRC-8,
* ``crypto`` — szyfrowanie tokenu kluczem publicznym MF (RSA-OAEP, SHA-256),
* ``client`` — wywołania API (uwierzytelnienie, odświeżenie tokenu,
  metadane faktur, XML faktury, 429 z ``Retry-After``),
* ``fa`` — odczyt XML FA(2)/FA(3): sprzedawca, numer, daty, kwoty, pozycje,
* ``source`` — źródło faktur: API albo pliki trybu ``simulate``,
* ``sync`` — pobieranie przyrostowe (pętla co godzinę, „Pobierz teraz”,
  „Pobierz ponownie okres”) i zapis faktur od NIP-ów z danych do rozliczeń,
* ``invoices`` — lista faktur, ręczny PDF, przypisanie do miesiąca, pominięcie.

Zapisujemy wyłącznie faktury od NIP-ów z ``employee_billing_details``;
faktury dostawców firmy liczymy jako „pominięte” i nie trafiają do bazy ani
do logów. Logi niosą identyfikatory faktur w NEXUSIE i liczby — bez NIP-ów,
numerów KSeF, kwot i tokenów.
"""
