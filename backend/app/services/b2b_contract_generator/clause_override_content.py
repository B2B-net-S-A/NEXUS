"""Treść per-klient modyfikacji umowy B2B (PL + EN).

Każdy Klient → funkcja ``ops(lang)`` zwracająca listę operacji (patrz
``clause_overrides`` — silnik). Treść prawna trzymana 1:1 (PL z briefu prawnika,
EN tłumaczone spójnie z terminologią szablonu EN).

Rejestr na końcu: ``CLIENT_OVERRIDES`` = lista ``(needles, ops_builder)``.
Dopasowanie po znormalizowanej (lower) nazwie Klienta — patrz
``clause_overrides.overrides_for_client``.
"""

from __future__ import annotations

Block = tuple[str, str]
Op = tuple[str, object, tuple[Block, ...]]


def _bullets(items: tuple[str, ...]) -> list[Block]:
    return [("b", f"•  {it}") for it in items]


# ════════════════════════════════════════════════════════════════════════════
# § 10 — Klauzule Antykonkurencyjne i Kary Umowne (Centrum e-Zdrowia, PFRON)
# ════════════════════════════════════════════════════════════════════════════

_P10_BULLETS_PL = (
    "opóźnienia w rozpoczęciu świadczenia usług,",
    "nienależytego wykonania usług,",
    "nieusprawiedliwionej nieobecności Partnera,",
    "niezłożenia wymaganych dokumentów lub oświadczeń,",
    "naruszenia zasad poufności,",
    "użycia wadliwego, niekompletnego lub nieuprawnionego kodu źródłowego,",
    "odmowy współpracy przy przekazaniu obowiązków,",
    "innych zawinionych uchybień wpływających negatywnie na realizację usług.",
)

_P10_BULLETS_EN = (
    "delay in commencing the provision of the services,",
    "improper performance of the services,",
    "unjustified absence of the Partner,",
    "failure to submit required documents or declarations,",
    "breach of confidentiality rules,",
    "use of defective, incomplete, or unauthorized source code,",
    "refusal to cooperate in the handover of duties,",
    "other culpable failures adversely affecting the provision of the services.",
)


def _p10_pl(desc: str) -> tuple[Block, ...]:
    b: list[Block] = [
        ("h", "§ 10"),
        ("sub", "Klauzule Antykonkurencyjne i Kary Umowne"),
        (
            "p",
            "1. W okresie obowiązywania Umowy oraz przez okres 12 (dwunastu) "
            "miesięcy po jej rozwiązaniu lub wygaśnięciu, Partner zobowiązuje się "
            "powstrzymać od:",
        ),
        (
            "i",
            "a) świadczenia usług bezpośrednio na rzecz Klienta B2BNET "
            "wskazanego w Załączniku nr 3, z pominięciem B2BNET., w zakresie "
            "objętym Segmentem Rynku,",
        ),
        (
            "i",
            "b) podejmowania zatrudnienia lub innej współpracy z Klientem "
            "B2BNET bez uprzedniej pisemnej zgody B2BNET.",
        ),
        (
            "p",
            "2. Zakaz konkurencji określony w ust. 1 nie obejmuje: a) "
            "współpracy z klientami B2BNET innymi niż Klienci wskazani w Załączniku "
            "nr 3, b) prowadzenia działalności gospodarczej lub świadczenia usług "
            "na rzecz podmiotów trzecich, które nie są Klientem Projektu, nawet "
            "jeśli działają w tym samym Segmencie Rynku, c) usług świadczonych poza "
            "Segmentem Rynku.",
        ),
        (
            "p",
            "3. W przypadku naruszenia przez Partnera postanowień § 8 "
            "(Informacje Poufne), Partner zapłaci B2BNET karę umowną w wysokości "
            "50.000,00 zł (słownie: pięćdziesiąt tysięcy złotych).",
        ),
        (
            "p",
            "4. W przypadku naruszenia przez Partnera postanowień ust. 1 "
            "niniejszego paragrafu (Zakaz Konkurencji), Partner zapłaci B2BNET karę "
            "umowną w wysokości 100.000,00 zł (słownie: sto tysięcy złotych).",
        ),
        (
            "p",
            "5. Zapłata kary umownej nie wyłącza prawa B2BNET do dochodzenia "
            "odszkodowania przewyższającego wysokość zastrzeżonej kary na zasadach "
            "ogólnych Kodeksu Cywilnego.",
        ),
        (
            "p",
            "6. Postanowienia ust. 7–10 poniżej znajdują zastosowanie w "
            f"przypadku, gdy działania lub zaniechania Partnera podczas świadczenia "
            f"usług na rzecz Klienta B2BNET ({desc}), skutkują nałożeniem na B2BNET "
            "przez Klienta kar umownych, odszkodowań lub innych sankcji "
            "finansowych.",
        ),
        (
            "p",
            "7. Partner ponosi wobec B2BNET odpowiedzialność finansową w "
            "pełnej wysokości za wszelkie sankcje nałożone na B2BNET przez Klienta "
            "B2BNET, jeżeli wynikają one z zawinionego działania lub zaniechania "
            "Partnera, w tym w szczególności z:",
        ),
    ]
    b += _bullets(_P10_BULLETS_PL)
    b += [
        (
            "p",
            "8. W razie zaistnienia sytuacji, o których mowa powyżej, Partner "
            "zobowiązuje się do zwrotu na rzecz B2BNET pełnej kwoty zapłaconych "
            "przez B2BNET kar umownych, odszkodowań lub innych świadczeń "
            "sankcyjnych, w terminie 7 (siedmiu) dni od dnia doręczenia wezwania do "
            "zapłaty.",
        ),
        (
            "p",
            "9. W przypadku opóźnienia w zapłacie, Partner zobowiązany jest do "
            "zapłaty odsetek ustawowych za opóźnienie zgodnie z art. 481 Kodeksu "
            "cywilnego.",
        ),
        (
            "p",
            "10. Postanowienia ust. 6–9 nie ograniczają prawa B2BNET do "
            "dochodzenia od Partnera odszkodowania przewyższającego wysokość "
            "zapłaconych kar, jeżeli poniesiona szkoda przekracza wartość tych "
            "świadczeń.",
        ),
    ]
    return tuple(b)


