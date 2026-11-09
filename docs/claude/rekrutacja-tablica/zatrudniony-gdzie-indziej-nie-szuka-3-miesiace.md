# „Zatrudniony gdzie indziej” zapisuje w profilu „Nie szuka” na 3 miesiące
<!-- indeks: odrzucenie z tym powodem → `availability_status` i „Dostępny od” +92 dni, zdjęcie nietkniętych kart od systemu z innych rekrutacji; dłuższego „Nie szuka” nie skraca -->

Decyzja Artura z 04.11.2026, pierwsza decyzja z zakładki „Wnioski” (makiety:
https://claude.ai/artifact/9adc6FGa17t5PzJFxDfiJB). Na kopii z 04.11.2026 41 ze
159 osób odrzuconych z tym powodem dostało potem 61 kart od systemu. Żadna nie
doszła do „Zweryfikowany”.

- **Działanie:** ruch w `api/pipeline.py` woła
  `autofill_feedback.mark_employed_elsewhere`: profil dostaje „Nie szuka”
  i „Dostępny od” za 92 dni, a silnik „Nowi na 20” pomija osobę do tej daty
  (`new_column_autofill.not_looking_now`). Nietknięte karty od systemu z innych
  rekrutacji znikają (`autofill_withdraw.withdraw_elsewhere`). Zmiana ma wpis
  `candidate_availability_changed` ze źródłem `employed_elsewhere_rejection`.
- **Bez pola w oknie:** okno tylko uprzedza. Datę zmienia się w profilu, bo każde
  dodatkowe pole przy odrzuceniu to praca przy każdej karcie.
- **Dłuższego „Nie szuka” nie skracamy:** ani bez daty, ani z datą późniejszą.
- **Człowiek nadal może dodać osobę ręcznie.** 4 ze 159 osób wróciły w 90 dni do
  „Zweryfikowany” innym wejściem, więc blokada dotyczy tylko systemu.
- **Propozycje z bazy tego nie sprawdzają:** nocny przegląd nie czyta
  `not_looking_now` (80 ze 159 osób dostało potem propozycję). Karta od systemu
  była tu problemem; propozycja czeka na decyzję człowieka.
