# Poczta systemowa NEXUS — osobna aplikacja nadawcza

Stan potwierdzony 24.09.2026: Entra „NEXUS ATS - Mailbox and Login” ma
`Application Mail.Read`, ale `Mail.Send` tylko delegowane. Odczyt konfiguracji
Coolify przez `app-mail-config-audit` ([bieg 36048980367](https://github.com/B2B-net-S-A/NEXUS/actions/runs/36048980367))
pokazał `M365_APP_MAIL_ENABLED=true` i nadawcę
`artur.twardowski@b2bnetwork.pl`. To nie jest docelowa skrzynka systemowa.

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
