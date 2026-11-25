# Rozliczenia: deklaracja z listą dni niedostępności w mailu z fakturą

<!-- indeks: mail_declaration, w dniach byłam niedostępna, będę niedostępna, zapowiedź nieobecności, lista dni, mLeasing deklaracja, report.consultant_declaration, dni robocze minus dni z listy -->

Od 25.11.2026, dopisek do reguły „Deklaracja wystarcza” z 23.11.2026
(`report.consultant_declaration`, `client_settlements/mail_declaration.py`).

Powtórka próby rozliczeń na VI–VIII 2026: konsultantka mLeasingu zamiast arkusza pisze
w mailu z fakturą „W czerwcu w dniach 3.06 i 08.06 byłam niedostępna”, „W sierpniu
w dniach 17-21 oraz 31 byłam niedostępna”, „W lipcu w dniach 27-31 będę niedostępna”.
Finanse fakturowały dni robocze minus te dni (VI 19, VII 18, VIII 15 MD), a NEXUS
nie czytał takich zdań.

- MD = dni robocze miesiąca (kalendarz firmy) minus dni robocze z listy; weekend
  i święto z listy nic nie odejmują.
- Lista: dni, zakresy („27-31”), „i”, „oraz”, w obu szykach zdania („byłam niedostępna
  w dniach …”). Dzień z innym miesiącem („3.06” w lipcu), brak nazwy miesiąca albo inne
  słowo w zdaniu („przez chorobę”) = MD wpisują Finanse.
- Zapowiedź „będę niedostępna” (mail przed końcem miesiąca) liczy się tak samo, ale
  z uwagą. Decyzja Artura z 25.11.2026: MD wpisane, przyjęcie po spojrzeniu Finansów,
  bo plan mógł się zmienić.
- Nadawcę (sam konsultant z kontraktu) sprawdza `service`, jak przy innych deklaracjach.
