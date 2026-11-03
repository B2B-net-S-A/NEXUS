# Adres z rejestru i stawka progresywna w umowie B2B
<!-- indeks: „ul.” przed adresem z CEIDG, adres bez capslocka, `format_registry_address`, podpunkty a) b), `build_rate_lines`, `b2b.rate_lines` -->

Zgłoszenia działu umów z 03.11.2026. Oba dotyczą tekstu umowy z Generatora,
który ludzie poprawiali ręcznie przed wysłaniem do Partnera.

## Adres z rejestru

Biała Lista i CEIDG zwracają adres WIELKIMI LITERAMI i zwykle bez „ul.”. Na
kopii produkcji z 03.11.2026 tak wyglądało 42 ze 123 adresów w umowach
z generatora. Pole formularza dostaje teraz „ul. Testowa 12/3, 00-001 Warszawa”.

- **Gdzie:** `format_registry_address` (`services/b2b_contract_generator/address_format.py`)
  woła trasa `GET /company-lookup` i `_company_from_ceidg` / `_company_from_krs`
  w sprawdzeniu „Pobierz DOCX”. Komparycja i DPA czytają to samo pole, a aneksy
  biorą adres z tej samej trasy.
- **`lookup_company` zwraca rejestr bez zmian**, bo Sprzedaż wyciąga z tego adresu
  miasto (`city_from_address`). Nie przenoś formatowania do `_merge`.
- **Bez „ul.”:** adres z rodzajem drogi (al., pl., os., Aleja, Plac, Osiedle,
  Rondo, Skwer, Bulwar, Park, Rynek) i miejscowość bez ulic.
- **Miejscowość bez ulic** rozstrzyga pole `ulica` z CEIDG API (`has_street`),
  gdy jest. Bez niego (Biała Lista daje jeden napis) rozpoznajemy ją po tym, że
  przy numerze stoi nazwa miejscowości: „Nowa Wieś 80B, 83-304 Nowa Wieś”.
  **Znane ograniczenie:** wieś z pocztą w innej miejscowości („Wierzbowo 233,
  22-417 Stare Testowo”) wygląda wtedy jak ulica i dostaje „ul.”. Człowiek widzi
  adres w formularzu i może go poprawić.
- **Wielkie litery zostają** w numerach (118E/31), liczbach rzymskich (Jana Pawła II)
  i na początku członów („Bielsko-Biała”). Małe litery dostają tytuły (dr., św., gen.)
  i spójniki w środku nazwy („Żwirki i Wigury”, „Nowe Miasto nad Pilicą”).
  „Mieszka I 12” zostaje przy wielkim „I”, bo po nim stoi numer domu.
- Wpisu człowieka i umów już wydanych nie zmieniamy. `addressKey` we froncie
  ignoruje „ul.” i wielkość liter, więc okno sprawdzenia nie zgłasza różnicy.

## Stawka progresywna

Przy co najmniej dwóch etapach § 6 ust. 1 ma podpunkty zamiast jednego zdania:

    …oraz stawki godzinowej w wysokości:
    a) 122 PLN (słownie: sto dwadzieścia dwa złote) w okresie od dnia 16.11.2026 do dnia 31.05.2027,
    b) 127 PLN (słownie: sto dwadzieścia siedem złotych) od dnia 01.06.2027 netto + VAT.

- **Osobne akapity, nie łamanie wiersza.** Umowa jest wyjustowana, a Word rozciąga
  wiersz zakończony łamaniem na całą szerokość strony. Podpunkty nie mają numeracji
  listy, więc następny ustęp zostaje ustępem 2, a wcięcie (360) trzyma je pod tekstem
  ustępu.
- **Końcówka należy do szablonu**, bo w EN brzmi inaczej. `build_rate_lines` zwraca
  podpunkty bez niej; pusta lista przy jednej stawce zostawia dotychczasowe zdanie.
- **`b2b.rate_clause` zostaje** (jedno zdanie, „…, a 160 PLN …”) dla szablonów
  kontraktu pisanych ręcznie w Ustawieniach, które znają tylko tę zmienną.
- **Szablony DOCX i HTML** zmienia `python scripts/build_b2b_templates.py --rate-lines`
  (idempotentnie, na zacommitowanych plikach). `b2b.rate_lines | default([])`, bo HTML
  jedzie na `StrictUndefined`.
- Ponowne pobranie wydanej umowy progresywnej (6 z 123 na kopii z 03.11.2026) renderuje
  ten sam tekst w nowym układzie: szablon umowy głównej nie ma wersji, kwoty i daty
  bierze z `render_payload`.
