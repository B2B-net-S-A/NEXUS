"""Polska uczelnia w polskim CV ma polską nazwę (zgłoszenie 15.10.2026).

Generator tłumaczył kierunek („Filologia angielska, licencjat”), a nazwę
uczelni przepisywał ze źródła jak nazwę własną („University of Białystok”).
Prompt prosi teraz o oficjalną polską nazwę; ta tabela domyka najczęstsze
uczelnie bez udziału modelu, więc wynik nie zależy od tego, czy model posłuchał.

Podmieniana jest tylko CAŁA nazwa (z miastem, skrótem w nawiasie albo bez).
Nazwa z wydziałem, uczelnia spoza tabeli i każda uczelnia zagraniczna zostają
tak, jak napisał model — połowiczne tłumaczenie byłoby gorsze niż żadne.
Wpisy to oficjalne angielskie nazwy uczelni (także dawne, gdy polska nazwa się
nie zmieniła); nowy wpis tylko z oficjalną nazwą z witryny uczelni.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# (oficjalna polska nazwa, miasto bez polskich znaków, angielskie nazwy)
_UNIVERSITIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Politechnika Warszawska", "warsaw", ("Warsaw University of Technology",)),
    (
        "Politechnika Wrocławska",
        "wroclaw",
        (
            "Wrocław University of Science and Technology",
            "Wrocław University of Technology",
        ),
    ),
    (
        "Politechnika Gdańska",
        "gdansk",
        ("Gdańsk University of Technology", "Technical University of Gdańsk"),
    ),
    ("Politechnika Poznańska", "poznan", ("Poznań University of Technology",)),
    (
        "Politechnika Łódzka",
        "lodz",
        ("Łódź University of Technology", "Technical University of Łódź"),
    ),
    ("Politechnika Śląska", "gliwice", ("Silesian University of Technology",)),
    (
        "Politechnika Krakowska",
        "krakow",
        (
            "Cracow University of Technology",
            "Tadeusz Kościuszko Cracow University of Technology",
        ),
    ),
    (
        "Politechnika Białostocka",
        "bialystok",
        ("Białystok University of Technology", "Białystok Technical University"),
    ),
    ("Politechnika Lubelska", "lublin", ("Lublin University of Technology",)),
    ("Politechnika Rzeszowska", "rzeszow", ("Rzeszów University of Technology",)),
    ("Politechnika Opolska", "opole", ("Opole University of Technology",)),
    ("Politechnika Świętokrzyska", "kielce", ("Kielce University of Technology",)),
    (
        "Politechnika Częstochowska",
        "czestochowa",
        ("Częstochowa University of Technology",),
    ),
    ("Politechnika Koszalińska", "koszalin", ("Koszalin University of Technology",)),
    (
        "Politechnika Bydgoska",
        "bydgoszcz",
        ("Bydgoszcz University of Science and Technology",),
    ),
    (
        "Akademia Górniczo-Hutnicza w Krakowie",
        "krakow",
        ("AGH University of Science and Technology", "AGH University of Krakow"),
    ),
    ("Wojskowa Akademia Techniczna", "warsaw", ("Military University of Technology",)),
    (
        "Zachodniopomorski Uniwersytet Technologiczny w Szczecinie",
        "szczecin",
        ("West Pomeranian University of Technology",),
    ),
    ("Uniwersytet Warszawski", "warsaw", ("University of Warsaw", "Warsaw University")),
    ("Uniwersytet Jagielloński", "krakow", ("Jagiellonian University",)),
    ("Uniwersytet Wrocławski", "wroclaw", ("University of Wrocław",)),
    ("Uniwersytet Gdański", "gdansk", ("University of Gdańsk",)),
    (
        "Uniwersytet im. Adama Mickiewicza w Poznaniu",
        "poznan",
        ("Adam Mickiewicz University",),
    ),
    ("Uniwersytet Łódzki", "lodz", ("University of Łódź",)),
    ("Uniwersytet Śląski w Katowicach", "katowice", ("University of Silesia",)),
    ("Uniwersytet w Białymstoku", "bialystok", ("University of Białystok",)),
    (
        "Uniwersytet Marii Curie-Skłodowskiej w Lublinie",
        "lublin",
        ("Maria Curie-Skłodowska University",),
    ),
    (
        "Uniwersytet Mikołaja Kopernika w Toruniu",
        "torun",
        ("Nicolaus Copernicus University",),
    ),
    ("Uniwersytet Rzeszowski", "rzeszow", ("University of Rzeszów",)),
    ("Uniwersytet Szczeciński", "szczecin", ("University of Szczecin",)),
    ("Uniwersytet Opolski", "opole", ("University of Opole",)),
    ("Uniwersytet Zielonogórski", "zielona gora", ("University of Zielona Góra",)),
    (
        "Uniwersytet Warmińsko-Mazurski w Olsztynie",
        "olsztyn",
        ("University of Warmia and Mazury",),
    ),
    (
        "Uniwersytet Kardynała Stefana Wyszyńskiego w Warszawie",
        "warsaw",
        ("Cardinal Stefan Wyszyński University",),
    ),
    (
        "Katolicki Uniwersytet Lubelski Jana Pawła II",
        "lublin",
        ("John Paul II Catholic University of Lublin",),
    ),
    (
        "Uniwersytet Kazimierza Wielkiego w Bydgoszczy",
        "bydgoszcz",
        ("Kazimierz Wielki University",),
    ),
    (
        "Uniwersytet Jana Kochanowskiego w Kielcach",
        "kielce",
        ("Jan Kochanowski University", "Jan Kochanowski University of Kielce"),
    ),
    (
        "Szkoła Główna Handlowa w Warszawie",
        "warsaw",
        ("SGH Warsaw School of Economics", "Warsaw School of Economics"),
    ),
    (
        "Uniwersytet Ekonomiczny w Krakowie",
        "krakow",
        ("Cracow University of Economics", "Krakow University of Economics"),
    ),
    (
        "Uniwersytet Ekonomiczny w Poznaniu",
        "poznan",
        (
            "Poznań University of Economics and Business",
            "Poznań University of Economics",
        ),
    ),
    (
        "Uniwersytet Ekonomiczny we Wrocławiu",
        "wroclaw",
        (
            "Wrocław University of Economics and Business",
            "Wrocław University of Economics",
        ),
    ),
    (
        "Uniwersytet Ekonomiczny w Katowicach",
        "katowice",
        ("University of Economics in Katowice",),
    ),
    (
        "Szkoła Główna Gospodarstwa Wiejskiego w Warszawie",
        "warsaw",
        ("Warsaw University of Life Sciences",),
    ),
    ("Akademia Leona Koźmińskiego", "warsaw", ("Kozminski University",)),
    (
        "Polsko-Japońska Akademia Technik Komputerowych",
        "warsaw",
        ("Polish-Japanese Academy of Information Technology",),
    ),
    (
        "Uniwersytet SWPS",
        "warsaw",
        ("SWPS University", "SWPS University of Social Sciences and Humanities"),
    ),
    ("Uniwersytet Morski w Gdyni", "gdynia", ("Gdynia Maritime University",)),
    (
        "Wyższa Szkoła Informatyki i Zarządzania w Rzeszowie",
        "rzeszow",
        ("University of Information Technology and Management in Rzeszów",),
    ),
)

# NFKD nie rozkłada „ł”, więc bez tej mapy „Łódź” dawałoby „odz”.
_TRANSLIT = str.maketrans({"ł": "l", "Ł": "L"})
_CITY_SPELLINGS = {"cracow": "krakow"}


def _key(text: str) -> str:
    """Nazwa sprowadzona do porównania: bez znaków, wielkości liter i interpunkcji."""
    text = re.sub(r"\([^()]*\)\s*$", "", text.translate(_TRANSLIT))
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    words = re.sub(r"[^a-z0-9]+", " ", text.replace("&", " and ")).split()
    if words[:1] == ["the"]:
        words = words[1:]
    return " ".join(_CITY_SPELLINGS.get(word, word) for word in words)


def _variant_keys(english: str, city: str) -> tuple[str, ...]:
    """Nazwa sama, z „in <miasto>” i z „, <miasto>” (przecinek znika w kluczu)."""
    return (_key(english), _key(f"{english} in {city}"), _key(f"{english} {city}"))


_POLISH_BY_KEY: dict[str, str] = {
    key: polish
    for polish, city, english_names in _UNIVERSITIES
    for english in english_names
    for key in _variant_keys(english, city)
}


def polish_university_name(institution: str) -> str:
    """Polska nazwa uczelni z tabeli albo nazwa bez zmian."""
    return _POLISH_BY_KEY.get(_key(institution), institution)


def localize_education(candidate_data: dict[str, Any], language: str) -> None:
    """W polskim CV podmienia angielskie nazwy polskich uczelni (w miejscu)."""
    if language != "pl":
        return
    for edu in candidate_data.get("education") or []:
        edu["institution"] = polish_university_name(edu["institution"])
