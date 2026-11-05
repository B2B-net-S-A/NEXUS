# Dopasowanie maila po temacie pomija profile pracowników (05.11.2026)
<!-- indeks: smart_name, adres w domenie firmy, imię i nazwisko konta z users -->

`smart_name` (`app/services/m365/matcher.py`) przypinał mail do profilu, gdy imię
i nazwisko z profilu stały w temacie, a profil miał kontakt w ostatnich 90 dniach.
`external_addresses` wyklucza adresy firmy tylko przy dopasowaniu po adresie, więc
ta reguła łapała też pracowników.

Pomiar z 05.11.2026: 237 maili `smart_name` w 21 profilach o nazwie konta z `users`,
119 z ostatnich 30 dni, 20 z tych profili ma prywatny adres. Profil z adresem
firmowym miał 8 takich maili i 1 z `smart_thread`, z 6 cudzych skrzynek, bez tej
osoby wśród nadawcy i odbiorców. Okno 90 dni otworzyły 2 ręczne przypięcia.

## Reguła (decyzja Artura)

- Profil z adresem w domenie firmy (`_internal_domains`, także domena właściciela
  skrzynki) nie dostaje maila po temacie.
- Tak samo profil, którego imię i nazwisko to nazwa konta z `users`, także
  nieaktywnego. Porównanie bez polskich znaków i wielkości liter.
- Powód: mail bez kandydata to prywatna korespondencja właściciela skrzynki, a po
  przypięciu widzą go admin i Delivery Lead (`email_threads._can_access_email`).

## Koszt

Kandydat będący imiennikiem pracownika nie dostaje dopasowania po temacie. Po adresie
(`strict`) i po wątku (`smart_thread`) działa jak wcześniej, ręczne przypięcie też.
