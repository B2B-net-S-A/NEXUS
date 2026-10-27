# Rzadkie słowo „musi mieć” w „Wymaganiach do poprawy” (`rare_word`, 27.10.2026)

Decyzja Artura z 27.10.2026: robimy wszystkie rekomendacje z raportu o wymaganiach
Championa (pomiar 129 profili z wierszami, kopia z 22.10). 49 z 886 wierszy „musi mieć”
miało mniej niż 10 osób w bazie (12 zero), a w 50 rekrutacjach wszystkie „musi mieć”
razem nie zostawiały nikogo. Okienko w edytorze (PR #2698) działa dopiero po jego
otwarciu, więc istniejące rekrutacje pokazuje DL-owi pulpit.

- **Powód.** `requirement_cleanup.build_proposal` dokłada `rare_word`, gdy wiersz
  poziomu „musi mieć” ma mniej niż `RARE_WORD_PEOPLE` (20, lustro frontu) osób.
  Krytycznych nie ruszamy — AI filtruje tylko po nich i tego nie zmieniamy; mile
  widziane niczego nie zawężają.
- **Co proponuje.** Sklejone warianty (`glued_variants`, lustro `gluedVariants`
  z `lib/requirement-rows.ts`: „SoapUI/ReadyAPI”, „GitOps (ArgoCD/FluxCD)”) rozdziela
  na warianty wiersza, gdy części razem mają co najmniej 20 osób. Inaczej wiersz idzie
  do „Rekruter sprawdza w rozmowie” (`experience.skills`, poziom „musi”, tekst jak
  „Do rozmowy” w edytorze: słowa przez „ / ”). Ostatni wiersz obowiązkowy zostaje
  (ten z największą liczbą osób) — rekrutacja nie traci słów do szukania.
  `after.rare` mówi oknu propozycji, ile osób ma słowo i co się z nim stanie.
- **Liczba osób = licznik „W bazie” w edytorze.** `services/requirement_row_counts.count_row`
  buduje to samo zapytanie co lista kandydatów (`_build_candidate_filtered_query`:
  aktywni i pasywni, słowa wiersza jako jedna grupa `q_any_group`, „Wyklucz” Championa
  jako `q_none`, `semantics_version=2` — całe słowo), liczone do granicy 20 (`LIMIT`).
  Słowo krótsze niż 2 znaki = brak liczby (lista odpowiada 422). Nie dokładaj własnej
  heurystyki rzadkości: pulpit ma mówić to, co DL zobaczy po otwarciu edytora.
- **Koszt i pamięć.** Pomiar 27.10.2026 na kopii z 22.10: 673 wiersze w 202 otwartych
  rekrutacjach to ok. 7 min liczenia (rzadkie słowo ≤ 0,5 s, popularne do 2,7 s nawet
  z `LIMIT`). Liczby trzyma pamięć procesu (jeden uvicorn) przez 24 h; pętla
  `requirement_row_counts` (`app/tasks/`, na stagingu dozwolona) dolicza co godzinę
  brakujące i bliskie wygaśnięcia. Pulpit i okno propozycji liczą same tylko nowe
  wiersze, w limicie 1,5 s; brak liczby = brak powodu, nie zgadywanie.
- **Decyzje.** „Odrzuć” chowa propozycję do zmiany profilu, jak dotąd. „Zatwierdź”
  starej propozycji nie chowa `rare_word` (na kopii z 22.10 23 z 24 decyzji na
  otwartych rekrutacjach to zatwierdzenia sprzed tego powodu); po zatwierdzeniu
  rzadkiego wiersza powód nie wraca, bo wiersz schodzi do rozmowy albo dostaje warianty.
- **Pomiar na stagingu (kopia z 22.10, 202 otwarte).** Propozycja na pulpicie: 73 przed,
  114 po. `rare_word` ma 53 rekrutacje (41 tylko z tego powodu, 36 z wierszem poniżej
  10 osób); 81 wierszy idzie do rozmowy, 6 dostaje warianty, żadna nie traci możliwości
  zatwierdzenia. Pierwszy obrót pętli: 678 wierszy w 222 s; kolejny 0,07 s; pulpit
  z pamięci 0,11 s; pulpit na zimno 2,4 s (jedno popularne słowo ponad limit 1,5 s).
