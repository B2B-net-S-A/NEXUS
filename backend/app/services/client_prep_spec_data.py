"""Specyfika na prep — zasiew 12 kart (F2, decyzje Artura z 24.11.2026).

Treść z odpowiedzi Delivery Leadów i KAM-ów z 10–17.11.2026 i z kart klientów,
po rozstrzygnięciach Artura:
- Nordea: wartości z karty i „na rozmowie dobrze wypada” od DL-a — osobno;
- Tauron: umowa bezpośrednio z Tauronem, UoP możliwa (wyjątek od fundamentu 1),
  godziny według zlecenia rekrutacyjnego (umowa ramowa z 16.06.2026 nie ma
  limitu 165 h), biura Warszawa, Katowice, Wrocław.

Uwagi tylko dla zespołu (czego kandydat ma nie usłyszeć) nie trafiają tutaj:
repo jest publiczne, a klient mógłby je przeczytać — dopisuje je DL w karcie.

Klucze to id klientów z produkcji (kopia stagingu z 24.11.2026); pustą listą
zostaje pole, którego nikt nie opisał — karta pokazuje wtedy „zapytaj DL-a”.
Bez imion i stawek: repo jest publiczne.
"""

from __future__ import annotations

NORDEA, PKO_BP, BNP, ORLEN, ENERGA, EZDROWIE = 11, 26, 12, 35, 41, 115
PANSA, ALIOR, BANK_POCZTOWY, CREDIT_AGRICOLE, TAURON, VELOBANK = (
    153,
    39,
    16,
    116,
    151,
    37,
)

_ORLEN_GROUP_INTERVIEW = {
    "language": ["Polski; angielski czasem tylko do czytania dokumentacji"],
    "interview": [
        "Zwykle manager i osoba techniczna",
        "Najczęściej jeden etap, czasem drugi",
    ],
    "focus": [
        "Samodzielność, odpowiedzialność, proaktywność, komunikatywność",
        "Stabilność rozwiązań, bezpieczeństwo, jakość danych, dokumentacja, "
        "integracje, rozumienie procesów biznesowych",
        "Sama definicja technologii nie wystarczy: kandydat pokazuje, gdzie "
        "i jak jej używał",
    ],
    "questions": [
        "Projekty, technologie, odpowiedzialność kandydata i wyzwania; pytania "
        "techniczne zależą od stanowiska",
    ],
    "rejections": [
        "Zbyt płytkie doświadczenie z kluczowymi technologiami",
        "Brak samodzielności, zbyt ogólne odpowiedzi",
        "Doświadczenie ograniczone do koordynacji zamiast realnej pracy",
    ],
}

