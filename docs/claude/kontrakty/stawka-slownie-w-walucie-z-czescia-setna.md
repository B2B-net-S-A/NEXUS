# Stawka słownie w walucie obcej z częścią setną (audyt 24.11.2026)

- `number_words.rate_in_words` dla walut innych niż PLN gubił setne, np.
  „45,50 EUR (słownie: czterdzieści pięć EUR)”, a umowa wymaga, żeby zapis
  słowny odpowiadał kwocie.
- Teraz waluta obca dostaje setne jako ułamek, tak jak w aneksach
  (`pln_words_with_fraction`): „czterdzieści pięć EUR 50/100”, „forty five
  EUR 50/100”. Kwota całkowita zostaje bez ułamka („sto EUR”). PLN dalej
  zapisuje grosze słownie.
- Przed podziałem na część całkowitą i setne kwota jest zaokrąglana do
  setnych Decimalem z ROUND_HALF_UP (`_whole_and_cents`), więc 99,999 to
  „sto złotych”, a nie „sto groszy”.
