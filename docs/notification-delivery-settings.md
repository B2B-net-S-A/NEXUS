# Sterowanie automatycznymi powiadomieniami email

Administrator: **Ustawienia → System → Powiadomienia** (`/settings?item=notifications`).

Panel pokazuje wyzwalacz, regułę doboru odbiorców, kanały, rzeczywistego nadawcę i ostatnio zaobserwowany stan dostawcy. Steruje pięcioma rodzinami wiadomości: nieprzeczytany czat, wzmianki w notatkach, zmiany etapów, terminy rekrutacji oraz alerty klientów i umów.

## Aktywacja i zaległości

- Brak zapisanej konfiguracji oznacza wyłączenie wysyłki globalnej i wszystkich pięciu typów.
- Wysyłka wymaga obu zgód: przełącznika globalnego i przełącznika danego typu.
- Każde przejście OFF → ON ustala po stronie serwera nową granicę czasu. Zdarzenie musi powstać po późniejszej z granic: globalnej lub dla typu.
- Wiadomości sprzed aktywacji i z okresów wyłączenia są wykluczone z przyszłej wysyłki. Włączenie nie odtwarza kolejki. Historia w aplikacji pozostaje i nie otrzymuje fałszywego znacznika wysłania.
- Błąd odczytu polityki blokuje rutynową wysyłkę. Worker sprawdza politykę także bezpośrednio przed wywołaniem dostawcy. Żądania już przyjętego przez dostawcę nie można odwołać przełącznikiem.

## Zakres

Reset/zmiana hasła i weryfikacja adresu pozostają niezależne i są widoczne w katalogu bez przełączników. Ręczna korespondencja Microsoft 365, shortlisty, odpowiedzi odmowne, odczyt zamówień oraz zewnętrzne alarmy Sentry/Grafana mają własną konfigurację.

Panel nie nadaje uprawnień Microsoft 365, nie zmienia nadawcy i nie wysyła sondy. Aktywacja typu nie dowodzi sprawności dostawcy. Dla terminów i alertów klientów panel pokazuje podłączoną skrzynkę delegowaną, jeśli właśnie ona będzie używana; pozostałe ścieżki pokazują skonfigurowany Graph app-only lub SMTP.

Liczniki kolejki dotyczą wyłącznie maili o nieprzeczytanym czacie. Zbiory oczekujących i potencjalnie gotowych mogą się nakładać; nie należy ich sumować. Niepewne wyniki dostawy pozostają widoczne także podczas wyłączenia.

## Implementacja i kontrola

Admin-only GET/PUT `/api/settings/notification-delivery` zapisuje JSONB w istniejącym `app_settings` pod kluczem `notification_email_delivery`; bez migracji. PUT dopuszcza wyłącznie ścisłe wartości bool oraz pięć znanych identyfikatorów. Serwer ustala granice czasu pod blokadą wiersza.

Monitor poczty rozróżnia `policy_enabled`, `provider_enabled`, `delivery_status` i `provider_status`. Celowe wyłączenie nie zgłasza alarmu rutynowej wysyłki; awaria odczytu polityki nadal alarmuje. Health zachowuje niezależny stan `m365_mail` (używany także przez wiadomości bezpieczeństwa) oraz dodaje `notification_email_policy`.

Weryfikacja obejmuje testy polityki, autoryzacji, wiadomości bezpieczeństwa, monitora i UI. Hosted PostgreSQL sprawdza prawdziwy zapis i selekcję: 113-dniowy rekord nie wraca po aktywacji, nowy może się kwalifikować, a ponowne włączenie wyklucza okres OFF. Odbiór produkcji wymaga zielonego CI, zgodnego SHA, health/deep/Alembic oraz odczytu panelu administratora przy pozostawieniu przełączników OFF.
