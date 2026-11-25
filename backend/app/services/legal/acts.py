"""Akty w korpusie asystenta prawnego (decyzja Artura 25.11.2026).

Klucz aktu jest kontraktem dla części B–H planu
(``docs/asystent-prawny-plan.md``): pisma, wzory i zgodność z umową klienta
odwołują się do przepisów przez ``act_key`` + ``ref`` (``kc`` + ``art. 61 § 1``).

Identyfikatory sprawdzone w API 25.11.2026: ELI Sejmu
(``https://api.sejm.gov.pl/eli/acts/<ident>``, wszystkie 13 aktów mają status
„akt posiada tekst jednolity”) i CELEX w CELLAR Urzędu Publikacji UE (wersje
skonsolidowane ``0<CELEX bez 3>-<data>``).

``aliases`` to skróty i nazwy, po których ``citations.extract`` rozpoznaje akt
w zdaniu („art. 61 § 1 KC”, „art. 30 § 1 k.p.”, „art. 6 ust. 1 lit. b RODO”).
Porównanie idzie po tekście bez polskich znaków i bez kropek.
"""

from __future__ import annotations

from dataclasses import dataclass

SOURCE_ELI = "eli"
SOURCE_EURLEX = "eurlex"


@dataclass(frozen=True)
class ActSpec:
    key: str
    source: str
    ident: str
    short_name: str
    title: str
    aliases: tuple[str, ...]


ACTS: tuple[ActSpec, ...] = (
    ActSpec(
        "kc",
        SOURCE_ELI,
        "DU/1964/93",
        "KC",
        "Kodeks cywilny",
        ("kc", "k.c.", "kodeks cywilny", "kodeksu cywilnego", "kodeksie cywilnym"),
    ),
    ActSpec(
        "kp",
        SOURCE_ELI,
        "DU/1974/141",
        "KP",
        "Kodeks pracy",
        ("kp", "k.p.", "kodeks pracy", "kodeksu pracy", "kodeksie pracy"),
    ),
    ActSpec(
        "pr_aut",
        SOURCE_ELI,
        "DU/1994/83",
        "Pr. aut.",
        "Ustawa o prawie autorskim i prawach pokrewnych",
        (
            "pr. aut.",
            "pr.aut.",
            "prawa autorskiego",
            "prawo autorskie",
            "ustawy o prawie autorskim i prawach pokrewnych",
            "upapp",
        ),
    ),
    ActSpec(
        "pip",
        SOURCE_ELI,
        "DU/2007/589",
        "Ustawa o PIP",
        "Ustawa o Państwowej Inspekcji Pracy",
        (
            "ustawy o pip",
            "ustawy o państwowej inspekcji pracy",
            "ustawa o państwowej inspekcji pracy",
        ),
    ),
    ActSpec(
        "min_wynagrodzenie",
        SOURCE_ELI,
        "DU/2002/1679",
        "Ustawa o minimalnym wynagrodzeniu",
        "Ustawa o minimalnym wynagrodzeniu za pracę",
        (
            "ustawy o minimalnym wynagrodzeniu za pracę",
            "ustawy o minimalnym wynagrodzeniu",
        ),
    ),
    ActSpec(
        "zatory",
        SOURCE_ELI,
        "DU/2013/403",
        "Ustawa o zatorach płatniczych",
        "Ustawa o przeciwdziałaniu nadmiernym opóźnieniom w transakcjach handlowych",
        (
            "ustawy o przeciwdziałaniu nadmiernym opóźnieniom w transakcjach handlowych",
            "ustawy o zatorach płatniczych",
            "ustawy o terminach zapłaty",
        ),
    ),
    ActSpec(
        "pit",
        SOURCE_ELI,
        "DU/1991/350",
        "Ustawa o PIT",
        "Ustawa o podatku dochodowym od osób fizycznych",
        (
            "updof",
            "u.p.d.o.f.",
            "ustawy o pit",
            "ustawy o podatku dochodowym od osób fizycznych",
        ),
    ),
    ActSpec(
        "ksh",
        SOURCE_ELI,
        "DU/2000/1037",
        "KSH",
        "Kodeks spółek handlowych",
        ("ksh", "k.s.h.", "kodeks spółek handlowych", "kodeksu spółek handlowych"),
    ),
    ActSpec(
        "kpc",
        SOURCE_ELI,
        "DU/1964/296",
        "KPC",
        "Kodeks postępowania cywilnego",
        (
            "kpc",
            "k.p.c.",
            "kodeks postępowania cywilnego",
            "kodeksu postępowania cywilnego",
        ),
    ),
    ActSpec(
        "sus",
        SOURCE_ELI,
        "DU/1998/887",
        "Ustawa o sus",
        "Ustawa o systemie ubezpieczeń społecznych",
        (
            "usus",
            "u.s.u.s.",
            "ustawy o sus",
            "ustawy o systemie ubezpieczeń społecznych",
        ),
    ),
    ActSpec(
        "odo",
        SOURCE_ELI,
        "DU/2018/1000",
        "Ustawa o ochronie danych osobowych",
        "Ustawa o ochronie danych osobowych",
        ("uodo", "ustawy o ochronie danych osobowych"),
    ),
    ActSpec(
        "znk",
        SOURCE_ELI,
        "DU/1993/211",
        "Uznk",
        "Ustawa o zwalczaniu nieuczciwej konkurencji",
        ("uznk", "u.z.n.k.", "ustawy o zwalczaniu nieuczciwej konkurencji"),
    ),
    ActSpec(
        "prawo_przedsiebiorcow",
        SOURCE_ELI,
        "DU/2018/646",
        "Prawo przedsiębiorców",
        "Ustawa — Prawo przedsiębiorców",
        (
            "prawa przedsiębiorców",
            "prawo przedsiębiorców",
            "ustawy prawo przedsiębiorców",
        ),
    ),
    ActSpec(
        "rodo",
        SOURCE_EURLEX,
        "32016R0679",
        "RODO",
        "Rozporządzenie (UE) 2016/679 (RODO)",
        ("rodo", "gdpr", "rozporządzenia 2016/679", "rozporządzenia (ue) 2016/679"),
    ),
    ActSpec(
        "dora",
        SOURCE_EURLEX,
        "32022R2554",
        "DORA",
        "Rozporządzenie (UE) 2022/2554 (DORA)",
        ("dora", "rozporządzenia 2022/2554", "rozporządzenia (ue) 2022/2554"),
    ),
    ActSpec(
        "ai_act",
        SOURCE_EURLEX,
        "32024R1689",
        "AI Act",
        "Rozporządzenie (UE) 2024/1689 (akt w sprawie sztucznej inteligencji)",
        (
            "ai act",
            "aktu w sprawie sztucznej inteligencji",
            "rozporządzenia 2024/1689",
            "rozporządzenia (ue) 2024/1689",
        ),
    ),
)

ACT_KEYS: tuple[str, ...] = tuple(spec.key for spec in ACTS)
BY_KEY: dict[str, ActSpec] = {spec.key: spec for spec in ACTS}


def spec_for(key: str) -> ActSpec | None:
    return BY_KEY.get(key)
