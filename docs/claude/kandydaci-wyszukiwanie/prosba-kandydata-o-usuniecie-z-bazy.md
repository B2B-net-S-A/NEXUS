# Prośba kandydata o usunięcie z bazy: czarna lista, zamknięcie kart, decyzja admina (03.11.2026)
<!-- indeks: co robi rekruter, co zatrzymuje czarna lista, czego nie zatrzymuje, kto decyduje o trwałym usunięciu -->

Decyzja Artura z 03.11.2026. Przegląd tego dnia pokazał, że prośby lądowały
w zwykłych notatkach, a notatka niczego nie blokuje: osoby z taką notatką miały
status `active`, a część dostawała później nowe karty, także bez autora. W 2026
takich próśb było ok. 7, więc procedura idzie bez nowego kodu.

## Procedura

1. Rekruter wybiera „Czarna lista…” w menu profilu albo w panelu osoby, zakres
   „U nas”, powód: „Prośba o usunięcie z bazy, data, telefon lub mail”.
2. Przenosi otwarte karty tej osoby do „Wycofany”, z powodem ze słownika. Czarna
   lista sama kart nie zamyka (`api/candidate_blacklist.py`), a ruch zamykający
   jest dozwolony także dla osoby z czarnej listy (`api/pipeline.py`).
3. Wysyła Arturowi link do profilu na Teams.
4. Admin decyduje: osoba zostaje na czarnej liście albo używa „Usuń profil”.
   Trwałe usunięcie jest nieodwracalne i tylko dla admina, dlatego nie jest
   pierwszym krokiem.

Czarną listę zdejmuje admin, Delivery Lead albo Head of Recruitment, z powodem.

## Co to zatrzymuje, a czego nie

| Mechanizm | Działa | Nie działa |
|---|---|---|
| Notatka | nic nie blokuje | wszystko |
| Czarna lista „U nas” | osoba znika z wyszukiwania pod rekrutację i propozycji, nie da się jej dodać do rekrutacji | nie zamyka kart; ruch otwartej karty przechodzi po potwierdzeniu ostrzeżenia; nie blokuje ręcznego telefonu ani maila |
| Wynik kontaktu `do_not_contact` | tylko przy włączonej kolejce kontaktu (`CANDIDATE_CONTACT_ENABLED`) | na produkcji kolejka nie działa: 0 spraw i 0 telefonów z tym wynikiem (03.11.2026) |
| „Usuń profil” | usuwa profil i zapisuje nagrobek | pliki CV zostają; profil może wrócić, patrz niżej |

Ręcznego kontaktu system nie zatrzyma, więc zespół po prostu się z tą osobą nie
kontaktuje.

## Na co uważać

- Nie wskazuj `do_not_contact` jako sposobu na taką prośbę, dopóki kolejka
  kontaktu jest wyłączona.
- Brak telefonu w bazie nie dowodzi braku kontaktu. `calls` ma w całym systemie
  10 wierszy (22.03–14.04.2026), bo CloudTalka nie używamy
  (`integracje/cloudtalk-telefonia.md`). `emails` sięga 14.07.2025,
  `prep_meetings` 02.10.2026.
- Nagrobek po trwałym usunięciu sprawdzają (stan z 03.11.2026) import z Traffita,
  importer Talent Radaru i API integracji. Formularz aplikacyjny
  (`services/public_apply.py`) i załącznik z maila
  (`services/m365/attachment_handler.py`) go nie sprawdzają, więc mogą założyć
  nowy profil bez śladu prośby.
- Decyzji z 26.09.2026, że usunięcie kandydata nie kasuje CV
  (`uprawnienia/integralnosc-i-uprawnienia-reguly-po-audytach.md`), ta procedura
  nie zmienia.