def _p10_en(desc: str) -> tuple[Block, ...]:
    b: list[Block] = [
        ("h", "§ 10"),
        ("sub", "Non-Competition Clauses and Contractual Penalties"),
        (
            "p",
            "1. During the term of the Agreement and for a period of 12 "
            "(twelve) months after its termination or expiration, the Partner "
            "undertakes to refrain from:",
        ),
        (
            "i",
            "a) providing services directly to the B2BNET Customer indicated "
            "in Appendix 3, bypassing B2BNET, within the scope covered by the "
            "Market Segment,",
        ),
        (
            "i",
            "b) taking up employment or other cooperation with the B2BNET "
            "Customer without the prior written consent of B2BNET.",
        ),
        (
            "p",
            "2. The non-competition clause specified in section 1 does not "
            "apply to: a) cooperation with B2BNET customers other than those "
            "indicated in Appendix 3, b) conducting business activity or providing "
            "services to third parties who are not Project Customers, even if they "
            "operate in the same Market Segment, c) services provided outside the "
            "Market Segment.",
        ),
        (
            "p",
            "3. In the event of a breach by the Partner of the provisions of "
            "§ 8 (Confidential Information), the Partner shall pay B2BNET a "
            "contractual penalty in the amount of PLN 50,000.00 (in words: fifty "
            "thousand zlotys).",
        ),
        (
            "p",
            "4. In the event of a breach by the Partner of the provisions of "
            "section 1 of this paragraph (Non-Competition), the Partner shall pay "
            "B2BNET a contractual penalty in the amount of PLN 100,000.00 (in "
            "words: one hundred thousand zlotys).",
        ),
        (
            "p",
            "5. The payment of the contractual penalty shall not exclude "
            "B2BNET's right to claim damages in excess of the amount of the "
            "reserved penalty under the general provisions of the Civil Code.",
        ),
        (
            "p",
            "6. The provisions of sections 7–10 below shall apply where the "
            "acts or omissions of the Partner during the provision of services to "
            f"the B2BNET Customer ({desc}) result in the imposition on B2BNET by "
            "the Customer of contractual penalties, damages, or other financial "
            "sanctions.",
        ),
        (
            "p",
            "7. The Partner shall bear full financial liability towards B2BNET "
            "for any sanctions imposed on B2BNET by the B2BNET Customer, where they "
            "result from the Partner's culpable act or omission, including in "
            "particular:",
        ),
    ]
    b += _bullets(_P10_BULLETS_EN)
    b += [
        (
            "p",
            "8. Should the situations referred to above occur, the Partner "
            "undertakes to reimburse B2BNET the full amount of contractual "
            "penalties, damages, or other sanction-related payments made by "
            "B2BNET, within 7 (seven) days from the date of delivery of the "
            "payment demand.",
        ),
        (
            "p",
            "9. In the event of delay in payment, the Partner shall be obliged "
            "to pay statutory interest for delay in accordance with Article 481 of "
            "the Civil Code.",
        ),
        (
            "p",
            "10. The provisions of sections 6–9 shall not limit B2BNET's right "
            "to claim from the Partner damages exceeding the amount of the "
            "penalties paid, where the damage suffered exceeds the value of those "
            "payments.",
        ),
    ]
    return tuple(b)


