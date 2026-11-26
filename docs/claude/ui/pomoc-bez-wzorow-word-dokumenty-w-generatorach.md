# Pomoc bez wzorów Word: dokumenty w generatorach, formularze klientów na kartach

Decyzja Artura z 26.11.2026 (wariant B z makiet na stagingu). Rekruterzy
pobierali z Pomoc → Materiały wzory Word (umowa B2B, umowa przedwstępna, Profil
Championa, notatka po screeningu) i wypełniali je ręcznie zamiast robić dokument
w NEXUSIE. Przy każdym wzorze każdy zalogowany miał też „Edytuj w Word Online”.

- **Pomoc ma dla zespołu dwie zakładki: Procedury i Klienci.** Nad zakładkami
  stoi pasek „Wzorów w Wordzie już tu nie ma” (`HelpGeneratorsNotice`)
  z odnośnikami do miejsc, w których te dokumenty powstają. Każdy odnośnik ma
  bramkę pozycji menu (`navId` → `visibleNavEntries`), więc pasek nie prowadzi
  tam, dokąd nie prowadzi menu. Nowy generator, który zastępuje wzór = wpis
  w `HELP_GENERATOR_LINKS`.
- **Materiały widzi tylko admin** (`helpTabsFor`). Zostały, bo tam admin
  edytuje treść zaproszenia na prep, które czyta okno „Zaproś na prep”
  w Rozmowach i profilu kandydata (`PrepInviteModal`, lista
  `published_only=true`). Zaproszenia nie odpublikowuj, bo okno straci treść.
  Stary link `?tab=materials` u innej roli otwiera Procedury.
- **Formularze onboardingowe klientów są w „Dokumentach” karty klienta**
  (`client_playbooks.documents`), a nie w Materiałach. To dokumenty klienta
  (oświadczenia, zgody, załączniki), generatora nie mają. Kartę otwiera link
  „Pełna karta klienta →” z rekrutacji, więc rekruter ma je przy kliencie.
  Nowy formularz dopisuje Delivery Lead albo admin w formularzu karty
  (limit 50 dokumentów), nie w Materiałach.
- **Przenosiny zrobił jednorazowy krok** `repair-help-onboarding-to-client-cards-2026-11`
  w `entrypoint.sh` (`app/services/help_onboarding_to_client_cards.py`,
  znacznik `help_onboarding_to_client_cards_2026_11_26`): 24 linki u 9
  klientów, nowa wersja karty i wpis w historii, potem odpublikowanie
  przeniesionych formularzy i czterech wzorów. Wiersze w `help_materials`
  zostają (admin widzi je jako szkic), seed `ON CONFLICT (slug) DO NOTHING`
  ich nie przywraca. Adresy krok czyta z bazy, bo repo jest publiczne.
- **Nie wracaj do wzorów Word w Pomocy** dla dokumentu, który NEXUS robi sam.
  Brakuje czegoś w generatorze → popraw generator.
