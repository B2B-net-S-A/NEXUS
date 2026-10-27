# Zrzut zgody RODO sprawdza AI przy wgraniu (F37)
<!-- indeks: model przepisuje nagłówek i akapit zgody, kod porównuje z rekrutacją; niepasujący zrzut tylko z powodem, DL widzi go w QC CV jako uwagę „consent_matches” -->

Decyzja Artura z 27.10.2026 po zgłoszeniu Martyny: do CV dla PKO BP trafiały
złe zrzuty zgody. Pomiar na 121 różnych zrzutach z produkcji (11.09–21.10):
11 złych — 6 to nie zgoda (plakat rekrutacyjny, zdjęcie, notatka, czat),
2 to prośba rekrutera bez odpowiedzi kandydata, 3 to zgoda innej osoby,
2 to inny numer ZOB; do tego jeden plik leżał pod CV dwóch kandydatów.
QC sprawdzało tylko, czy obraz jest (`zrzut-zgody-rodo-na-koncu-cv-wymog-pko-bp.md`).

- **Model tylko przepisuje, werdykt wydaje kod.** `services/cv_consent_check.py`:
  model F37 (`consent_screenshot_check`, Sonnet 5 z Haiku jak F33) dostaje sam
  obraz i nazwę klienta i oddaje nagłówek (nadawca, adresaci, data, temat)
  oraz dosłowny akapit zgody. Numer ZOB i nazwisko („Ja, X, wyrażam zgodę”)
  wyciąga z tego tekstu kod, a `assess` (czysta funkcja) porównuje je
  z kandydatem i rekrutacją. Nie dawaj modelowi danych kandydata i nie proś
  go o ocenę — wtedy „zgadza się” byłoby zdaniem modelu, nie porównaniem.
- **Co jest błędem:** brak zgody na obrazie, brak nagłówka z nadawcą, mail
  DO kandydata (prośba rekrutera — także gdy model wziął nadawcę z treści),
  nadawca to nie kandydat, inne nazwisko w zgodzie (od 5 liter wolno pomylić
  jedną: „Pawluk”/„Pawlak”), inny klient, brak albo inny numer ZOB niż
  `project_ref` pokwitowania (bez niego `pko_job_reference`), mail starszy
  niż otwarcie rekrutacji minus 3 dni, ten sam plik pod CV innego kandydata
  (skrót obrazu w bazie, bez AI). Bez znanego kandydata sprawdzamy tylko
  dokument (klient, ZOB, data).
- **Wariant A — ostrzeżenie, nie blokada.** `POST /api/cv-generator/consent-screenshot`
  przy `status: "mismatch"` bez `override_reason` oddaje wynik bez tokenu
  i NIE zapisuje obrazu. Z powodem (min. 5 znaków) zapisuje i wystawia
  pokwitowanie. Twardej blokady nie wprowadzaj: pomyłka albo awaria modelu
  zatrzymałaby CV do PKO, a wynik AI nigdy nie jest warunkiem ścieżki.
- **Awaria modelu = `unavailable`, zgoda przechodzi.** Tak samo, gdy nie da
  się złożyć danych do porównania — wtedy sprawdza Delivery Lead.
- **Wynik jedzie w pokwitowaniu, nie w nowej kolumnie.** `consent_binding.issue(..., check)`
  podpisuje go w tokenie, `verify` oddaje w `binding["check"]`, a ten ląduje
  tam, gdzie dziś `binding`: `render_payload.consent_screenshot.binding`
  (generator) i `branded_render_metadata.consent_binding` (kopia etapu).
  Treść zgody nie jest zapisywana — tylko nagłówek i kody.
- **QC CV: uwaga `consent_matches`** (ostatnia w `WARNING_KEYS`). `fail`
  z treścią problemów i powodem rekrutera, `manual` przy `unavailable`,
  `skip` dla zrzutów sprzed 27.10. Uwagę można pominąć („To OK” z powodem) —
  tak Delivery Lead przyjmuje zrzut; nie dopisuj jej do `NOT_DISMISSABLE`.
- **Pomiar przed zmianą promptu albo modelu.** 27.10 na 121 zrzutach ze
  stagingu: 10 z 11 złych oznaczonych (11. to stare CV bez powiązanego
  kandydata), dodatkowo duplikat i 2 zrzuty bez nagłówka; żaden dobry zrzut
  nie oznaczony. Skrypt pomiaru uruchamiaj w kontenerze stagingu, wynik
  tylko z id i kodami — zrzuty i nazwiska nie trafiają do repo.