_CENTRUM_DESC = {
    "pl": "Skarb Państwa – Centrum e-Zdrowia",
    "en": "the State Treasury – Centrum e-Zdrowia",
}
_PFRON_DESC = {
    "pl": "Państwowy Fundusz Rehabilitacji Osób Niepełnosprawnych tzw. PFRON",
    "en": "the State Fund for the Rehabilitation of Disabled Persons (PFRON)",
}


def _ops_centrum(lang: str) -> list[Op]:
    blocks = (
        _p10_en(_CENTRUM_DESC["en"]) if lang == "en" else _p10_pl(_CENTRUM_DESC["pl"])
    )
    return [("replace_section", 10, blocks)]


def _ops_pfron(lang: str) -> list[Op]:
    blocks = _p10_en(_PFRON_DESC["en"]) if lang == "en" else _p10_pl(_PFRON_DESC["pl"])
    return [("replace_section", 10, blocks)]


# ════════════════════════════════════════════════════════════════════════════
# BNP Paribas — podmiana całego § 4 + zdanie w Załączniku nr 1
# ════════════════════════════════════════════════════════════════════════════

_BNP_CODE_URL = "https://www.bnpparibas.pl/csr/strategia-csr/lad-korporacyjny"


def _bnp_s4_pl() -> tuple[Block, ...]:
    return (
        ("h", "§ 4"),
        ("sub", "Ogólne zasady współpracy"),
        (
            "p",
            "1. Z uwagi na charakter współpracy, Partner zachowuje swobodę w "
            "doborze miejsca świadczenia Usług. Strony zgodnie ustalają, że Usługi "
            "mogą być wykonywane w siedzibie Partnera, siedzibie B2BNET, siedzibie "
            "Klienta B2BNET lub innym miejscu, o ile zapewnia ono techniczne "
            "możliwości realizacji zlecenia. Jeżeli ze względów technicznych, "
            "bezpieczeństwa danych lub specyfiki projektu wymagana jest obecność "
            "Partnera w siedzibie Klienta B2BNET lub B2BNET, Partner zobowiązuje "
            "się do świadczenia usług w tym miejscu.",
        ),
        (
            "p",
            "2. W przypadku realizacji zlecenia na terenie siedziby Klienta "
            "B2BNET lub B2BNET, Partner zobowiązuje się do przestrzegania "
            "obowiązujących w danym obiekcie przepisów dotyczących bezpieczeństwa, "
            "BHP, ppoż. oraz procedur dostępu i ochrony informacji.",
        ),
        (
            "p",
            "3. Partner w relacjach z Klientem B2BNET występuje jako "
            "podwykonawca B2BNET. Partner nie jest umocowany do składania "
            "oświadczeń woli w imieniu B2BNET, zaciągania zobowiązań, podpisywania "
            "umów ani aneksowania warunków współpracy z Klientem.",
        ),
        (
            "p",
            "4. Partner jako profesjonalista prowadzący działalność "
            "gospodarczą, ponosi pełną odpowiedzialność za sposób wykonania Usługi "
            "oraz ryzyko gospodarcze związane z prowadzoną działalnością. Partner "
            "samodzielnie zapewnia narzędzia niezbędne do realizacji Usług (m.in. "
            "komputer, oprogramowanie, łączność), chyba że wymogi bezpieczeństwa "
            "Klienta B2BNET stanowią inaczej.",
        ),
        (
            "p",
            "5. Jeżeli ze względów bezpieczeństwa infrastruktury IT Klienta "
            "lub B2BNET konieczne jest korzystanie z powierzonego sprzętu, zostanie "
            "on przekazany Partnerowi na podstawie Protokołu Przekazania. Partner "
            "ponosi odpowiedzialność materialną za utratę, zniszczenie lub "
            "uszkodzenie powierzonego mienia od momentu jego odbioru do momentu "
            "zwrotu.",
        ),
        (
            "p",
            "6. Odbiór i zwrot sprzętu następują osobiście w siedzibie B2BNET "
            "(Al. Jerozolimskie 180, Warszawa) lub w siedzibie Klienta, zgodnie z "
            "bieżącymi ustaleniami. Za zgodą B2BNET lub Klienta B2BNET możliwy jest "
            "zwrot sprzętu firmą kurierską na koszt i ryzyko Partnera. Sprzęt "
            "podlega zwrotowi w stanie niepogorszonym (z uwzględnieniem normalnego "
            "zużycia eksploatacyjnego), niezwłocznie po zakończeniu współpracy lub "
            "na każde wezwanie B2BNET lub Klienta B2BNET.",
        ),
        (
            "p",
            "7. Świadczenie Usług poza terytorium RP wymaga uprzedniej "
            "pisemnej zgody B2BNET lub Klienta B2BNET ze względu na wymogi "
            "bezpieczeństwa i zobowiązania kontraktowe wobec Klientów.",
        ),
        (
            "p",
            "8. Usługi będą świadczone w lokalizacjach wskazanych przez "
            "Klienta B2BNET (Warszawa lub Kraków), zgodnie z wymogami "
            "realizowanego projektu. Konkretna lokalizacja realizacji usług "
            "ustalana jest każdorazowo w zależności od specyfiki zlecenia i wymogów "
            "technicznych projektu.",
        ),
        (
            "p",
            "9. W celu zapewnienia komunikacji z zespołem projektowym Klienta "
            "B2BNET, Partner otrzyma dostęp do skrzynki e-mail w domenie Klienta "
            "B2BNET w formacie imię.nazwisko@external.bnpparibas.pl. Podpis e-mail "
            "będzie zawierał informację o statusie Partnera jako zewnętrznego "
            "dostawcy usług.",
        ),
        (
            "p",
            "10. W zakresie niezbędnym do prawidłowej realizacji zleconych "
            "usług, Partner może uczestniczyć w szkoleniach organizowanych przez "
            "Klienta B2BNET lub B2BNET dotyczących specyficznych systemów, "
            "narzędzi, procedur compliance lub innych aspektów technicznych "
            "związanych z wykonywaniem zlecenia.",
        ),
        (
            "p",
            "11. Partner zobowiązuje się przeznaczyć do 2 dni roboczych (w "
            "ramach ustalonego wynagrodzenia) na zapoznanie się ze środowiskiem "
            "pracy, narzędziami i procedurami Klienta B2BNET niezbędnymi do "
            "rozpoczęcia świadczenia usług.",
        ),
        (
            "p",
            "12. Partner oświadcza, że w trakcie realizacji usług będzie "
            "przestrzegał wszelkich przepisów dotyczących przeciwdziałania praniu "
            "pieniędzy, finansowaniu terroryzmu, łapownictwu i korupcji oraz zasad "
            "określonych w Kodeksie Postępowania Grupy BNP (dostępnym pod adresem: "
            f"{_BNP_CODE_URL}), w sposób zapewniający, że Klient B2BNET (Bank BNP "
            "Paribas Polska S.A.) nie naruszy obowiązujących regulacji i "
            "standardów.",
        ),
        (
            "p",
            "13. Partner zobowiązuje się do przystąpienia do realizacji "
            "zlecenia w ustalonym terminie oraz do przestrzegania okresu "
            "wypowiedzenia określonego w Umowie. W przypadku: a) nieprzystąpienia "
            "przez Partnera do realizacji Usług w ustalonym terminie rozpoczęcia "
            "współpracy, b) przerwania realizacji Usług bez powiadomienia i "
            "obiektywnie uzasadnionych przyczyn lub c) zaprzestania świadczenia "
            "Usług bez zachowania okresu wypowiedzenia (porzucenie zlecenia), "
            "Partner zapłaci B2BNET karę umowną w wysokości 50.000,00 zł (słownie: "
            "pięćdziesiąt tysięcy złotych).",
        ),
        (
            "p",
            "14. Zapłata kary umownej nastąpi w terminie 7 dni od dnia "
            "doręczenia Partnerowi noty obciążeniowej (dopuszcza się doręczenie "
            "drogą elektroniczną na adres e-mail wskazany w Umowie). Zastrzeżenie "
            "kary umownej nie wyłącza możliwości dochodzenia przez B2BNET "
            "odszkodowania przenoszącego wysokość zastrzeżonej kary na zasadach "
            "ogólnych.",
        ),
        (
            "p",
            "15. Postanowienia ust. 13 nie mają zastosowania w przypadku, gdy "
            "niewykonanie, nienależyte wykonanie lub zaprzestanie świadczenia Usług "
            "wynika z działania siły wyższej.",
        ),
    )


