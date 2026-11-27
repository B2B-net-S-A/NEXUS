# Dostępy: wejście i odejście osoby, kwartalny przegląd

Lista z 27.11.2026. Każdy dostęp do NEXUSA i jego infrastruktury, kto go nadaje
i jak się go odbiera. Role zamiast nazwisk, bo repo jest publiczne. Przy incydencie:
`podstawy/incydent-bezpieczenstwa.md`.

## Mapa dostępów

| Dostęp | Kto ma (stan 27.11) | Nadaje / odbiera | Uwagi |
|---|---|---|---|
| Konto Microsoft (Entra) | każdy pracownik | admin Microsoft 365 | jedyna droga do NEXUSA (SSO); MFA wymagane polityką dostępu warunkowego |
| Rola w NEXUSIE | aktywne konta (ok. 40) | admin NEXUSA (Ustawienia → Użytkownicy) | pierwsze logowanie zakłada konto (`uprawnienia/nowa-osoba-po-pierwszym-logowaniu-hor-i-admin.md`) |
| Logowanie hasłem (break-glass) | konto awaryjne admina i konto E2E | „Coolify set env” `PASSWORD_LOGIN_BREAK_GLASS_EMAILS` | omija MFA Entra; `podstawy/konto-e2e-na-produkcji.md` |
| Panel Coolify | 2 operatorów (konta 0 i 1) | właściciel zespołu w Coolify | dodatkowo allowlista IP w Traefiku |
| Tokeny API Coolify | GitHub Actions, laptop operatora | konto 0 → Keys & Tokens | nie zmieniaj hasła konta 0 (kasuje tokeny) |
| SSH root na serwerze | laptop operatora, drugi operator, klucz projektu Hetznera | `/root/.ssh/authorized_keys` | klucz Coolify „localhost” to ten sam klucz co laptop operatora |
| GitHub (organizacja, repo) | właściciel organizacji; współpracownik zewnętrzny w innym repo | właściciel organizacji | sekrety repo widzi każdy z prawem zapisu do workflow |
| Sekrety repo GitHub | — | właściciel organizacji | 56 sekretów; przegląd dat zmian w skrypcie |
| Hetzner (konto i projekt Cloud) | właściciel konta | właściciel konta | konsola serwera, migawki, zapora, Object Storage |
| Cloudflare | właściciel konta | właściciel konta | DNS, WAF, proxy API |
| Grafana Cloud | właściciel organizacji | właściciel organizacji | logi i metryki |
| Sentry (`b2bnet-sa`) | 2 właścicieli | właściciel organizacji | zdarzenia mogą zawierać dane osobowe |
| Klucze dostawców AI i usług | — | właściciel konta u dostawcy | rotacja: `podstawy/incydent-bezpieczenstwa.md` |

## Konta awaryjne Entra

Decyzja z 27.11.2026: dwa konta awaryjne tylko-chmurowe (domena `*.onmicrosoft.com`,
administrator globalny na stałe, klucz FIDO2, hasło w sejfie firmy), w grupie wykluczonej
z każdej polityki dostępu warunkowego — także z polityk zarządzanych przez Microsoft.
Bez nich awaria MFA albo zgubiony telefon jedynego administratora zamyka firmę poza
Microsoft 365, a po włączeniu blokady logowań spoza UE także wyjazd. Nowa polityka dostępu
warunkowego zawsze dostaje to wykluczenie. Przegląd kwartalny: test logowania każdym kontem
i dziennik logowań kont awaryjnych (każde logowanie poza testem to incydent).

## Wejście osoby (onboarding)

1. Konto Microsoft z licencją; osoba przy pierwszym logowaniu rejestruje metodę MFA
   (Microsoft Authenticator albo klucz). Do czasu rejestracji konto jest słabe: kto pierwszy
   zaloguje się hasłem, ten zarejestruje swoje MFA — dlatego hasło tymczasowe przekazuj
   osobiście i pilnuj rejestracji tego samego dnia.
2. Logowanie do NEXUSA przez Microsoft zakłada konto; rolę nadaje admin NEXUSA.
3. Dostęp operatorski (Coolify, SSH, GitHub, Hetzner, Cloudflare) tylko dla osoby, która
   wdraża albo utrzymuje serwer, i od razu z 2FA. Klucz SSH z komentarzem `rola@urządzenie`,
   żeby przegląd wiedział, czyj jest.

## Odejście osoby (offboarding)

W dniu odejścia, w tej kolejności:

1. **Entra:** zablokuj logowanie, „Odwołaj sesje”, usuń metody MFA; licencję i skrzynkę
   według zasad kadr.
2. **NEXUS:** konto nieaktywne (Ustawienia → Użytkownicy). Bez tego sesja NEXUSA żyje do
   30 dni (własny token odświeżania), bo NEXUS nie pyta Microsoftu przy odświeżaniu.
   Wyłączenie unieważnia tokeny i zwalnia przypisania do rekrutacji. Przekazanie rekrutacji
   prowadzą Kadry (`hr/handover.py`).
3. **Konto awaryjne:** jeśli adres osoby jest na liście break-glass — usuń go z listy.
4. **Operator:** konto w Coolify (Team → usuń), adres z allowlisty panelu, klucz z
   `authorized_keys`, członkostwo i współpraca w GitHubie, członkostwo w Hetznerze,
   Cloudflare, Grafanie i Sentry. Tokeny API, które osoba znała, zastąp nowymi.
5. **Sekrety, które osoba mogła odczytać** (operator z panelem Coolify widzi wszystkie
   zmienne aplikacji): rotacja według `podstawy/incydent-bezpieczenstwa.md`, gdy odejście
   jest w konflikcie albo osoba kopiowała wartości poza menedżer haseł.
6. Wynik `python3 scripts/przeglad_dostepow.py` po zmianach: osoby nie ma na żadnej liście.

## Kwartalny przegląd

Pierwszy dzień roboczy stycznia, kwietnia, lipca i października (plus po każdym incydencie
i odejściu operatora):

```bash
python3 scripts/przeglad_dostepow.py
```

Skrypt tylko czyta: GitHub (`gh api`), serwer i bazy przez SSH z konfiguracji
`scripts/prod_readonly.py`. Wypisuje konta, klucze, tokeny (bez wartości) i sekcję
„Do decyzji”: brak 2FA, tokeny i klucze nieużywane ponad 30–90 dni, aktywne konta NEXUSA
bez SSO albo bez aktywności 30 dni, klucze SSH bez komentarza, liczbę adresów break-glass.
Na końcu lista rzeczy do sprawdzenia ręcznie (Entra, Cloudflare, Hetzner, Grafana, Sentry),
bo ich API wymaga logowania właściciela.

Wyjście ma adresy e-mail: zostaje w terminalu, nie trafia do repo, PR-a ani logów Actions.
Decyzje z przeglądu (kto zostaje, co usunięte) zapisuje się z datą w pamięci operatora,
nie w repo.
