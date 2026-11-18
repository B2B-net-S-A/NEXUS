# Poczta systemowa NEXUS — osobna aplikacja nadawcza

## Stan tenanta 25.09.2026

Utworzono osobną aplikację **NEXUS System Mail**. Entra pokazuje „No permissions
added”; aplikacja nie ma tam nieograniczonego `Mail.Send`. W Exchange App
RBAC rola `Application Mail.Send` jest ograniczona zakresem
`NEXUS-SystemMail-Sender-Scope`, którego jedynym bezpośrednim członkiem jest
`nexus-powiadomienia@b2bnetwork.pl`. Test zwrócił `InScope=True` dla tej
skrzynki i `InScope=False` dla `artur.twardowski@b2bnetwork.pl`.

`M365_APP_MAIL_CLIENT_ID` i `M365_MAIL_SENDER_UPN` zapisano w Coolify przez
workflow `Coolify set env` bez wdrożenia. Do uruchomienia pozostają sekret
aplikacji, wdrożenie oraz kontrolowany test wysyłki i dostarczenia.

Stan potwierdzony 24.09.2026: Entra „NEXUS ATS - Mailbox and Login” ma
`Application Mail.Read`, ale `Mail.Send` tylko delegowane. Odczyt konfiguracji
Coolify przez `app-mail-config-audit` ([bieg 36048980367](https://github.com/B2B-net-S-A/NEXUS/actions/runs/36048980367))
pokazał `M365_APP_MAIL_ENABLED=true` i nadawcę
`artur.twardowski@b2bnetwork.pl`. To nie jest docelowa skrzynka systemowa.

## Skrzynka kandydatów kariera@ (18.11.2026)

Udostępniona skrzynka `kariera@b2bnetwork.pl` („B2Bnetwork Kariera”, bez licencji)
dostała `Application Mail.Send` przez członkostwo w grupie `NEXUS-SystemMail-Scope`
(obok `nexus-powiadomienia@`). Tę samą aplikację „NEXUS System Mail” wybiera
`CANDIDATE_MAIL_SENDER_UPN=kariera@b2bnetwork.pl` (Coolify, 18.11). Próbny mail:
Coolify Ops → `candidate-terms-mail-probe` (tylko z `main`, tylko z kariera@,
adresaci stali). Domena: SPF z `spf.protection.outlook.com`, DKIM w M365
„Valid/Enabled”, DMARC `p=none`; b2bnetwork.pl jest w M365 „Internal Relay”
(MX na home.pl), więc mail na kariera@ z zewnątrz tam nie dojdzie — i nie ma
dochodzić, kandydat odpowiada formularzem.

T3b (18.11.2026, po #3585): obie wiadomości dotarły do Odebranych. Gmail
potwierdził SPF, DKIM i DMARC. W obu kopiach `List-Unsubscribe` dotarł jako
ASCII, a `List-Unsubscribe-Post` zniknął. Podpis DKIM w Gmailu pomijał oba pola. To nie
potwierdza wypisu jednym kliknięciem: [RFC 8058 §4](https://www.rfc-editor.org/rfc/rfc8058.html#section-4)
wymaga objęcia obu nagłówków ważnym podpisem DKIM.

Sonda sprawdza dokładne wartości obu nagłówków w każdym zserializowanym MIME
przed jakąkolwiek wysyłką. `outbound_mime_header_pair_verified=true` potwierdza
wyłącznie bajty przekazane do Graph. Log nie weryfikuje nagłówków u odbiorcy
ani ich objęcia podpisem DKIM. Ta diagnostyka nie naprawia transportu.

## Konfiguracja docelowa

1. Zarejestruj osobną aplikację „NEXUS System Mail” w Entra. **Nie nadawaj**
   jej aplikacyjnego `Mail.Send` w Entra ani zgody administratora na tę rolę.
   Unscoped grant Entra i scoped grant Exchange App RBAC sumują się: przy obu
   aplikacja mogłaby wysyłać z każdej skrzynki w tenantcie. Nie dodawaj także
   `Mail.Read`, `Mail.ReadWrite` ani dostępu do kalendarzy.
2. W Exchange App RBAC utwórz wskaźnik service principal, zakres obejmujący
   wyłącznie `nexus-powiadomienia@b2bnetwork.pl` i przypisz w nim rolę
   `Application Mail.Send`. Sprawdź `Test-ServicePrincipalAuthorization` dla
   tej skrzynki oraz skrzynki spoza zakresu. Test RBAC nie uwzględnia grantów
   Entra, dlatego osobno potwierdź, że tam nie ma aplikacyjnego `Mail.Send`.
   Nie poszerzaj istniejącej grupy `NEXUS-OrderMail-Scope`.
3. Zapisz w tajnych zmiennych Coolify `M365_APP_MAIL_CLIENT_ID` i
   `M365_APP_MAIL_CLIENT_SECRET`; ustaw
   `M365_MAIL_SENDER_UPN=nexus-powiadomienia@b2bnetwork.pl`. Nie zapisuj
   sekretu w GitHub ani w repo. `M365_MAIL_TENANT_ID` pozostaje wspólny.
4. Uruchom odczytowy `app-mail-config-audit` na `main`, by potwierdzić nazwę
   nadawcy i identyfikator nowej aplikacji. Następnie wykonaj jeden kontrolowany
   `app-mail-send-probe` do Artura. Graph 202 oznacza przyjęcie, więc sprawdź
   też odbiór/Message Trace przed uznaniem dostawy. Wyniku niepewnego nie
   ponawiaj bez sprawdzenia skrzynki.
5. Potwierdź `checks.m365_mail=healthy`, naturalną wiadomość z NEXUS oraz
   stan backlogu. Włączenie rutynowych powiadomień to osobna decyzja o
   zakresie wysyłki; nie odblokowuj ich samą zmianą statusu sondy.

Kod zachowuje zgodność wsteczną, gdy oba nowe pola są puste. Jeśli ustawiono
tylko jedno z nich, nadawca jest uznawany za nieskonfigurowany i nic nie
wysyła. Aplikacja do odczytu zamówień nadal używa `M365_CLIENT_ID/SECRET`.