def _bnp_s4_en() -> tuple[Block, ...]:
    return (
        ("h", "§ 4"),
        ("sub", "General Principles of Cooperation"),
        (
            "p",
            "1. Given the nature of the cooperation, the Partner retains "
            "discretion in choosing the place of providing the Services. The "
            "Parties jointly agree that the Services may be performed at the "
            "Partner's premises, B2BNET's premises, the B2BNET Customer's premises, "
            "or another location, provided it ensures the technical capability to "
            "perform the order. If, for technical reasons, data security, or the "
            "specifics of the project, the Partner's presence at the B2BNET "
            "Customer's or B2BNET's premises is required, the Partner undertakes to "
            "provide the services at that location.",
        ),
        (
            "p",
            "2. Where the order is performed at the premises of the B2BNET "
            "Customer or B2BNET, the Partner undertakes to comply with the "
            "regulations applicable at the given facility concerning safety, "
            "occupational health and safety (OHS), fire protection, as well as "
            "access and information protection procedures.",
        ),
        (
            "p",
            "3. In relations with the B2BNET Customer, the Partner acts as a "
            "subcontractor of B2BNET. The Partner is not authorized to make "
            "declarations of will on behalf of B2BNET, to incur obligations, to "
            "sign agreements, or to amend the terms of cooperation with the "
            "Customer.",
        ),
        (
            "p",
            "4. The Partner, as a professional conducting business activity, "
            "bears full responsibility for the manner of performing the Service and "
            "the economic risk associated with the business activity conducted. The "
            "Partner independently provides the tools necessary to perform the "
            "Services (including a computer, software, connectivity), unless the "
            "B2BNET Customer's security requirements provide otherwise.",
        ),
        (
            "p",
            "5. If, for reasons of the security of the IT infrastructure of "
            "the Customer or B2BNET, the use of entrusted equipment is necessary, "
            "it shall be handed over to the Partner on the basis of a Handover "
            "Protocol. The Partner bears material liability for the loss, "
            "destruction, or damage of the entrusted property from the moment of "
            "its receipt until the moment of its return.",
        ),
        (
            "p",
            "6. The receipt and return of equipment take place in person at "
            "B2BNET's premises (Al. Jerozolimskie 180, Warsaw) or at the Customer's "
            "premises, in accordance with current arrangements. With the consent of "
            "B2BNET or the B2BNET Customer, return of the equipment by courier at "
            "the Partner's cost and risk is possible. The equipment is subject to "
            "return in a non-deteriorated condition (taking into account normal "
            "operational wear), immediately after the end of cooperation or at each "
            "request of B2BNET or the B2BNET Customer.",
        ),
        (
            "p",
            "7. Providing the Services outside the territory of the Republic "
            "of Poland requires the prior written consent of B2BNET or the B2BNET "
            "Customer, due to security requirements and contractual obligations "
            "towards Customers.",
        ),
        (
            "p",
            "8. The Services will be provided at the locations indicated by "
            "the B2BNET Customer (Warsaw or Kraków), in accordance with the "
            "requirements of the project being carried out. The specific location "
            "for providing the services is determined on a case-by-case basis "
            "depending on the specifics of the order and the technical requirements "
            "of the project.",
        ),
        (
            "p",
            "9. In order to ensure communication with the project team of the "
            "B2BNET Customer, the Partner shall receive access to an e-mail mailbox "
            "in the B2BNET Customer's domain in the format "
            "firstname.lastname@external.bnpparibas.pl. The e-mail signature shall "
            "contain information about the Partner's status as an external service "
            "provider.",
        ),
        (
            "p",
            "10. To the extent necessary for the proper performance of the "
            "ordered services, the Partner may participate in training organized by "
            "the B2BNET Customer or B2BNET concerning specific systems, tools, "
            "compliance procedures, or other technical aspects related to the "
            "performance of the order.",
        ),
        (
            "p",
            "11. The Partner undertakes to devote up to 2 business days "
            "(within the agreed remuneration) to familiarizing themselves with the "
            "working environment, tools, and procedures of the B2BNET Customer "
            "necessary to commence providing the services.",
        ),
        (
            "p",
            "12. The Partner declares that, during the performance of the "
            "services, they will comply with all regulations concerning the "
            "prevention of money laundering, terrorist financing, bribery, and "
            "corruption, as well as the rules set out in the BNP Group Code of "
            f"Conduct (available at: {_BNP_CODE_URL}), in a manner ensuring that "
            "the B2BNET Customer (Bank BNP Paribas Polska S.A.) does not breach "
            "applicable regulations and standards.",
        ),
        (
            "p",
            "13. The Partner undertakes to commence the performance of the "
            "order on the agreed date and to observe the notice period specified in "
            "the Agreement. In the event of: a) the Partner's failure to commence "
            "the performance of the Services on the agreed start date of "
            "cooperation, b) interruption of the performance of the Services "
            "without notice and objectively justified reasons, or c) cessation of "
            "the performance of the Services without observing the notice period "
            "(abandonment of the order), the Partner shall pay B2BNET a contractual "
            "penalty in the amount of PLN 50,000.00 (in words: fifty thousand "
            "zlotys).",
        ),
        (
            "p",
            "14. Payment of the contractual penalty shall take place within 7 "
            "days from the date of delivery to the Partner of the debit note "
            "(delivery by electronic means to the e-mail address indicated in the "
            "Agreement is permitted). The reservation of a contractual penalty does "
            "not exclude the possibility of B2BNET pursuing damages exceeding the "
            "amount of the reserved penalty under general rules.",
        ),
        (
            "p",
            "15. The provisions of section 13 shall not apply where the "
            "non-performance, improper performance, or cessation of the provision "
            "of the Services results from force majeure.",
        ),
    )


