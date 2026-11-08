# Finanse → Rozjazdy stawek: stawka z kontraktu a linia zamówienia MD (audyt A5)
<!-- indeks: nocny raport bez id z bazy, kontrakt vs md_rate_* linii zamówienia zbiorczego, ostatni zamknięty miesiąc, zaokrąglenia godzinowe, kolejny krok: jedno źródło stawki -->

Synchronizacja kontrakt → zamówienie celowo pomija linie zamówień zbiorczych (`contract_order_sync`, filtr `order_group_id`), bo stawkę
linii prowadzi Delivery Lead. Marża i MRR liczą się jednak z kontraktu, więc linia 750 zł/MD przy kontrakcie 800 zł/MD zawyża wynik.

- Raport liczy się razem z nocną pętlą Braków (`tasks/order_gaps.py`, `services/rate_divergence_report.py`) i leży w `app_settings`
  (`contract_order_rate_divergences`). Ekran czyta ostatni stan, a kilka biegów dziennie niczego nie psuje.
- Dotyczy **ostatniego zamkniętego miesiąca**: dopiero za niego jest zużycie MD, a więc skutek w złotych.
- Obejmuje linie aktywne albo zakończone w tym miesiącu, z kontraktem aktywnym, kończącym się albo zakończonym. Szkic i `void` są poza
  raportem. Kontrakt bez stawki i inna waluta są tylko policzone w nagłówku, bo nie da się ich porównać.
- Porównujemy w walucie kontraktu: `md_rate_*` linii są zawsze w PLN/MD (materializator), a stawkę w walucie linii niosą
  `rate_client` i `rate_candidate`. Kontrakt w EUR porównany z `md_rate_*` dawał fałszywy rozjazd ×4.
- Wiersz mówi: osoba, klient i numer zamówienia, kontrakt i zamówienie w zł/MD, różnica, skutek w miesiącu. **Bez id z bazy**, bo
  Finanse szukają po osobie, kliencie, kwocie i miesiącu. Link do karty klienta jest tylko w adresie.
- Różnica do 4 zł/MD przy kontrakcie godzinowym to zaokrąglenie (945 zł/MD to 118,125 zł/h, a kontrakt ma 118). Idzie na koniec
  listy, z etykietą, ale nie znika.
- Raport **nic nie poprawia**. Zmiana źródła stawki (linia zamówienia jako jedyne źródło dla marży i MRR) to osobne, wielotygodniowe
  zadanie: dotyka `_compute_monthly_margin`, MRR, widoków jednoosobowych i eksportów.