PREP_SPECS: dict[int, dict[str, list[str]]] = {
    NORDEA: {
        "work_mode": [
            "Hybryda: 3 dni w tygodniu w biurze (są wyjątki)",
            "Biura: Warszawa (Daimlera 4), Gdynia, Gdańsk, Łódź",
            "Konsultant musi mieszkać w Polsce; dojazdy do biura nie są zwracane, "
            "poza wyjazdem do Trójmiasta na prośbę klienta",
        ],
        "language": ["Angielski"],
        "interview": ["Liczby etapów nie podajemy kandydatowi — ustala ją manager"],
        "focus": [
            "Na rozmowie dobrze wypada: proaktywność, poczucie odpowiedzialności, "
            "gra zespołowa",
            "Współpraca w międzynarodowym zespole i ze stakeholderami",
            "Samodzielność i odpowiedzialność za zadania",
            "Jasna, konkretna komunikacja na przykładach, najlepiej z danymi",
            "Konstruktywne podejście do problemów, otwartość na zmiany i usprawnienia",
        ],
        "questions": [
            "Autoprezentacja: najważniejsze projekty, osiągnięcia i zakres "
            "odpowiedzialności",
            "Przykłady realnego wpływu kandydata na biznes",
            "Największe sukcesy, wyzwania i niepowodzenia",
            "Powody zakończenia poprzednich współprac",
        ],
        "rejections": [],
        "highlights": [
            "Wartości Nordei: Collaboration, Ownership, Passion, Courage",
            "Strategiczny klient: współpraca od 2015 roku, ok. 400 naszych konsultantów",
            "Bank skandynawski z siedzibą w Helsinkach, inwestuje w AI i chmurę",
            "Dojrzałe, spokojne środowisko; międzynarodowe zespoły, nacisk na jakość "
            "i bezpieczeństwo; metodyka SAFe",
            "Projekty długoterminowe",
        ],
        "cooperation": [],
    },
    PKO_BP: {
        "work_mode": [
            "Zależy od projektu; często hybryda z biurem w Warszawie albo w mieście "
            "z zapytania",
        ],
        "language": [],
        "interview": [
            "Z zespołem projektowym: manager albo osoby techniczne, skład zależy "
            "od stanowiska",
            "Często techniczna, ze szczegółowymi pytaniami o doświadczenie "
            "i stosowane rozwiązania",
            "Może być live coding albo zadanie praktyczne, czasem 30–40 minut — "
            "formę i czas potwierdzaj przed każdą rozmową",
        ],
        "focus": [
            "Jak kandydat używał technologii z CV, jakie miał problemy i jak je "
            "rozwiązał",
            "Przy roli technicznej — krótka powtórka pod zadanie praktyczne",
        ],
        "questions": [],
        "rejections": [],
        "highlights": [
            "Największy bank w Polsce: ponad 12 mln klientów, ponad 100 lat działalności",
            "Rozwój aplikacji, modernizacja systemów, integracje, migracja do chmury; "
            "projekty utrzymaniowe i nowe rozwiązania",
            "Współwłaściciel Operatora Chmury Krajowej (OChK) — chmura w skali "
            "enterprise",
            "Rozwiązania trafiają do milionów klientów, więc widać efekt pracy",
        ],
        "cooperation": [],
    },
    BNP: {
        "work_mode": [
            "Hybryda: 18 dni w biurze na kwartał (standard banku), chyba że "
            "zapytanie mówi inaczej",
            "Limit 220 dni pracy w roku, bez wyjątków",
        ],
        "language": ["Polski, wymagany bardzo dobry"],
        "interview": [
            "Prowadzą przedstawiciele zespołów projektowych i technicznych; skład "
            "i liczba etapów zależą od zapytania",
        ],
        "focus": [
            "Kandydat zna każdą technologię z CV i umie powiedzieć, jak jej używał",
            "W rolach analitycznych: samodzielność, współpraca z biznesem i IT, "
            "rozumienie zależności między systemami",
        ],
        "questions": [
            "Dotychczasowe projekty, decyzje techniczne, rozwiązywanie problemów",
            "Przy rolach developerskich i QA także podstawy techniczne",
        ],
        "rejections": [
            "Powierzchowna znajomość deklarowanych technologii",
            "Brak samodzielności",
            "Rozbieżności między CV a odpowiedziami",
        ],
        "highlights": [
            "Duży bank w środowisku regulowanym: bezpieczeństwo, jakość i stabilność; "
            "współpracujemy od 2015 roku",
            "Realne zastosowania AI/ML i generatywnej AI (analiza danych, anti-fraud, KYC)",
            "Architektura hybrydowa: on-prem i chmura dedykowana, platformy "
            "kontenerowe (OpenShift)",
            "Zwinne zespoły produktowe (squady, chaptery), często struktury globalne "
            "(Francja)",
        ],
        "cooperation": [],
    },
    ORLEN: {
        "work_mode": [
            "Hybryda: 1–4 dni w biurze, zależnie od projektu",
            "Biura: Płock (centrala), Warszawa (Kasprzaka)",
        ],
        **_ORLEN_GROUP_INTERVIEW,
        "highlights": [
            "Duża grupa energetyczno-paliwowa; systemy krytyczne dla energetyki "
            "i paliw, projekty długoterminowe",
            "Transformacja cyfrowa, platformy danych (GCP: BigQuery, Dataflow), "
            "integracja systemów po przejęciach LOTOS i PGNiG",
        ],
        "cooperation": [],
    },
    ENERGA: {
        "work_mode": ["Hybryda"],
        **_ORLEN_GROUP_INTERVIEW,
        "highlights": [
            "Energa-Operator (Gdańsk) należy do Grupy Orlen",
            "Środowisko regulowane: bezpieczeństwo danych, compliance i ciągłość "
            "działania",
            "Integracje systemów, utrzymanie i rozwój infrastruktury IT; projekty "
            "długoterminowe",
        ],
        "cooperation": [],
    },
    EZDROWIE: {
        "work_mode": [
            "W pełni zdalnie, pn–pt 8:00–16:00 albo 9:00–17:00 — decyzja klienta, "
            "nie podlega negocjacji",
        ],
        "language": [],
        "interview": [
            "Ostatni etap: test stacjonarny w siedzibie w Warszawie, ul. Stanisława "
            "Dubois 5A — ustal z kandydatem dojazd",
        ],
        "focus": [
            "Instytucja publiczna: formalne procedury, dokumentowanie pracy, "
            "godziny pracy urzędu",
            "Rzetelność i przewidywalność ważniejsze niż tempo i kreatywność",
        ],
        "questions": [],
        "rejections": [],
        "highlights": [
            "Państwowa instytucja Ministerstwa Zdrowia: e-recepta, e-skierowanie, "
            "Internetowe Konto Pacjenta, dokumentacja medyczna",
            "Stabilny, wieloletni kontrakt publiczny (Pzp)",
            "W zespole IT pracuje już kilku specjalistów B2Bnetwork",
        ],
        "cooperation": [],
    },
    PANSA: {
        "work_mode": [
            "Raz w miesiącu w biurze w Warszawie, ul. Wieżowa 8",
            "Pn–pt 8:00–16:00 albo 9:00–17:00 — decyzja klienta, nie podlega "
            "negocjacji",
            "Konsultant musi mieszkać w Polsce; dojazdy nie są zwracane",
        ],
        "language": ["Polski"],
        "interview": ["Analiza CV → test online w Devskiller → rozmowa online"],
        "focus": [
            "Instytucja publiczna: formalne procedury i dokumentowanie pracy; "
            "rzetelność ważniejsza niż tempo",
            "Cenione: systemy krytyczne (wysoka dostępność), bezpieczeństwo, duże "
            "i złożone systemy",
        ],
        "questions": [],
        "rejections": [],
        "highlights": [
            "Państwowa agencja zarządzania ruchem lotniczym; IT dla kontroli ruchu, "
            "integracje z radarami i nawigacją",
            "Kontrakt publiczny (Pzp), najczęściej wieloletni — długość sprawdź "
            "przed rozmową, zanim ją podasz",
        ],
        "cooperation": [],
    },
    ALIOR: {
        "work_mode": ["Głównie praca zdalna"],
        "language": ["Polski, wymagany płynny"],
        "interview": [
            "Weryfikacja doświadczenia projektowego i praktycznego sposobu myślenia",
        ],
        "focus": [
            "Rozumienie celu biznesowego, potrzeb użytkownika i wpływu rozwiązania",
            "Uzasadnianie decyzji, a nie wymienianie narzędzi i metod",
            "W rolach analitycznych i produktowych: samodzielność, inicjatywa, "
            "kwestionowanie założeń",
        ],
        "questions": [
            "Pytania sytuacyjne i przykłady realnych problemów do rozwiązania"
        ],
        "rejections": [
            "Schematyczne odpowiedzi",
            "Skupienie na zadaniu bez zrozumienia celu biznesowego",
        ],
        "highlights": [
            "Silny obszar rozwiązań cyfrowych i procesów biznesowych; współpracujemy "
            "od 2022 roku",
            "Aplikacje mobilne i online z AI i hiperpersonalizacją w czasie "
            "rzeczywistym",
            "Cloud Native i mikroserwisy; Azure i Google Cloud; CRM w chmurze",
        ],
        "cooperation": [],
    },
    BANK_POCZTOWY: {
        "work_mode": [
            "W większości projektów zdalnie, czasem wizyta w biurze raz na kwartał",
        ],
        "language": ["Polski"],
        "interview": ["Klient wybiera kandydatów z CV, potem rozmowa i decyzja"],
        "focus": [
            "Konkretne przykłady z projektów, najlepiej z liczbami i wynikami",
            "Doświadczenie w sektorze finansowym to atut",
            "Znajomość metodyk (PRINCE2, Agile)",
            "Samodzielność i zaangażowanie",
        ],
        "questions": [],
        "rejections": [],
        "highlights": [
            "Bank blisko współpracujący z Pocztą Polską, w transformacji chmurowej; "
            "projekty zwykle ponad 2 lata",
            "Migracje z on-premise do AWS, landing zone w Azure — Cloud Engineerowie "
            "i Solution Architekci",
            "PowerApps (Canvas Pro) z Pocztą Polską, m.in. Pocztowy24; PocztowyID "
            "(mojeID od KIR)",
            "Bankowość mobilna i internetowa: Pocztowy24, BLIK, Apple Pay, Google Pay; "
            "Express Elixir",
        ],
        "cooperation": [],
    },
    CREDIT_AGRICOLE: {
        "work_mode": [
            "Tryb pracy i dni w biurze ustalane osobno dla każdego projektu",
            "Biura: Warszawa (Żwirki i Wigury 18), Wrocław (Legnicka 48)",
        ],
        "language": ["Polski"],
        "interview": [
            "Zwykle 1–2 etapy",
            "Może być techniczna, ze szczegółowymi pytaniami o doświadczenie "
            "i rozwiązania",
        ],
        "focus": [],
        "questions": [
            "W analizie systemowej: komunikacja między systemami, integracje, "
            "projektowanie rozwiązań",
            "Pytania sytuacyjne o konkretne problemy techniczne",
        ],
        "rejections": [],
        "highlights": [
            "Bank z siedzibą we Wrocławiu, część Grupy Crédit Agricole; w IT ok. 800 "
            "specjalistów",
            "Bankowość detaliczna, korporacyjna i mobilna, cyberbezpieczeństwo, "
            "infrastruktura; rozwój systemów i greenfield",
            "Współpraca długoterminowa; po projekcie często jest kolejny w banku",
        ],
        "cooperation": [
            "B2B; przy stanowiskach juniorskich dla studentów możliwa umowa zlecenie",
        ],
    },
    TAURON: {
        "work_mode": [
            "Raz w miesiącu w biurze: Warszawa, Katowice (al. Roździeńskiego 1B), "
            "Wrocław (pl. Powstańców Śląskich 20)",
            "Godziny i ich liczba według zlecenia rekrutacyjnego — często nie są "
            "sztywne",
            "Konsultant musi mieszkać w Polsce; dojazdy nie są zwracane",
        ],
        "language": ["Polski"],
        "interview": ["Analiza CV → rozmowa online"],
        "focus": [
            "Kompleksowe podejście: jak kandydat rozwiązał problem i po co, a nie "
            "samo mówienie o technologiach",
            "Praca w metodyce Agile",
        ],
        "questions": [],
        "rejections": [],
        "highlights": [
            "Jedna z największych grup energetycznych w Polsce, w transformacji "
            "cyfrowej: platformy IT, AI, dane, cyfryzacja sieci",
            "Projekty długoterminowe",
        ],
        "cooperation": [
            "Umowa bezpośrednio z Tauronem, nie z nami; negocjuje ją Tauron",
            "Preferujemy B2B; umowa o pracę możliwa, gdy kandydat nie przyjmie B2B — "
            "wtedy brak zgody na B2B nie kończy procesu",
        ],
    },
    VELOBANK: {
        "work_mode": [],
        "language": [],
        "interview": [],
        "focus": [],
        "questions": [],
        "rejections": [],
        "highlights": [
            "Bank uniwersalny z siedzibą w Warszawie, od 2022 roku, w pierwszej "
            "dziesiątce banków w Polsce",
            "Własne oprogramowanie w Scrumie, infrastruktura utrzymywana wewnątrz, "
            "AI i GenAI w obsłudze klienta",
        ],
        "cooperation": [],
    },
}

# Tauron — karta „Co powiedzieć kandydatowi o kliencie”: limitu 165 h nie ma
# w umowie ramowej (godziny podaje zlecenie rekrutacyjne), biuro w Warszawie
# według DL-a klienta. Zmiana tylko, gdy zdania stoją jak w kopii z 24.11.
TAURON_ABOUT_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (
        "W Tauron obowiązuje sztywny limit godzin przepracowanych w miesiącu, "
        "który wynosi 165h.",
        "Godziny i ich liczba według zlecenia rekrutacyjnego — często nie są sztywne.",
    ),
    (
        "Katowice al. Walentego Roździeńskiego 1B (KTW II)\n",
        "Katowice al. Walentego Roździeńskiego 1B (KTW II)\nWarszawa\n",
    ),
)
