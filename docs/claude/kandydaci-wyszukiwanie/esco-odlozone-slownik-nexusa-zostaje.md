# ESCO odłożone: synonimy umiejętności zostają we własnym słowniku (28.11.2026)
<!-- indeks: ESCO v1.2.1 nie zna Spring/Docker/Kubernetes/Git/AWS; 25 z 200 haseł z odpowiednikiem; altLabels IT to szum; wracamy tylko z nowym pomiarem -->

Decyzja Artura z 28.11.2026: unijnej klasyfikacji ESCO nie wprowadzamy — ani
tabeli słownika, ani podpowiedzi w `/jobs/new`, ani synonimów w wyszukiwaniu.
Przegląd narzędzi z 28.11 polecał ESCO jako uzupełnienie słownika („Spring”,
„Spring Boot”, „SpringBoot” połączone przez ESCO), ale pomiar przed budową
pokazał, że ESCO tego nie robi, a własny słownik już tak.

## Pomiar (API ESCO, `selectedVersion=v1.2.1`, pl i en)

200 najczęstszych haseł słownika bez ról, kolejność wg liczby profili
(`app_settings['skill_dictionary_usage']`, kopia stagingu z 28.11.2026,
słownik: 1 282 hasła bez ról).

- **Czysty odpowiednik ma ok. 25 z 200**: SQL, Python, Java, JavaScript,
  TypeScript, PostgreSQL, MySQL, C#, C++, PHP, Angular, Ansible, Jenkins,
  Android, Swift, ASP.NET, WordPress, Adobe Photoshop i Illustrator, Sass,
  PRINCE2, Agile i Waterfall development. Każde z nich słownik zna już
  z wariantami.
- **Brak odpowiednika**: Spring, Spring Boot i Spring Framework (0 trafień
  w obu językach), Docker, Kubernetes, Git, Jira, AWS, Azure, Node.js, MongoDB,
  Kafka, Power BI, Postman, REST API, Scrum, Flutter, NgRx. ESCO odsyła je do
  ogólników („zarządzać środowiskami ICT do wirtualizacji” przy Kubernetesie
  i Dockerze), które jako synonim rozlałyby wyszukiwanie.
- **Etykiety alternatywne ESCO przy IT to szum**: Java (pl) = „Javax”,
  „Java Posse” (nazwa podcastu); SQL = „Subquery”, „Informix 4GL/SQL”.
  Jako synonim w wyszukiwaniu dawałyby trafienia bez związku z wymaganiem.
- Słownik NEXUSA już łączy te zapisy: „Spring Boot” ma `springboot`,
  `spring-boot`, `spring boot 3.x` i inne, „Spring” ma `spring framework`,
  a mapa wiedzy daje Spring Boot ⇒ Java (`mapa-wiedzy-it-powiazania.md`).
- Pobranie CSV z esco.ec.europa.eu wymaga akceptacji oświadczenia i adresu
  e-mail (link przychodzi mailem), więc skrypt importu nie pobrałby go sam.
  Publiczne API (`ec.europa.eu/esco/api`) działa bez formularza.

## Jak postępować

- Synonimy i warianty umiejętności dodaje się przez słownik
  (`slownik-rosnie-z-danych-propozycje.md`: nocne propozycje, „Zmapuj”,
  „Popraw”), a związki przez mapę wiedzy. Zewnętrznej listy jako drugiego
  źródła synonimów nie dokładaj.
- Do ESCO wracamy tylko z nowym pomiarem, który pokazuje zysk: nowa wersja
  ESCO z technologiami IT albo potrzeba spoza IT (praktyki i kompetencje
  miękkie, np. „Stakeholder Management” ↔ „zarządzać relacjami
  z interesariuszami”, które ESCO zna). Pomiar powtarza się tym samym
  sposobem (top 200 haseł wg profili, odpowiednik = etykieta preferowana
  równa nazwie hasła, po złożeniu wielkości liter i znaków), a decyzję
  podejmuje Artur.
