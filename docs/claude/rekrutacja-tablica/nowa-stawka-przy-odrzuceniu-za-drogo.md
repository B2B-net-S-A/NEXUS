# Nowa stawka przy odrzuceniu „Za wysokie oczekiwania finansowe”
<!-- indeks: „Ile teraz chce?” w oknie odrzucenia, `rejection_rate_hourly`, nowe minimum w profilu, opis „Chce min. X zł/h”, wpis historii z rekrutacją -->

Prośba Marka i decyzje Artura z 26.10.2026 (makiety ze stagingu:
https://claude.ai/artifact/CtqvYWjtVxQxyLr1Weu2RG). Rekruter dzwonił
z projektem za 130 zł/h do osoby z „Stawką od” 129, słyszał „teraz minimum
150”, odrzucał z powodem finansowym i wpisywał kwotę w opis. Na kopii
z 22.10.2026 tak wyglądało 51 ze 118 odrzuceń i rezygnacji z powodem
finansowym, a „Stawka od” żadnej z tych kwot nie widziała.

- **Kiedy okno pyta:** odrzucenie „Za wysokie oczekiwania finansowe”
  (słownik szablonu domyślnego, 0006) i rezygnacja `salary_mismatch`
  („Rozbieżność oczekiwań finansowych”, 0068) — `rejection_reason_labels.RATE_TOO_HIGH`,
  lustro na froncie `isRateTooHighReason`. Tylko przy jednej osobie; przy
  kilku naraz pola nie ma. Pole jest w `RejectionV2`, więc działa na Tablicy,
  w formularzu screeningu i w zakładce „Rozmowy”.
- **Kwota opcjonalna (D1).** Bez niej odrzucenie przechodzi jak dotąd.
  Serwer odrzuca `rejection_rate_hourly` przy innym powodzie (422).
- **„To jego nowe minimum” domyślnie zaznaczone (D2).** Zapis idzie przez
  `write_profile_rate` ze źródłem `rejection_minimum` (w `MINIMUM_SOURCES`),
  więc starsze, niższe stawki przestają się liczyć do „Stawki od”.
  Odznaczone = źródło `rejection`, zwykła stawka w historii — najniższa
  z 18 miesięcy dalej wygrywa. Kwota niższa od obecnej „Stawki od” tylko
  ostrzega w oknie.
- **Opis ruchu:** serwer dokleja „Chce min. 150 zł/h” (albo „Chce 150 zł/h”)
  przed opisem rekrutera, więc profil pokazuje kwotę przy powodzie, nawet gdy
  opis był pusty. Do maila odrzucenia opis nie trafia.
- **Wpis historii stawek niesie rekrutację** (`job_id` w audycie, czytane
  w `_profile_observation` tylko dla źródeł `REJECTION_SOURCES`): okno
  „Historia stawek” pokazuje jej nazwę, a „W tej rekrutacji” tę kwotę.
- **Osoba od systemu z powodem „Za droga”:** przy tym powodzie odrzucenia
  okno nie pyta drugi raz o „Ile chce?” — kwotę niesie pole pod powodem.
- **Starsze odrzucenia z kwotą w opisie zostają, jak są (D3)** — bez
  wczytywania do historii stawek.
