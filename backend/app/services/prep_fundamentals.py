"""Fundamenty przygotowania kandydata — ustawienia startowe (F1, 24.11.2026).

Wspólna lista 18 punktów ułożona z odpowiedzi Delivery Leadów (10–17.11.2026)
i rozstrzygnięta przez Artura 24.11.2026: wszystkie punkty obowiązkowe, tło
w Teams „B2Bnetwork albo neutralne”, wyjątki od warunków stop (np. umowa
o pracę, równoległy projekt) stoją w karcie klienta, nie na tej liście.
Rekruter przechodzi ją z każdym kandydatem przed prepem z Delivery Leadem.

Head of Recruitment zmienia listę w Ustawienia → Ocena prepów → „Przygotowanie”
(nowa wersja ``prep_review_configs``); ta stała obowiązuje, dopóki żadna
opublikowana wersja nie ma klucza ``preparation``.
"""

from __future__ import annotations

DEFAULT_PREPARATION: dict = {
    "groups": [
        {
            "title": "A. Warunki — najpierw",
            "hint": "Coś się nie zgadza: kończysz rozmowę i od razu dajesz znać DL-owi.",
            "items": [
                {
                    "label": "Forma współpracy",
                    "says": "Kontrakt B2B; kandydat pracuje u klienta, a B2Bnetwork "
                    "opiekuje się nim przez cały kontrakt.",
                    "passed_when": "Kandydat akceptuje B2B (wyjątki: karta klienta).",
                    "stop": True,
                },
                {
                    "label": "Stawka",
                    "says": "Potwierdź stawkę. Na rozmowie z klientem kandydat nie "
                    "rozmawia o pieniądzach — to ustala B2Bnetwork.",
                    "passed_when": "Zna i akceptuje stawkę, wie, że nie porusza jej "
                    "u klienta.",
                    "stop": True,
                },
                {
                    "label": "Dostępność i stabilność",
                    "says": "Od kiedy może zacząć, okres wypowiedzenia, czy ma inne "
                    "procesy albo projekt równolegle, czy zostanie na cały kontrakt.",
                    "passed_when": "Masz datę startu i odpowiedź o równoległych "
                    "procesach, zapisane w notatce (wyjątki: karta klienta).",
                    "stop": True,
                },
                {
                    "label": "Tryb pracy i biuro",
                    "says": "Ile dni w biurze, w którym mieście; przy rozmowie na "
                    "miejscu — dojazd.",
                    "passed_when": "Kandydat potwierdził tryb klienta.",
                    "stop": True,
                },
            ],
        },
        {
            "title": "B. Klient i rozmowa",
            "hint": "Szczegóły klienta bierzesz z jego karty.",
            "items": [
                {
                    "label": "B2Bnetwork i nasza rola",
                    "says": "Kim jesteśmy, że opiekujemy się konsultantem przez cały "
                    "kontrakt i możemy dać kolejny projekt.",
                    "passed_when": "Kandydat wie, kto jest kim między nim, nami "
                    "i klientem.",
                },
                {
                    "label": "Klient i projekt",
                    "says": "Nazwa klienta, projekt i zespół. Zapytaj, czy zna klienta "
                    "i czy był już w jego procesie.",
                    "passed_when": "Kandydat umie powiedzieć, do kogo idzie i do czego.",
                },
                {
                    "label": "Przebieg rozmowy",
                    "says": "Kto będzie na rozmowie, ile etapów, czy jest test albo "
                    "live coding (karta klienta).",
                    "passed_when": "Kandydat wie, czego się spodziewać.",
                },
            ],
        },
        {
            "title": "C. CV i przykłady",
            "hint": "Najdłuższa część: kandydat mówi, Ty słuchasz i dopytujesz.",
            "items": [
                {
                    "label": "CV punkt po punkcie",
                    "says": "Przejdźcie CV, które poszło do klienta: chronologia, "
                    "technologie, rola, wynik. Co się nie zgadza — powiedz kandydatowi.",
                    "passed_when": "Kandydat broni każdej pozycji z CV.",
                },
                {
                    "label": "Autoprezentacja 2–3 min",
                    "says": "Poproś o krótkie przedstawienie się pod wymagania tej "
                    "rekrutacji.",
                    "passed_when": "Mieści się w 3 min i trafia w wymagania.",
                },
                {
                    "label": "2–3 projekty metodą STAR",
                    "says": "Sytuacja, zadanie, działanie, rezultat. „Ja” zamiast „my”, "
                    "liczby i wynik.",
                    "passed_when": "Dwa projekty opowiedziane z własną rolą i wynikiem.",
                },
                {
                    "label": "Luki, zmiany i motywacja",
                    "says": "Przerwy w zatrudnieniu, krótkie epizody, powody odejść, "
                    "dlaczego ta rola.",
                    "passed_when": "Ma odpowiedź na każdą lukę i konkretny powód "
                    "„dlaczego ta rola”.",
                },
                {
                    "label": "Braki wobec wymagań",
                    "says": "Gdy czegoś nie robił: „nie pracowałem z X, ale z podobnym "
                    "Y”. Przyłapanie na naciąganiu kończy proces.",
                    "passed_when": "Kandydat wie, których wymagań nie spełnia i jak "
                    "o tym powie.",
                },
            ],
        },
        {
            "title": "D. Sposób rozmowy",
            "hint": "",
            "items": [
                {
                    "label": "Konkretnie i krótko",
                    "says": "Przykład zamiast deklaracji. Gdy nie wie: mówi to i mówi, "
                    "jak by do tego podszedł. Nie przerywa, dopytuje o niejasne pytanie.",
                    "passed_when": "Odpowiedzi na próbne pytania są krótkie i z przykładem.",
                },
                {
                    "label": "2–3 pytania do klienta",
                    "says": "O zespół, priorytety na start, technologie, sposób pracy.",
                    "passed_when": "Kandydat ma je zapisane.",
                },
            ],
        },
        {
            "title": "E. Organizacja i po rozmowie",
            "hint": "",
            "items": [
                {
                    "label": "Termin, link i sprzęt",
                    "says": "Potwierdź zaproszenie i link. Kamera włączona, mikrofon "
                    "i łącze sprawdzone wcześniej, spokojne miejsce, punktualność.",
                    "passed_when": "Kandydat potwierdził termin i sprawdził sprzęt.",
                },
                {
                    "label": "Wygląd i tło",
                    "says": "Schludnie, najlepiej koszula. Tło B2Bnetwork w Teams, a gdy "
                    "kandydat nie może go ustawić — neutralne.",
                    "passed_when": "Kandydat wie, jak ma wyglądać, i ma jedno z dwóch teł.",
                },
                {
                    "label": "Bez podpowiadaczy i nagrywania",
                    "says": "W trakcie rozmowy bez ChatGPT i innych narzędzi; kandydat "
                    "nie nagrywa spotkania.",
                    "passed_when": "Kandydat to usłyszał.",
                },
                {
                    "label": "Feedback zaraz po rozmowie",
                    "says": "Umawiacie się na telefon po rozmowie: jakie padły pytania, "
                    "co poszło dobrze, co słabiej. Pytania wpisujesz do NEXUSA — "
                    "przydadzą się następnym kandydatom.",
                    "passed_when": "Termin telefonu ustalony.",
                },
            ],
        },
    ],
    "readiness": [
        "Przedstawić swoje doświadczenie w 2–3 minuty",
        "Powiedzieć, kim jest klient i jak się u niego pracuje",
        "Omówić co najmniej 2 konkretne projekty",
        "Powiedzieć, jak ma odpowiadać na rozmowie",
        "Zadać 2–3 przygotowane pytania do klienta",
    ],
}