def _ops_bnp(lang: str) -> list[Op]:
    if lang == "en":
        s4 = _bnp_s4_en()
        anchor = "I have read this declaration, understand its content"
        sentence = (
            (
                "p",
                "I declare that I have read the BNP Group Code of Conduct, "
                f"available at: {_BNP_CODE_URL}, referred to in § 4 section 12 of "
                "the Agreement, and I undertake to apply and comply with the "
                "guidelines contained in the Code.",
            ),
        )
    else:
        s4 = _bnp_s4_pl()
        anchor = "z niniejszą deklaracją, rozumiem jej treść"
        sentence = (
            (
                "p",
                "Oświadczam, iż zapoznałem się z Kodeksem Postępowania Grupy "
                f"BNP, który znajduje się pod adresem: {_BNP_CODE_URL} o którym "
                "mowa w § 4 ust. 12 Umowy oraz zobowiązuję do stosowania i "
                "przestrzegania zawartych w Kodeksie wytycznych.",
            ),
        )
    return [
        ("replace_section", 4, s4),
        ("after_sentence", anchor, sentence),
    ]


# ════════════════════════════════════════════════════════════════════════════
# Rejestr: needle(s) → builder operacji. Pierwsze trafienie wygrywa.
# ════════════════════════════════════════════════════════════════════════════

CLIENT_OVERRIDES: list[tuple[tuple[str, ...], object]] = [
    (("pfron", "rehabilitacji osób niepełnosprawnych"), _ops_pfron),
    (("centrum e-zdrowia", "e-zdrowia"), _ops_centrum),
    (("bnp paribas",), _ops_bnp),
]
