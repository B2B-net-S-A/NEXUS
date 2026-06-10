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
# Alior Bank — § 4A (po § 4) + § 9 ust. 5 + zapis pod tabelą Załącznika nr 3
# ════════════════════════════════════════════════════════════════════════════


def _alior_s4a_pl() -> tuple[Block, ...]:
    return (
        ("h", "§ 4A"),
        ("sub", "Zasoby i Warunki Korzystania"),
        (
            "p",
            "1. Strony przyjmują do wiadomości, że w związku z realizacją "
            "Usług na rzecz Klienta B2BNET Partner może uzyskać dostęp do systemów, "
            "środowisk, kont, narzędzi, oprogramowania, usług chmurowych oraz "
            "sprzętu udostępnionych przez B2BNET lub Klienta B2BNET lub przez "
            "podmioty, którym przysługują prawa do tych zasobów (dalej łącznie: "
            "„Zasoby”).",
        ),
        (
            "p",
            "2. Partner zobowiązuje się korzystać z Zasobów wyłącznie w "
            "zakresie niezbędnym do realizacji Usług oraz zgodnie z warunkami "
            "licencji, regulaminami, politykami bezpieczeństwa, instrukcjami i "
            "innymi dokumentami dotyczącymi Zasobów, udostępnionymi Partnerowi w "
            "formie elektronicznej, papierowej lub poprzez wskazanie adresu "
            "internetowego (dalej: „Warunki Korzystania”).",
        ),
        ("p", "3. Partner zobowiązuje się w szczególności:"),
        (
            "i",
            "a) przed rozpoczęciem korzystania z Zasobów zapoznać się z "
            "Warunkami Korzystania oraz potwierdzić ich przyjęcie, jeżeli jest to "
            "wymagane przez B2BNET lub Klienta B2BNET;",
        ),
        (
            "i",
            "b) nie instalować, nie kopiować, nie udostępniać, nie udzielać "
            "dalszych dostępów ani nie używać oprogramowania w sposób wykraczający "
            "poza Warunki Korzystania;",
        ),
        (
            "i",
            "c) nie podejmować działań zmierzających do obejścia zabezpieczeń, "
            "limitów licencyjnych, mechanizmów kontroli dostępu lub zasad "
            "bezpieczeństwa;",
        ),
        (
            "i",
            "d) korzystać z Zasobów wyłącznie na potrzeby realizacji Usług dla "
            "Klienta B2BNET i nie wykorzystywać ich w żadnym innym celu ani na rzecz "
            "osób trzecich.",
        ),
        (
            "p",
            "4. W razie powzięcia podejrzenia naruszenia Warunków Korzystania, "
            "incydentu bezpieczeństwa lub nieuprawnionego dostępu do Zasobów, "
            "Partner zobowiązuje się niezwłocznie (nie później niż w ciągu 24 "
            "godzin) powiadomić B2BNET oraz współpracować przy wyjaśnianiu zdarzenia "
            "i ograniczaniu jego skutków, w tym przekazać wszelkie informacje i "
            "materiały niezbędne do analizy zdarzenia oraz – na żądanie B2BNET – "
            "uczestniczyć w komunikacji z Klientem B2BNET.",
        ),
        (
            "p",
            "5. Na żądanie B2BNET lub Klienta B2BNET, umotywowane "
            "zobowiązaniem podmiotu trzeciego uprawnionego do Zasobów, Partner "
            "zobowiązany jest do niezwłocznego złożenia na rzecz tego podmiotu "
            "oświadczeń i zobowiązań odpowiadających treści niniejszego paragrafu w "
            "zakresie dotyczącym korzystania z Zasobów.",
        ),
        (
            "p",
            "6. Partner przyjmuje do wiadomości, że podmioty trzecie "
            "uprawnione do Zasobów nie ponoszą wobec Partnera bezpośredniej "
            "odpowiedzialności za szkody związane z korzystaniem z Zasobów w ramach "
            "projektu, i zobowiązuje się powstrzymać od kierowania wobec nich "
            "roszczeń z tego tytułu, z zastrzeżeniem roszczeń, których wyłączenie "
            "jest niedopuszczalne na podstawie bezwzględnie obowiązujących "
            "przepisów prawa.",
        ),
    )


def _alior_s4a_en() -> tuple[Block, ...]:
    return (
        ("h", "§ 4A"),
        ("sub", "Resources and Terms of Use"),
        (
            "p",
            "1. The Parties acknowledge that, in connection with the "
            "performance of the Services for the B2BNET Customer, the Partner may "
            "gain access to systems, environments, accounts, tools, software, cloud "
            "services, and equipment made available by B2BNET or the B2BNET "
            "Customer, or by entities holding rights to these resources (hereinafter "
            "jointly: the „Resources”).",
        ),
        (
            "p",
            "2. The Partner undertakes to use the Resources solely to the "
            "extent necessary to perform the Services and in accordance with the "
            "license terms, regulations, security policies, instructions, and other "
            "documents concerning the Resources, made available to the Partner in "
            "electronic or paper form or by indicating an internet address "
            "(hereinafter: the „Terms of Use”).",
        ),
        ("p", "3. The Partner undertakes in particular:"),
        (
            "i",
            "a) before commencing use of the Resources, to read the Terms of "
            "Use and confirm their acceptance, if required by B2BNET or the B2BNET "
            "Customer;",
        ),
        (
            "i",
            "b) not to install, copy, share, grant further access to, or use "
            "software in a manner exceeding the Terms of Use;",
        ),
        (
            "i",
            "c) not to take actions aimed at circumventing security measures, "
            "license limits, access control mechanisms, or security rules;",
        ),
        (
            "i",
            "d) to use the Resources solely for the purpose of performing the "
            "Services for the B2BNET Customer and not to use them for any other "
            "purpose or for the benefit of third parties.",
        ),
        (
            "p",
            "4. In the event of a suspected breach of the Terms of Use, a "
            "security incident, or unauthorized access to the Resources, the Partner "
            "undertakes to notify B2BNET immediately (no later than within 24 hours) "
            "and to cooperate in investigating the event and mitigating its effects, "
            "including providing all information and materials necessary to analyze "
            "the event and – at B2BNET's request – participating in communication "
            "with the B2BNET Customer.",
        ),
        (
            "p",
            "5. At the request of B2BNET or the B2BNET Customer, justified by "
            "an obligation of a third party entitled to the Resources, the Partner "
            "is obliged to promptly submit to that entity declarations and "
            "undertakings corresponding to the content of this paragraph with "
            "respect to the use of the Resources.",
        ),
        (
            "p",
            "6. The Partner acknowledges that third parties entitled to the "
            "Resources bear no direct liability towards the Partner for damages "
            "related to the use of the Resources within the project, and undertakes "
            "to refrain from directing claims against them on this account, subject "
            "to claims whose exclusion is impermissible under mandatory provisions "
            "of law.",
        ),
    )


def _alior_s9_5_pl() -> tuple[Block, ...]:
    return (
        (
            "p",
            "5. Ograniczenie odpowiedzialności, o którym mowa w ust. 4 "
            "powyżej, nie znajduje zastosowania do odpowiedzialności Partnera za "
            "szkody, koszty i roszczenia wynikające z: (i) naruszenia §4A (Zasoby i "
            "Warunki Korzystania), (ii) naruszenia §8 (Poufność), (iii) naruszenia "
            "§7A oraz Załącznika nr 2 (DPA/RODO), (iv) naruszenia §5 (Własność "
            "intelektualna), (v) kar umownych i roszczeń Klienta B2BNET nałożonych "
            "na B2BNET wskutek działań lub zaniechań Partnera.",
        ),
    )


def _alior_s9_5_en() -> tuple[Block, ...]:
    return (
        (
            "p",
            "5. The limitation of liability referred to in section 4 above "
            "shall not apply to the Partner's liability for damages, costs, and "
            "claims arising from: (i) a breach of § 4A (Resources and Terms of "
            "Use), (ii) a breach of § 8 (Confidentiality), (iii) a breach of § 7A "
            "and Appendix No. 2 (DPA/GDPR), (iv) a breach of § 5 (Intellectual "
            "Property), (v) contractual penalties and claims of the B2BNET Customer "
            "imposed on B2BNET as a result of the Partner's acts or omissions.",
        ),
    )


_ALIOR_SIG_PL = (
    ("gap", ""),
    ("sig", "________________________                    _____________________"),
    (
        "sig",
        "     B2B.NET S.A.                                                "
        "                Partner",
    ),
)


def _alior_table_pl() -> tuple[Block, ...]:
    return (
        ("gap", ""),
        ("sub", "SZCZEGÓŁOWE POSTANOWIENIA UMOWY:"),
        (
            "p",
            "1. Partner zobowiązuje się, że w okresie świadczenia Usług na "
            "rzecz Klienta Alior Bank S.A. nie będzie podejmował zleceń, które "
            "obiektywnie uniemożliwiałyby realizację Usług zgodnie z uzgodnioną "
            "dostępnością i terminami projektu lub powodowały konflikt interesów "
            "wobec Klienta Alior Bank S.A.. Powyższe nie wyłącza możliwości "
            "świadczenia usług na rzecz innych podmiotów, o ile nie narusza to "
            "zobowiązań wobec B2BNET i Klienta B2BNET, w szczególności zasad "
            "poufności i bezpieczeństwa.",
        ),
        (
            "p",
            "2. Partner zobowiązuje się do świadczenia swoich usług na rzecz "
            "Klienta B2BNET jakim jest Alior Bank S.A. zgodnie z ustalonymi "
            "warunkami i harmonogramem projektu. Partner będzie dyspozycyjny przez "
            "cały czas trwania projektu i podejmie wszelkie niezbędne działania w "
            "celu zapewnienia ciągłości i efektywności pracy.",
        ),
        (
            "p",
            "3. Partner zobowiązany jest do poinformowania zarówno Klienta "
            "B2BNET jak i samego B2BNET o planowanej nieobecności z wyprzedzeniem co "
            "najmniej 5 dni przed planowanym terminem nieobecności, chyba że "
            "wystąpią nadzwyczajne okoliczności, które uniemożliwią wcześniejsze "
            "zgłoszenie. W przypadku wystąpienia takich nadzwyczajnych okoliczności, "
            "Partner zobowiązany jest do jak najszybszego zgłoszenia nieobecności po "
            "ich wystąpieniu.",
        ),
        (
            "p",
            "4. Nieusprawiedliwione i niezgłoszone nieobecności Partnera będą "
            "podlegać karze w wysokości 5% wynagrodzenia należnego Partnerowi za "
            "okres, w którym miała miejsce nieobecność. B2BNET zastrzega sobie prawo "
            "do potrącenia tej kary z wynagrodzenia Partnera lub żądania jej "
            "zwrotu.",
        ),
        (
            "p",
            "5. Partner zobowiązuje się do dostarczenia „Raportu z "
            "wykonywanych usług” do 3 dni po skończonym okresie rozliczeniowym na "
            "adres mailowy: rozliczenia@b2bnetwork.pl. B2BNET ma prawo odrzucić "
            "„Raport z wykonywanych usług” w momencie opóźnienia w dostarczeniu "
            "„Raportu” do B2BNET.",
        ),
        *_ALIOR_SIG_PL,
    )


def _alior_table_en() -> tuple[Block, ...]:
    return (
        ("gap", ""),
        ("sub", "DETAILED PROVISIONS OF THE AGREEMENT:"),
        (
            "p",
            "1. The Partner undertakes that, during the period of providing "
            "the Services for the Customer Alior Bank S.A., it will not accept "
            "orders that would objectively prevent the performance of the Services "
            "in accordance with the agreed availability and project deadlines, or "
            "that would cause a conflict of interest towards the Customer Alior Bank "
            "S.A. The above does not exclude the possibility of providing services "
            "to other entities, provided that this does not breach the obligations "
            "towards B2BNET and the B2BNET Customer, in particular the rules of "
            "confidentiality and security.",
        ),
        (
            "p",
            "2. The Partner undertakes to provide its services to the B2BNET "
            "Customer, which is Alior Bank S.A., in accordance with the agreed terms "
            "and project schedule. The Partner shall be available throughout the "
            "entire duration of the project and shall take all necessary actions to "
            "ensure the continuity and effectiveness of the work.",
        ),
        (
            "p",
            "3. The Partner is obliged to inform both the B2BNET Customer and "
            "B2BNET itself of a planned absence at least 5 days before the planned "
            "date of absence, unless extraordinary circumstances arise that prevent "
            "earlier notification. Should such extraordinary circumstances occur, "
            "the Partner is obliged to report the absence as soon as possible after "
            "their occurrence.",
        ),
        (
            "p",
            "4. Unexcused and unreported absences of the Partner shall be "
            "subject to a penalty of 5% of the remuneration due to the Partner for "
            "the period in which the absence occurred. B2BNET reserves the right to "
            "deduct this penalty from the Partner's remuneration or to demand its "
            "return.",
        ),
        (
            "p",
            "5. The Partner undertakes to deliver the „Report on Services "
            "Performed” within 3 days after the end of the settlement period to the "
            "e-mail address: rozliczenia@b2bnetwork.pl. B2BNET has the right to "
            "reject the „Report on Services Performed” in the event of a delay in "
            "delivering the „Report” to B2BNET.",
        ),
        *_ALIOR_SIG_PL,
    )


def _ops_alior(lang: str) -> list[Op]:
    if lang == "en":
        return [
            ("append_to_section", 4, _alior_s4a_en()),
            ("append_to_section", 9, _alior_s9_5_en()),
            ("after_table", 0, _alior_table_en()),
        ]
    return [
        ("append_to_section", 4, _alior_s4a_pl()),
        ("append_to_section", 9, _alior_s9_5_pl()),
        ("after_table", 0, _alior_table_pl()),
    ]


# ════════════════════════════════════════════════════════════════════════════
# Credit Agricole — nowy Załącznik nr 4 (na końcu umowy)
# ════════════════════════════════════════════════════════════════════════════

_SIG_PL = (
    ("gap", ""),
    ("sig", "__________________________            ______________________________"),
    (
        "sig",
        "Podpis osoby reprezentującej B2B.NET S.A.            "
        "Podpis osoby reprezentującej Partnera",
    ),
)
_SIG_EN = (
    ("gap", ""),
    ("sig", "__________________________            ______________________________"),
    (
        "sig",
        "Signature of the person representing B2B.NET S.A.            "
        "Signature of the person representing the Partner",
    ),
)


def _ca_appendix_pl() -> tuple[Block, ...]:
    return (
        (
            "h",
            "Załącznik nr 4 – Szczególne wymagania dotyczące realizacji usług "
            "na rzecz Klienta Projektu - Credit Agricole Bank Polska S.A.",
        ),
        (
            "sub",
            "Szczególne wymagania dotyczące realizacji usług na rzecz "
            "Klienta Projektu - Credit Agricole Bank Polska S.A.",
        ),
        (
            "p",
            "Niniejszy Załącznik stosuje się, gdy Klientem Projektu wskazanym "
            "w Załączniku nr 3 jest Credit Agricole Bank Polska S.A. dalej jak: "
            "„Bank” lub „Credit Agricole”. W przypadku sprzeczności pomiędzy "
            "postanowieniami niniejszego Załącznika a postanowieniami Umowy "
            "Głównej, pierwszeństwo mają postanowienia niniejszego Załącznika, "
            "wyłącznie w zakresie Usług świadczonych na rzecz Banku. Partner "
            "zobowiązany jest do przestrzegania regulacji, zasad i procedur "
            "obowiązujących u Banku, o ile zostały mu przekazane lub udostępnione "
            "przez B2BNET lub Bank.",
        ),
        (
            "sh",
            "§ 1. Wymagania wobec Partnera przed przystąpieniem do realizacji Usług",
        ),
        (
            "p",
            "1. Warunkiem przystąpienia Partnera do realizacji Usług jest "
            "uprzednie spełnienie wymogów formalnych, organizacyjnych i "
            "bezpieczeństwa wskazanych przez B2BNET lub Bank, w zakresie, w jakim "
            "dotyczą one Usług powierzonych Partnerowi.",
        ),
        ("p", "2. Partner zobowiązuje się w szczególności do:"),
        (
            "i",
            "a) podpisania i dostarczenia do B2BNET Deklaracji Poufności, "
            "stanowiącej Załącznik nr 1 do Umowy,",
        ),
        (
            "i",
            "b) podpisania i dostarczenia do B2BNET Umowy Powierzenia "
            "Przetwarzania Danych Osobowych, stanowiącej Załącznik nr 2 do Umowy,",
        ),
        (
            "i",
            "c) zaświadczenia o zapoznaniu się z wewnętrznymi regulacjami, "
            "zasadami i procedurami Banku dotyczącymi bezpieczeństwa informacji, "
            "ochrony danych osobowych, tajemnicy bankowej, zasad dostępu do "
            "systemów, pomieszczeń, infrastruktury IT oraz zasad korzystania ze "
            "sprzętu, urządzeń, aplikacji i innych zasobów Credit Agricole,",
        ),
        (
            "i",
            "d) przekazania B2BNET informacji lub dokumentów niezbędnych do "
            "wykazania wobec Banku posiadania przez Partnera kwalifikacji, "
            "doświadczenia lub referencji wymaganych dla realizacji Usług, w "
            "terminie 2 dni roboczych od dnia otrzymania takiego żądania.",
        ),
        (
            "p",
            "3. Niedostarczenie wymaganych dokumentów lub informacji, o "
            "których mowa w ust. 2, w terminie wyznaczonym przez B2BNET traktowane "
            "jest jako nieprzystąpienie do realizacji Usług w rozumieniu §4 ust. 8 "
            "Umowy Głównej i skutkuje naliczeniem przewidzianej tam kary umownej.",
        ),
        ("sh", "§ 2. Podwykonawstwo i zmiana osoby realizującej Usługi"),
        (
            "p",
            "1. Partner zobowiązuje się wykonywać Usługi osobiście i nie jest "
            "uprawniony do powierzania wykonania całości lub części Usług osobom "
            "trzecim, w tym dalszym podwykonawcom, współpracownikom, pracownikom, "
            "konsultantom lub innym osobom, bez uprzedniej zgody B2BNET wyrażonej w "
            "formie pisemnej pod rygorem nieważności.",
        ),
        (
            "p",
            "2. Partner przyjmuje do wiadomości, że Bank jest uprawniony do "
            "żądania odsunięcia osoby realizującej Usługi od projektu, w "
            "szczególności w przypadku naruszenia prawa, postanowień umowy zawartej "
            "pomiędzy B2BNET a Bankiem, zasad poufności, tajemnicy bankowej, "
            "ochrony danych osobowych, zasad bezpieczeństwa, regulacji Banku lub "
            "innych wymogów obowiązujących przy realizacji Usług.",
        ),
        (
            "p",
            "3. W przypadku otrzymania przez B2BNET żądania Banku dotyczącego "
            "odsunięcia Partnera od realizacji Usług, B2BNET jest uprawniona do "
            "natychmiastowego wstrzymania wykonywania Usług przez Partnera, "
            "ograniczenia lub odebrania Partnerowi dostępu do środowisk, systemów, "
            "informacji i aktywów Banku oraz podjęcia innych działań niezbędnych do "
            "wykonania żądania Banku.",
        ),
        (
            "p",
            "4. Partnerowi nie przysługują wobec B2BNET jakiekolwiek roszczenia "
            "z tytułu odsunięcia od realizacji Usług, jeżeli odsunięcie nastąpiło z "
            "przyczyn leżących po stronie Partnera albo w związku z uzasadnionym "
            "żądaniem Banku.",
        ),
        ("sh", "§ 3. Regulacje Banku, instruktaże i szkolenia"),
        (
            "p",
            "1. Partner przed uzyskaniem dostępu do systemów informatycznych, "
            "obiektów, informacji lub zasobów Banku zobowiązany jest zapoznać się z "
            "regulacjami, zasadami i procedurami Banku przekazanymi przez B2BNET lub "
            "Bank oraz przestrzegać ich przez cały okres realizacji Usług.",
        ),
        (
            "p",
            "2. Partner zobowiązuje się uczestniczyć w instruktażach, "
            "programach zwiększania świadomości lub szkoleniach dotyczących "
            "bezpieczeństwa informacji, bezpieczeństwa teleinformatycznego, ochrony "
            "danych osobowych, compliance, zasad dostępu do systemów lub "
            "operacyjnej odporności cyfrowej sektora finansowego, jeżeli zostaną "
            "one wskazane przez B2BNET lub Bank jako wymagane dla osób realizujących "
            "Usługi na rzecz Banku.",
        ),
        (
            "p",
            "3. Jeżeli udział w danym instruktażu, programie lub szkoleniu "
            "zostanie wskazany przez B2BNET lub Bank jako warunek uzyskania albo "
            "utrzymania dostępu do systemów, obiektów, informacji lub zasobów Banku, "
            "Partner nie jest uprawniony do wykonywania Usług w zakresie "
            "wymagającym takiego dostępu do czasu spełnienia tego warunku.",
        ),
        (
            "p",
            "4. Nieodbycie wymaganego instruktażu, programu lub szkolenia z "
            "przyczyn leżących po stronie Partnera skutkuje brakiem możliwości "
            "świadczenia Usług w zakresie, w jakim udział ten jest wymagany przez "
            "B2BNET lub Bank, a Partnerowi nie przysługuje z tego tytułu "
            "wynagrodzenie ani jakiekolwiek inne roszczenia wobec B2BNET za okres, w "
            "którym nie świadczył Usług.",
        ),
        (
            "p",
            "5. Odmowa udziału w wymaganym instruktażu, programie lub "
            "szkoleniu albo niespełnienie warunku wymaganego przez B2BNET lub Bank, "
            "jeżeli uniemożliwia Partnerowi wykonywanie Usług na rzecz Banku albo "
            "uzyskanie lub utrzymanie wymaganego dostępu, stanowi nienależyte "
            "wykonanie Umowy. W przypadku nieusunięcia naruszenia w terminie "
            "wyznaczonym przez B2BNET, B2BNET może rozwiązać Umowę ze skutkiem "
            "natychmiastowym na podstawie § 12 ust. 3 Umowy Głównej.",
        ),
        (
            "p",
            "6. Postanowień ust. 4 i 5 nie stosuje się w przypadku "
            "niewykonania lub nienależytego wykonania obowiązków, o których mowa w "
            "niniejszym paragrafie, spowodowanego działaniem siły wyższej. Partner "
            "zobowiązany jest do niezwłocznego poinformowania B2BNET o wystąpieniu "
            "siły wyższej oraz do podjęcia działań zmierzających do spełnienia "
            "wymaganych obowiązków niezwłocznie po ustaniu okoliczności siły "
            "wyższej.",
        ),
        (
            "sh",
            "§ 4. Korzystanie ze sprzętu, identyfikatorów i zasobów Credit Agricole.",
        ),
        (
            "p",
            "1. Partner zobowiązany jest do korzystania ze sprzętu, urządzeń, "
            "aplikacji, systemów, repozytoriów, sieci, identyfikatorów, tokenów, "
            "certyfikatów, danych dostępowych, materiałów oraz innych zasobów "
            "udostępnionych przez B2BNET lub Bank wyłącznie zgodnie z ich "
            "przeznaczeniem i wyłącznie w celu realizacji Usług.",
        ),
        (
            "p",
            "2. Partner może korzystać z zasobów Banku wyłącznie na podstawie "
            "udzielonego upoważnienia, w zakresie nadanych uprawnień i przez okres "
            "niezbędny do realizacji Usług.",
        ),
        (
            "p",
            "3. Partnerowi zabrania się udostępniania osobom trzecim sprzętu, "
            "urządzeń, nośników, kart dostępu, identyfikatorów, tokenów, loginów, "
            "haseł, certyfikatów lub innych środków uwierzytelniających przekazanych "
            "albo udostępnionych w związku z realizacją Usług.",
        ),
        (
            "p",
            "4. Partnerowi zabrania się podejmowania prób dostępu do zasobów "
            "Banku, do których dostęp nie został mu nadany, przełamywania "
            "zabezpieczeń Banku, nieautoryzowanego testowania podatności systemów "
            "Banku, podłączania do sprzętu Banku nieautoryzowanych urządzeń "
            "zewnętrznych lub sieciowych, instalowania nieautoryzowanego "
            "oprogramowania albo modyfikowania parametrów technicznych aplikacji lub "
            "urządzeń Banku.",
        ),
        (
            "p",
            "5. Partner zobowiązuje się korzystać z powierzonych mu zasobów z "
            "zachowaniem należytej staranności i dbałości o ich stan techniczny "
            "oraz ponosi pełną odpowiedzialność materialną za utratę, zniszczenie "
            "lub uszkodzenie powierzonego mu sprzętu, urządzeń, nośników, "
            "identyfikatorów lub innych aktywów od chwili ich odbioru do chwili ich "
            "zwrotu albo trwałego usunięcia dostępu, zgodnie z § 4 ust. 5 i 6 Umowy "
            "Głównej.",
        ),
        (
            "p",
            "6. Partner zobowiązuje się niezwłocznie zgłosić B2BNET utratę, "
            "zniszczenie, uszkodzenie, kradzież, nieuprawnione użycie, ujawnienie "
            "lub podejrzenie naruszenia bezpieczeństwa jakiegokolwiek urządzenia, "
            "identyfikatora, tokenu, hasła, certyfikatu, nośnika, dostępu lub innego "
            "zasobu udostępnionego w związku z realizacją Usług.",
        ),
        ("sh", "§ 5. Tajemnica bankowa i poufność"),
        (
            "p",
            "1. Partner przyjmuje do wiadomości, że informacje uzyskane w "
            "związku z realizacją Usług na rzecz Credit Agricole mogą być objęte "
            "tajemnicą bankową w rozumieniu art. 104 ustawy z dnia 29 sierpnia "
            "1997 r. – Prawo bankowe (t.j. Dz.U. z 2023 r. poz. 2488 z późn. zm.).",
        ),
        (
            "p",
            "2. Partner zobowiązuje się zachować w tajemnicy wszelkie "
            "informacje uzyskane w związku z realizacją Usług na rzecz Banku, w "
            "szczególności informacje dotyczące Banku, Grupy Credit Agricole, "
            "klientów Banku, systemów, infrastruktury, zabezpieczeń, procesów, "
            "produktów, dokumentacji, organizacji pracy, strategii, warunków "
            "współpracy oraz danych przetwarzanych w środowisku Banku.",
        ),
        (
            "p",
            "3. Partner może wykorzystywać informacje, o których mowa w ust. 1 "
            "i 2, wyłącznie w celu i zakresie niezbędnym do wykonania Usług.",
        ),
        (
            "p",
            "4. Partnerowi zabrania się ujawniania, kopiowania, pobierania, "
            "utrwalania, przekazywania, publikowania lub wykorzystywania "
            "informacji, o których mowa w ust. 1 i 2, poza zakresem niezbędnym do "
            "realizacji Usług, chyba że B2BNET lub Bank udzielą uprzedniej zgody w "
            "wymaganej formie.",
        ),
        (
            "p",
            "5. Partner zobowiązuje się zachować w poufności sposób "
            "inicjowania połączeń zdalnych, adresy sieciowe, dane uwierzytelniające, "
            "loginy, hasła, tokeny, certyfikaty oraz inne informacje niezbędne do "
            "ustanowienia połączenia ze środowiskiem Banku.",
        ),
        (
            "p",
            "6. Partner zobowiązuje się przetwarzać dane osobowe wyłącznie "
            "zgodnie z Umową Główną, Załącznikiem nr 2 do Umowy Głównej, "
            "udokumentowanymi poleceniami B2BNET lub Banku oraz obowiązującymi "
            "przepisami prawa, w szczególności RODO.",
        ),
        (
            "p",
            "7. Partner zobowiązuje się zgłosić B2BNET każde naruszenie "
            "ochrony danych osobowych, tajemnicy bankowej lub informacji poufnych "
            "niezwłocznie, nie później niż w terminie 2 godzin od chwili powzięcia "
            "informacji o zdarzeniu.",
        ),
        (
            "p",
            "8. Obowiązek zachowania tajemnicy bankowej, danych osobowych oraz "
            "innych informacji prawnie chronionych wiąże Partnera również po "
            "rozwiązaniu, wypowiedzeniu lub wygaśnięciu Umowy, bezterminowo albo "
            "przez okres wynikający z bezwzględnie obowiązujących przepisów prawa. "
            "Dwunastomiesięczny termin wskazany w § 8 ust. 6 Umowy Głównej nie ma "
            "zastosowania do informacji objętych tajemnicą bankową, danych "
            "osobowych ani innych informacji prawnie chronionych.",
        ),
        (
            "p",
            "9. Naruszenie przez Partnera obowiązku zachowania tajemnicy "
            "bankowej, poufności, ochrony danych osobowych lub innych informacji "
            "prawnie chronionych stanowi rażące naruszenie Umowy w rozumieniu § 12 "
            "ust. 4 lit. a) Umowy Głównej.",
        ),
        ("sh", "§ 6. Bezpieczeństwo środowiska teleinformatycznego"),
        (
            "p",
            "1. Partner zobowiązuje się przestrzegać zasad bezpieczeństwa "
            "informacji, zasad bezpieczeństwa środowiska teleinformatycznego, zasad "
            "pracy zdalnej, zasad dostępu do środowisk Banku, zasad korzystania z "
            "infrastruktury Banku oraz innych standardów bezpieczeństwa "
            "przekazanych lub udostępnionych przez B2BNET lub Bank.",
        ),
        (
            "p",
            "2. Partner zobowiązuje się wykonywać Usługi w sposób, który nie "
            "doprowadzi do utraty, uszkodzenia, zniekształcenia, nieuprawnionej "
            "modyfikacji, usunięcia, ujawnienia, naruszenia integralności lub "
            "niedostępności danych Banku.",
        ),
        (
            "p",
            "3. Jeżeli wykonanie jakiejkolwiek czynności mogłoby wiązać się z "
            "ryzykiem utraty, uszkodzenia, naruszenia integralności lub dostępności "
            "danych Banku, Partner zobowiązuje się powstrzymać od jej wykonania do "
            "czasu uprzedniego poinformowania B2BNET i uzyskania dalszych "
            "instrukcji.",
        ),
        (
            "p",
            "4. Partner zobowiązuje się niezwłocznie, nie później niż w "
            "terminie 1 godziny od powzięcia informacji, zgłosić B2BNET każdy "
            "przypadek naruszenia lub podejrzenia naruszenia bezpieczeństwa "
            "środowiska teleinformatycznego Banku, w szczególności zdarzenie mogące "
            "wpływać na poufność, integralność, dostępność, autentyczność, "
            "rozliczalność, lub niezawodność danych, systemów, usług, sieci lub "
            "procesów Banku.",
        ),
        (
            "p",
            "5. Zgłoszenie, o którym mowa w ust. 4, powinno zawierać wszystkie "
            "znane Partnerowi informacje dotyczące zdarzenia, w szczególności, "
            "kiedy, w jakim zakresie oraz jakie dane, systemy, usługi lub sieci "
            "Banku zostały naruszone lub zagrożone naruszeniem.",
        ),
        (
            "p",
            "6. Partner zobowiązuje się współpracować z B2BNET i Bankiem przy "
            "ograniczeniu skutków incydentu, wyjaśnieniu jego przyczyn, przywróceniu "
            "danych lub prawidłowości ich struktury, zabezpieczeniu materiału "
            "dowodowego oraz wdrożeniu działań naprawczych.",
        ),
        ("sh", "§ 7. Miejsce świadczenia Usług"),
        (
            "p",
            "1. Partner zobowiązuje się świadczyć Usługi wyłącznie z "
            "lokalizacji zaakceptowanej przez B2BNET lub Bank.",
        ),
        (
            "p",
            "2. Świadczenie Usług poza uzgodnioną lokalizacją, w szczególności "
            "poza terytorium Rzeczypospolitej Polskiej, wymaga uprzedniej zgody "
            "B2BNET, a jeżeli wymagają tego zobowiązania wobec Banku - również zgody "
            "Banku.",
        ),
        (
            "p",
            "3. Świadczenie Usług poza terytorium Unii Europejskiej jest "
            "niedopuszczalne.",
        ),
        (
            "p",
            "4. Partner zobowiązuje się nie korzystać z infrastruktury, "
            "narzędzi, repozytoriów, urządzeń, usług chmurowych, kont, nośników ani "
            "środowisk znajdujących się poza terytorium Unii Europejskiej, jeżeli "
            "mogłoby to prowadzić do przetwarzania danych osobowych, tajemnicy "
            "bankowej, informacji poufnych lub danych Banku poza tym terytorium.",
        ),
        ("sh", "§ 8. Regulacje wewnętrzne Banku"),
        (
            "p",
            "1. Partner zobowiązuje się do przestrzegania wszelkich regulacji, "
            "zasad, instrukcji i procedur obowiązujących w Banku, które zostały mu "
            "przekazane lub udostępnione przez B2BNET albo Bank, w szczególności "
            "dotyczących dostępu do budynków, pomieszczeń, systemów, środowisk oraz "
            "infrastruktury informatycznej Banku, zasad bezpieczeństwa informacji, "
            "ochrony danych osobowych, tajemnicy bankowej, korzystania z "
            "powierzonych zasobów, zasad organizacyjnych oraz wymogów compliance.",
        ),
        (
            "p",
            "2. W zakresie nieuregulowanym niniejszym Załącznikiem Partner "
            "zobowiązany jest stosować się do wymagań i regulacji obowiązujących u "
            "Credit Agricole, przekazywanych przez B2BNET lub bezpośrednio przez "
            "Bank, o ile dotyczą one Usług wykonywanych przez Partnera.",
        ),
        (
            "p",
            "3. Naruszenie regulacji, zasad, instrukcji lub procedur Banku "
            "przez Partnera traktowane jest jako nienależyte wykonanie Umowy, a "
            "jeżeli naruszenie dotyczy poufności, tajemnicy bankowej, ochrony danych "
            "osobowych, bezpieczeństwa informacji lub zasad dostępu do systemów "
            "Banku - jako rażące naruszenie Umowy.",
        ),
        ("sh", "§ 9. Organizacja pracy i komunikacja"),
        (
            "p",
            "1. Partner zobowiązuje się wykonywać Usługi w uzgodnieniu z "
            "przedstawicielami B2BNET oraz Banku, zgodnie z zasadami organizacji "
            "pracy obowiązującymi w projekcie, w zakresie niezbędnym do prawidłowej "
            "realizacji Usług.",
        ),
        (
            "p",
            "2. Partner zobowiązuje się do bieżącego monitorowania kanałów "
            "komunikacji wskazanych przez B2BNET lub Bank, w szczególności poczty "
            "elektronicznej, komunikatorów, systemów zgłoszeniowych lub innych "
            "narzędzi projektowych, w dniach roboczych i godzinach obowiązujących w "
            "projekcie.",
        ),
        (
            "p",
            "3. Partner zobowiązuje się do rzetelnego i terminowego "
            "raportowania czasu świadczenia Usług oraz wykonanych czynności w "
            "systemach, narzędziach lub formatach wskazanych przez B2BNET lub "
            "Bank.",
        ),
        (
            "p",
            "4. Partner zobowiązuje się niezwłocznie informować B2BNET o "
            "wszelkich przeszkodach, ryzykach, opóźnieniach, błędach lub innych "
            "okolicznościach, które mogą mieć wpływ na prawidłową lub terminową "
            "realizację Usług.",
        ),
        ("sh", "§ 10. DORA, audyty i obowiązki regulacyjne"),
        (
            "p",
            "1. Partner przyjmuje do wiadomości, że Usługi świadczone na rzecz "
            "Banku mogą stanowić usługi ICT w rozumieniu przepisów dotyczących "
            "operacyjnej odporności cyfrowej sektora finansowego, w szczególności "
            "Rozporządzenia Parlamentu Europejskiego i Rady (UE) 2022/2554 z dnia "
            "14 grudnia 2022 r. w sprawie operacyjnej odporności cyfrowej sektora "
            "finansowego.",
        ),
        (
            "p",
            "2. Partner zobowiązuje się współpracować z B2BNET i Bankiem w "
            "zakresie niezbędnym do wykazania prawidłowości realizacji Usług oraz "
            "zgodności z wymogami regulacyjnymi, outsourcingowymi, bezpieczeństwa "
            "informacji, ciągłości działania oraz operacyjnej odporności cyfrowej "
            "sektora finansowego.",
        ),
        (
            "p",
            "3. Partner zobowiązuje się przekazywać B2BNET informacje, "
            "wyjaśnienia, dokumenty, raporty lub oświadczenia niezbędne do obsługi "
            "audytów, kontroli, przeglądów bezpieczeństwa, testów, ocen ryzyka, "
            "czynności sprawdzających, obowiązków raportowych Banku lub czynności "
            "realizowanych przez organy nadzoru, w zakresie, w jakim dotyczą Usług "
            "wykonywanych przez Partnera.",
        ),
        (
            "p",
            "4. Odmowa współpracy, nieudzielenie informacji, udzielenie "
            "informacji niepełnych, nieprawdziwych lub nierzetelnych, odmowa udziału "
            "w wymaganym szkoleniu albo utrudnianie czynności, o których mowa w "
            "niniejszym paragrafie, stanowi nienależyte wykonanie Umowy.",
        ),
        ("sh", "§ 11. Prawa własności intelektualnej, kod źródłowy i dokumentacja"),
        (
            "p",
            "1. Partner przyjmuje do wiadomości, że wszelkie efekty prac "
            "powstałe w związku z realizacją Usług na rzecz Banku, w szczególności "
            "kod źródłowy, dokumentacja, skrypty, konfiguracje, analizy, raporty "
            "oraz materiały projektowe, techniczne, funkcjonalne lub powykonawcze, "
            "podlegają zasadom określonym w § 5 Umowy Głównej.",
        ),
        (
            "p",
            "2. Partner zobowiązuje się wykonywać obowiązki określone w § 5 "
            "Umowy Głównej w sposób umożliwiający B2BNET skuteczne przeniesienie "
            "praw lub udzielenie uprawnień na rzecz Banku, Grupy Credit Agricole "
            "lub innych podmiotów uprawnionych zgodnie z umową zawartą pomiędzy "
            "B2BNET a Bankiem.",
        ),
        (
            "p",
            "3. Partner zobowiązuje się przekazać B2BNET, w terminach i formie "
            "wskazanych przez B2BNET lub Bank, kod źródłowy, dokumentację, "
            "informacje techniczne, wykazy bibliotek, narzędzi, zależności, "
            "konfiguracji, instrukcje oraz inne materiały niezbędne do korzystania, "
            "utrzymania, rozwoju, kompilacji, uruchomienia lub kontynuacji Usług.",
        ),
        ("sh", "§ 12. Sankcje międzynarodowe"),
        (
            "p",
            "1. Partner oświadcza, że nie jest osobą ani podmiotem objętym "
            "Sankcjami Międzynarodowymi, nie działa na rzecz takiej osoby lub "
            "podmiotu, nie jest przez taką osobę lub podmiot kontrolowany ani nie "
            "prowadzi działalności na Terytorium Sankcjonowanym w sposób mogący "
            "naruszać obowiązki B2BNET wobec Banku.",
        ),
        (
            "p",
            "2. Partner zobowiązuje się niezwłocznie poinformować B2BNET o "
            "każdej zmianie stanu faktycznego lub prawnego dotyczącego oświadczenia, "
            "o którym mowa w ust. 1.",
        ),
        (
            "p",
            "3. Złożenie nieprawdziwego oświadczenia albo brak niezwłocznego "
            "poinformowania B2BNET o zmianie, o której mowa w ust. 2, stanowi "
            "nienależyte wykonanie Umowy i może stanowić podstawę rozwiązania Umowy "
            "ze skutkiem natychmiastowym na podstawie § 12 ust. 3 Umowy Głównej.",
        ),
        (
            "sh",
            "§ 13. Odpowiedzialność Partnera za kary nałożone przez Credit Agricole",
        ),
        (
            "p",
            "1. W przypadku nałożenia na B2BNET przez Credit Agricole kary "
            "umownej, odszkodowania, kosztu lub innego obciążenia wynikającego "
            "bezpośrednio z działania lub zaniechania Partnera, niewykonania lub "
            "nienależytego wykonania przez Partnera Usług albo naruszenia przez "
            "Partnera obowiązków wynikających z Umowy, niniejszego Załącznika, "
            "regulacji Banku lub instrukcji przekazanych Partnerowi, Partner "
            "zobowiązany jest do zwrotu B2BNET równowartości kwoty faktycznie "
            "zapłaconej przez B2BNET z tego tytułu.",
        ),
        (
            "p",
            "2. Odpowiedzialność Partnera, o której mowa w ust. 1, obejmuje w "
            "szczególności obciążenia nałożone na B2BNET przez Bank z tytułu:",
        ),
        (
            "i",
            "a) wypowiedzenia przez Bank Zamówienia realizowanego z udziałem "
            "Partnera, jeżeli przyczyna wypowiedzenia pozostaje w bezpośrednim "
            "związku z działaniem lub zaniechaniem Partnera - w wysokości "
            "odpowiadającej karze naliczonej B2BNET przez Bank, w szczególności w "
            "wysokości 20% łącznego wynagrodzenia należnego B2BNET z tytułu "
            "realizacji danego Zamówienia;",
        ),
        (
            "i",
            "b) naruszenia zasad poufności, tajemnicy bankowej, ochrony danych "
            "osobowych lub innych informacji prawnie chronionych, jeżeli naruszenie "
            "wynika z działania lub zaniechania Partnera - w wysokości "
            "odpowiadającej karze naliczonej B2BNET przez Bank, w szczególności w "
            "wysokości 150.000,00 zł za każdy przypadek naruszenia;",
        ),
        (
            "i",
            "c) naruszenia zasad bezpieczeństwa środowiska teleinformatycznego, "
            "jeżeli naruszenie wynika z działania lub zaniechania Partnera - w "
            "wysokości odpowiadającej karze naliczonej B2BNET przez Bank, w "
            "szczególności w wysokości 50.000,00 zł za każdy przypadek naruszenia;",
        ),
        (
            "i",
            "d) naruszenia zasad osobistego świadczenia Usług, w szczególności "
            "podstawienia innej osoby do realizacji Usług bez wymaganej zgody B2BNET "
            "lub Banku albo przerwania świadczenia Usług przez Partnera z przyczyn "
            "leżących po stronie Partnera - w wysokości odpowiadającej karze "
            "naliczonej B2BNET przez Bank, w szczególności w wysokości 25.000,00 zł "
            "za każdy przypadek naruszenia;",
        ),
        (
            "i",
            "e) naruszenia zasad dotyczących podwykonawstwa, w szczególności "
            "dopuszczenia podwykonawcy bez wymaganej zgody Banku albo wykonywania "
            "czynności poza terytorium Unii Europejskiej - w wysokości "
            "odpowiadającej karze naliczonej B2BNET przez Bank, w szczególności w "
            "wysokości 10.000,00 zł za każdy przypadek naruszenia.",
        ),
        (
            "p",
            "3. Partner ponosi odpowiedzialność za kary umowne, o których mowa "
            "w ust. 1 i 2, wyłącznie w zakresie, w jakim zostały one naliczone "
            "B2BNET przez Bank i faktycznie zapłacone przez B2BNET, a ich naliczenie "
            "pozostaje w bezpośrednim związku z działaniem lub zaniechaniem "
            "Partnera, niewykonaniem lub nienależytym wykonaniem przez Partnera "
            "Usług albo naruszeniem przez Partnera obowiązków wynikających z Umowy, "
            "niniejszego Załącznika, regulacji Banku lub instrukcji przekazanych "
            "Partnerowi.",
        ),
        (
            "p",
            "4. Partner nie ponosi odpowiedzialności za kary umowne naliczone "
            "B2BNET przez Bank z przyczyn niezależnych od Partnera, w szczególności "
            "z przyczyn leżących wyłącznie po stronie B2BNET lub Banku.",
        ),
        (
            "p",
            "5. Zwrot kwoty, o której mowa w niniejszym paragrafie nastąpi w "
            "terminie 14 dni od dnia doręczenia Partnerowi noty obciążeniowej wraz z "
            "informacją o podstawie naliczenia kary przez Bank oraz dokumentacją "
            "potwierdzającą związek kary z działaniem lub zaniechaniem Partnera.",
        ),
        (
            "p",
            "6. Zapłata przez Partnera kwoty odpowiadającej karze umownej, "
            "odszkodowaniu lub innemu obciążeniu naliczonemu B2BNET przez Bank nie "
            "wyłącza prawa B2BNET do dochodzenia od Partnera odszkodowania "
            "przewyższającego wysokość tej kwoty, jeżeli szkoda poniesiona przez "
            "B2BNET pozostaje w bezpośrednim związku z działaniem lub zaniechaniem "
            "Partnera, niewykonaniem lub nienależytym wykonaniem przez Partnera "
            "Usług albo naruszeniem przez Partnera obowiązków wynikających z Umowy, "
            "niniejszego Załącznika, regulacji Banku lub instrukcji przekazanych "
            "Partnerowi.",
        ),
        (
            "p",
            "7. B2BNET jest uprawniona do potrącenia kwot wynikających z kar "
            "umownych o których mowa w niniejszym paragrafie z wynagrodzenia "
            "Partnera lub innymi świadczeniami należnymi Partnerowi, na co Partner "
            "wyraża zgodę.",
        ),
        (
            "p",
            "8. Postanowienie niniejszego paragrafu stanowi uszczegółowienie "
            "§9 ust. 5 Umowy Głównej w zakresie projektów realizowanych na rzecz "
            "Credit Agricole.",
        ),
        ("sh", "§ 14. Zakończenie świadczenia Usług"),
        (
            "p",
            "1. Partner zobowiązuje się do niezwłocznego poinformowania B2BNET "
            "o zakończeniu świadczenia Usług na rzecz Credit Agricole, w "
            "szczególności w celu umożliwienia odebrania dostępów, zwrotu sprzętu "
            "oraz wykonania innych czynności wymaganych przez Credit Agricole lub "
            "B2BNET przy zakończeniu współpracy.",
        ),
        (
            "p",
            "2. W przypadku zakończenia współpracy, rozwiązania lub wygaśnięcia "
            "Umowy, zakończenia zlecenia, odsunięcia Partnera od realizacji Usług "
            "albo żądania B2BNET lub Banku, Partner zobowiązuje się niezwłocznie "
            "przekazać B2BNET wszelkie materiały, dokumentację, kody źródłowe, "
            "repozytoria, dane dostępowe, loginy, hasła, instrukcje, informacje "
            "techniczne, statusy zadań oraz inne elementy niezbędne do kontynuacji "
            "realizacji Usług przez B2BNET, Bank lub innego wykonawcę.",
        ),
        (
            "p",
            "3. Partner zobowiązuje się niezwłocznie zwrócić albo trwale "
            "usunąć, zgodnie z instrukcją B2BNET, wszelkie informacje poufne, dane, "
            "dane osobowe, dokumenty, nośniki, urządzenia, identyfikatory, tokeny, "
            "materiały, aplikacje oraz inne aktywa przekazane mu lub wytworzone w "
            "związku z realizacją Usług.",
        ),
        (
            "p",
            "4. Czynności, o których mowa w niniejszym paragrafie, objęte są "
            "wynagrodzeniem Partnera i nie uprawniają Partnera do żądania "
            "dodatkowego wynagrodzenia, chyba że Strony wyraźnie postanowią inaczej.",
        ),
        ("sh", "§ 15. Postanowienia końcowe"),
        (
            "p",
            "1. Partner zobowiązuje się niezwłocznie informować B2BNET o każdej "
            "zmianie danych, statusu, miejsca świadczenia Usług, uprawnień, sytuacji "
            "prawnej, organizacyjnej lub faktycznej, która może mieć wpływ na "
            "możliwość świadczenia Usług na rzecz Banku.",
        ),
        (
            "p",
            "2. Postanowienia niniejszego Załącznika obowiązują przez okres "
            "wykonywania Usług na rzecz Banku, a w zakresie poufności, tajemnicy "
            "bankowej, ochrony danych osobowych, bezpieczeństwa informacji, praw "
            "własności intelektualnej, odpowiedzialności regresowej, kar umownych "
            "oraz obowiązków związanych z zakończeniem współpracy, również po "
            "rozwiązaniu, wypowiedzeniu lub wygaśnięciu Umowy.",
        ),
        (
            "p",
            "3. W przypadku sprzeczności pomiędzy postanowieniami niniejszego "
            "Załącznika, a pozostałymi postanowieniami Umowy, pierwszeństwo mają "
            "postanowienia niniejszego Załącznika, ale wyłącznie w zakresie Usług "
            "świadczonych na rzecz Banku.",
        ),
        *_SIG_PL,
    )


def _ca_appendix_en() -> tuple[Block, ...]:
    return (
        (
            "h",
            "Appendix No. 4 – Special requirements for the provision of "
            "services to the Project Customer - Credit Agricole Bank Polska S.A.",
        ),
        (
            "sub",
            "Special requirements for the provision of services to the "
            "Project Customer - Credit Agricole Bank Polska S.A.",
        ),
        (
            "p",
            "This Appendix applies where the Project Customer indicated in "
            "Appendix No. 3 is Credit Agricole Bank Polska S.A., hereinafter "
            "referred to as the „Bank” or „Credit Agricole”. In the event of any "
            "conflict between the provisions of this Appendix and the provisions of "
            "the Main Agreement, the provisions of this Appendix shall prevail, "
            "solely with respect to the Services provided to the Bank. The Partner "
            "is obliged to comply with the regulations, rules, and procedures "
            "applicable at the Bank, insofar as they have been provided or made "
            "available to the Partner by B2BNET or the Bank.",
        ),
        (
            "sh",
            "§ 1. Requirements for the Partner before commencing the "
            "provision of the Services",
        ),
        (
            "p",
            "1. A precondition for the Partner commencing the provision of the "
            "Services is the prior fulfilment of the formal, organizational, and "
            "security requirements indicated by B2BNET or the Bank, to the extent "
            "they concern the Services entrusted to the Partner.",
        ),
        ("p", "2. The Partner undertakes in particular to:"),
        (
            "i",
            "a) sign and deliver to B2BNET the Confidentiality Declaration "
            "constituting Appendix No. 1 to the Agreement,",
        ),
        (
            "i",
            "b) sign and deliver to B2BNET the Personal Data Processing "
            "Agreement constituting Appendix No. 2 to the Agreement,",
        ),
        (
            "i",
            "c) provide a certificate of having read the Bank's internal "
            "regulations, rules, and procedures concerning information security, "
            "personal data protection, banking secrecy, rules of access to systems, "
            "premises, IT infrastructure, and rules for using the equipment, "
            "devices, applications, and other resources of Credit Agricole,",
        ),
        (
            "i",
            "d) provide B2BNET with information or documents necessary to "
            "demonstrate to the Bank that the Partner holds the qualifications, "
            "experience, or references required for the provision of the Services, "
            "within 2 business days of receiving such a request.",
        ),
        (
            "p",
            "3. Failure to provide the required documents or information "
            "referred to in section 2 within the deadline set by B2BNET shall be "
            "treated as a failure to commence the provision of the Services within "
            "the meaning of § 4 section 8 of the Main Agreement and results in the "
            "imposition of the contractual penalty provided for therein.",
        ),
        ("sh", "§ 2. Subcontracting and change of the person providing the Services"),
        (
            "p",
            "1. The Partner undertakes to perform the Services personally and "
            "is not authorized to entrust the performance of all or part of the "
            "Services to third parties, including further subcontractors, "
            "associates, employees, consultants, or other persons, without the "
            "prior consent of B2BNET expressed in writing under pain of nullity.",
        ),
        (
            "p",
            "2. The Partner acknowledges that the Bank is entitled to demand "
            "the removal of the person providing the Services from the project, in "
            "particular in the event of a breach of law, of the provisions of the "
            "agreement concluded between B2BNET and the Bank, of confidentiality "
            "rules, banking secrecy, personal data protection, security rules, the "
            "Bank's regulations, or other requirements applicable to the provision "
            "of the Services.",
        ),
        (
            "p",
            "3. Where B2BNET receives a request from the Bank concerning the "
            "removal of the Partner from the provision of the Services, B2BNET is "
            "entitled to immediately suspend the performance of the Services by the "
            "Partner, to limit or withdraw the Partner's access to the Bank's "
            "environments, systems, information, and assets, and to take other "
            "actions necessary to fulfil the Bank's request.",
        ),
        (
            "p",
            "4. The Partner shall have no claims whatsoever against B2BNET on "
            "account of removal from the provision of the Services, where the "
            "removal occurred for reasons attributable to the Partner or in "
            "connection with a justified request of the Bank.",
        ),
        ("sh", "§ 3. Bank regulations, briefings, and training"),
        (
            "p",
            "1. Before gaining access to the Bank's IT systems, facilities, "
            "information, or resources, the Partner is obliged to read the Bank's "
            "regulations, rules, and procedures provided by B2BNET or the Bank and "
            "to comply with them throughout the entire period of providing the "
            "Services.",
        ),
        (
            "p",
            "2. The Partner undertakes to participate in briefings, awareness "
            "programs, or training concerning information security, ICT security, "
            "personal data protection, compliance, system access rules, or digital "
            "operational resilience of the financial sector, where these are "
            "indicated by B2BNET or the Bank as required for persons providing the "
            "Services to the Bank.",
        ),
        (
            "p",
            "3. If participation in a given briefing, program, or training is "
            "indicated by B2BNET or the Bank as a condition for obtaining or "
            "maintaining access to the Bank's systems, facilities, information, or "
            "resources, the Partner is not entitled to perform the Services to the "
            "extent requiring such access until that condition is fulfilled.",
        ),
        (
            "p",
            "4. Failure to complete the required briefing, program, or "
            "training for reasons attributable to the Partner results in the "
            "inability to provide the Services to the extent for which such "
            "participation is required by B2BNET or the Bank, and the Partner shall "
            "not be entitled to any remuneration or any other claims against B2BNET "
            "for the period during which the Partner did not provide the Services.",
        ),
        (
            "p",
            "5. Refusal to participate in a required briefing, program, or "
            "training, or failure to fulfil a condition required by B2BNET or the "
            "Bank, where it prevents the Partner from performing the Services for "
            "the Bank or from obtaining or maintaining the required access, "
            "constitutes improper performance of the Agreement. In the event of "
            "failure to remedy the breach within the deadline set by B2BNET, B2BNET "
            "may terminate the Agreement with immediate effect on the basis of § 12 "
            "section 3 of the Main Agreement.",
        ),
        (
            "p",
            "6. The provisions of sections 4 and 5 shall not apply in the case "
            "of non-performance or improper performance of the obligations referred "
            "to in this paragraph caused by force majeure. The Partner is obliged to "
            "promptly inform B2BNET of the occurrence of force majeure and to take "
            "actions aimed at fulfilling the required obligations promptly after the "
            "force majeure circumstances cease.",
        ),
        ("sh", "§ 4. Use of equipment, identifiers, and resources of Credit Agricole."),
        (
            "p",
            "1. The Partner is obliged to use the equipment, devices, "
            "applications, systems, repositories, networks, identifiers, tokens, "
            "certificates, access data, materials, and other resources made "
            "available by B2BNET or the Bank solely in accordance with their "
            "intended purpose and solely for the purpose of providing the "
            "Services.",
        ),
        (
            "p",
            "2. The Partner may use the Bank's resources solely on the basis "
            "of the authorization granted, within the scope of the granted "
            "permissions, and for the period necessary to provide the Services.",
        ),
        (
            "p",
            "3. The Partner is prohibited from making available to third "
            "parties the equipment, devices, media, access cards, identifiers, "
            "tokens, logins, passwords, certificates, or other authentication means "
            "provided or made available in connection with the provision of the "
            "Services.",
        ),
        (
            "p",
            "4. The Partner is prohibited from attempting to access the Bank's "
            "resources to which access has not been granted, breaking the Bank's "
            "security measures, unauthorized testing of the vulnerability of the "
            "Bank's systems, connecting unauthorized external or network devices to "
            "the Bank's equipment, installing unauthorized software, or modifying "
            "the technical parameters of the Bank's applications or devices.",
        ),
        (
            "p",
            "5. The Partner undertakes to use the entrusted resources with due "
            "diligence and care for their technical condition, and bears full "
            "material liability for the loss, destruction, or damage of the "
            "entrusted equipment, devices, media, identifiers, or other assets from "
            "the moment of their receipt until the moment of their return or "
            "permanent removal of access, in accordance with § 4 sections 5 and 6 "
            "of the Main Agreement.",
        ),
        (
            "p",
            "6. The Partner undertakes to promptly report to B2BNET the loss, "
            "destruction, damage, theft, unauthorized use, disclosure, or suspected "
            "security breach of any device, identifier, token, password, "
            "certificate, medium, access, or other resource made available in "
            "connection with the provision of the Services.",
        ),
        ("sh", "§ 5. Banking secrecy and confidentiality"),
        (
            "p",
            "1. The Partner acknowledges that information obtained in "
            "connection with the provision of the Services to Credit Agricole may "
            "be covered by banking secrecy within the meaning of Article 104 of the "
            "Act of 29 August 1997 – Banking Law (consolidated text: Journal of "
            "Laws of 2023, item 2488, as amended).",
        ),
        (
            "p",
            "2. The Partner undertakes to keep confidential all information "
            "obtained in connection with the provision of the Services to the Bank, "
            "in particular information concerning the Bank, the Credit Agricole "
            "Group, the Bank's customers, systems, infrastructure, security "
            "measures, processes, products, documentation, work organization, "
            "strategy, terms of cooperation, and data processed in the Bank's "
            "environment.",
        ),
        (
            "p",
            "3. The Partner may use the information referred to in sections 1 "
            "and 2 solely for the purpose and to the extent necessary to perform "
            "the Services.",
        ),
        (
            "p",
            "4. The Partner is prohibited from disclosing, copying, "
            "downloading, recording, transmitting, publishing, or using the "
            "information referred to in sections 1 and 2 beyond the scope necessary "
            "to provide the Services, unless B2BNET or the Bank grant prior consent "
            "in the required form.",
        ),
        (
            "p",
            "5. The Partner undertakes to keep confidential the manner of "
            "initiating remote connections, network addresses, authentication data, "
            "logins, passwords, tokens, certificates, and other information "
            "necessary to establish a connection with the Bank's environment.",
        ),
        (
            "p",
            "6. The Partner undertakes to process personal data solely in "
            "accordance with the Main Agreement, Appendix No. 2 to the Main "
            "Agreement, the documented instructions of B2BNET or the Bank, and "
            "applicable provisions of law, in particular the GDPR.",
        ),
        (
            "p",
            "7. The Partner undertakes to report to B2BNET any breach of "
            "personal data protection, banking secrecy, or confidential information "
            "promptly, no later than within 2 hours of becoming aware of the "
            "event.",
        ),
        (
            "p",
            "8. The obligation to maintain banking secrecy, personal data, and "
            "other legally protected information binds the Partner also after the "
            "termination, notice, or expiration of the Agreement, indefinitely or "
            "for the period resulting from mandatory provisions of law. The "
            "twelve-month period indicated in § 8 section 6 of the Main Agreement "
            "does not apply to information covered by banking secrecy, personal "
            "data, or other legally protected information.",
        ),
        (
            "p",
            "9. A breach by the Partner of the obligation to maintain banking "
            "secrecy, confidentiality, personal data protection, or other legally "
            "protected information constitutes a gross breach of the Agreement "
            "within the meaning of § 12 section 4 letter a) of the Main Agreement.",
        ),
        ("sh", "§ 6. Security of the ICT environment"),
        (
            "p",
            "1. The Partner undertakes to comply with the rules of information "
            "security, the rules of ICT environment security, remote work rules, "
            "the rules of access to the Bank's environments, the rules for using "
            "the Bank's infrastructure, and other security standards provided or "
            "made available by B2BNET or the Bank.",
        ),
        (
            "p",
            "2. The Partner undertakes to perform the Services in a manner "
            "that will not lead to the loss, damage, distortion, unauthorized "
            "modification, deletion, disclosure, breach of integrity, or "
            "unavailability of the Bank's data.",
        ),
        (
            "p",
            "3. If the performance of any activity could involve a risk of "
            "loss, damage, breach of the integrity or availability of the Bank's "
            "data, the Partner undertakes to refrain from performing it until prior "
            "notification of B2BNET and obtaining further instructions.",
        ),
        (
            "p",
            "4. The Partner undertakes to report to B2BNET promptly, no later "
            "than within 1 hour of becoming aware, any case of breach or suspected "
            "breach of the security of the Bank's ICT environment, in particular an "
            "event that may affect the confidentiality, integrity, availability, "
            "authenticity, accountability, or reliability of the Bank's data, "
            "systems, services, networks, or processes.",
        ),
        (
            "p",
            "5. The report referred to in section 4 should contain all "
            "information known to the Partner regarding the event, in particular "
            "when, to what extent, and which of the Bank's data, systems, services, "
            "or networks were breached or threatened with breach.",
        ),
        (
            "p",
            "6. The Partner undertakes to cooperate with B2BNET and the Bank "
            "in mitigating the effects of the incident, clarifying its causes, "
            "restoring data or the correctness of its structure, securing evidence, "
            "and implementing corrective measures.",
        ),
        ("sh", "§ 7. Place of providing the Services"),
        (
            "p",
            "1. The Partner undertakes to provide the Services solely from a "
            "location accepted by B2BNET or the Bank.",
        ),
        (
            "p",
            "2. Providing the Services outside the agreed location, in "
            "particular outside the territory of the Republic of Poland, requires "
            "the prior consent of B2BNET, and where the obligations towards the Bank "
            "so require - also the consent of the Bank.",
        ),
        (
            "p",
            "3. Providing the Services outside the territory of the European "
            "Union is impermissible.",
        ),
        (
            "p",
            "4. The Partner undertakes not to use infrastructure, tools, "
            "repositories, devices, cloud services, accounts, media, or "
            "environments located outside the territory of the European Union, where "
            "this could lead to the processing of personal data, banking secrecy, "
            "confidential information, or the Bank's data outside that territory.",
        ),
        ("sh", "§ 8. Internal regulations of the Bank"),
        (
            "p",
            "1. The Partner undertakes to comply with all regulations, rules, "
            "instructions, and procedures applicable at the Bank that have been "
            "provided or made available to the Partner by B2BNET or the Bank, in "
            "particular those concerning access to the Bank's buildings, premises, "
            "systems, environments, and IT infrastructure, the rules of information "
            "security, personal data protection, banking secrecy, the use of "
            "entrusted resources, organizational rules, and compliance "
            "requirements.",
        ),
        (
            "p",
            "2. To the extent not regulated by this Appendix, the Partner is "
            "obliged to comply with the requirements and regulations applicable at "
            "Credit Agricole, provided by B2BNET or directly by the Bank, insofar "
            "as they concern the Services performed by the Partner.",
        ),
        (
            "p",
            "3. A breach of the Bank's regulations, rules, instructions, or "
            "procedures by the Partner is treated as improper performance of the "
            "Agreement, and where the breach concerns confidentiality, banking "
            "secrecy, personal data protection, information security, or the rules "
            "of access to the Bank's systems - as a gross breach of the Agreement.",
        ),
        ("sh", "§ 9. Work organization and communication"),
        (
            "p",
            "1. The Partner undertakes to perform the Services in agreement "
            "with the representatives of B2BNET and the Bank, in accordance with the "
            "work organization rules applicable in the project, to the extent "
            "necessary for the proper provision of the Services.",
        ),
        (
            "p",
            "2. The Partner undertakes to continuously monitor the "
            "communication channels indicated by B2BNET or the Bank, in particular "
            "e-mail, messengers, ticketing systems, or other project tools, on "
            "business days and during the hours applicable in the project.",
        ),
        (
            "p",
            "3. The Partner undertakes to reliably and timely report the time "
            "of providing the Services and the activities performed in the systems, "
            "tools, or formats indicated by B2BNET or the Bank.",
        ),
        (
            "p",
            "4. The Partner undertakes to promptly inform B2BNET of any "
            "obstacles, risks, delays, errors, or other circumstances that may "
            "affect the proper or timely provision of the Services.",
        ),
        ("sh", "§ 10. DORA, audits, and regulatory obligations"),
        (
            "p",
            "1. The Partner acknowledges that the Services provided to the "
            "Bank may constitute ICT services within the meaning of the provisions "
            "on digital operational resilience of the financial sector, in "
            "particular Regulation (EU) 2022/2554 of the European Parliament and of "
            "the Council of 14 December 2022 on digital operational resilience for "
            "the financial sector.",
        ),
        (
            "p",
            "2. The Partner undertakes to cooperate with B2BNET and the Bank "
            "to the extent necessary to demonstrate the correctness of the "
            "provision of the Services and compliance with regulatory, outsourcing, "
            "information security, business continuity, and digital operational "
            "resilience requirements of the financial sector.",
        ),
        (
            "p",
            "3. The Partner undertakes to provide B2BNET with information, "
            "explanations, documents, reports, or declarations necessary to handle "
            "audits, controls, security reviews, tests, risk assessments, "
            "verification activities, the Bank's reporting obligations, or "
            "activities carried out by supervisory authorities, to the extent they "
            "concern the Services performed by the Partner.",
        ),
        (
            "p",
            "4. Refusal to cooperate, failure to provide information, "
            "provision of incomplete, untrue, or unreliable information, refusal to "
            "participate in required training, or obstruction of the activities "
            "referred to in this paragraph constitutes improper performance of the "
            "Agreement.",
        ),
        ("sh", "§ 11. Intellectual property rights, source code, and documentation"),
        (
            "p",
            "1. The Partner acknowledges that all results of work created in "
            "connection with the provision of the Services to the Bank, in "
            "particular source code, documentation, scripts, configurations, "
            "analyses, reports, and project, technical, functional, or as-built "
            "materials, are subject to the rules set out in § 5 of the Main "
            "Agreement.",
        ),
        (
            "p",
            "2. The Partner undertakes to perform the obligations set out in "
            "§ 5 of the Main Agreement in a manner enabling B2BNET to effectively "
            "transfer the rights or grant the authorizations to the Bank, the "
            "Credit Agricole Group, or other entities entitled under the agreement "
            "concluded between B2BNET and the Bank.",
        ),
        (
            "p",
            "3. The Partner undertakes to provide B2BNET, within the deadlines "
            "and in the form indicated by B2BNET or the Bank, with the source code, "
            "documentation, technical information, lists of libraries, tools, "
            "dependencies, configurations, instructions, and other materials "
            "necessary to use, maintain, develop, compile, run, or continue the "
            "Services.",
        ),
        ("sh", "§ 12. International sanctions"),
        (
            "p",
            "1. The Partner declares that it is not a person or entity subject "
            "to International Sanctions, does not act for the benefit of such a "
            "person or entity, is not controlled by such a person or entity, and "
            "does not conduct business in a Sanctioned Territory in a manner that "
            "could breach B2BNET's obligations towards the Bank.",
        ),
        (
            "p",
            "2. The Partner undertakes to promptly inform B2BNET of any change "
            "in the factual or legal status concerning the declaration referred to "
            "in section 1.",
        ),
        (
            "p",
            "3. Making a false declaration or failing to promptly inform "
            "B2BNET of a change referred to in section 2 constitutes improper "
            "performance of the Agreement and may constitute grounds for "
            "terminating the Agreement with immediate effect on the basis of § 12 "
            "section 3 of the Main Agreement.",
        ),
        ("sh", "§ 13. Partner's liability for penalties imposed by Credit Agricole"),
        (
            "p",
            "1. In the event of Credit Agricole imposing on B2BNET a "
            "contractual penalty, damages, cost, or other charge resulting directly "
            "from the Partner's act or omission, the Partner's non-performance or "
            "improper performance of the Services, or the Partner's breach of "
            "obligations arising from the Agreement, this Appendix, the Bank's "
            "regulations, or instructions provided to the Partner, the Partner is "
            "obliged to reimburse B2BNET the equivalent of the amount actually paid "
            "by B2BNET on this account.",
        ),
        (
            "p",
            "2. The Partner's liability referred to in section 1 includes in "
            "particular charges imposed on B2BNET by the Bank for:",
        ),
        (
            "i",
            "a) the Bank's termination of an Order carried out with the "
            "Partner's participation, where the reason for termination is directly "
            "related to the Partner's act or omission - in the amount corresponding "
            "to the penalty imposed on B2BNET by the Bank, in particular in the "
            "amount of 20% of the total remuneration due to B2BNET for the "
            "performance of the given Order;",
        ),
        (
            "i",
            "b) a breach of the rules of confidentiality, banking secrecy, "
            "personal data protection, or other legally protected information, "
            "where the breach results from the Partner's act or omission - in the "
            "amount corresponding to the penalty imposed on B2BNET by the Bank, in "
            "particular in the amount of PLN 150,000.00 for each instance of "
            "breach;",
        ),
        (
            "i",
            "c) a breach of the rules of ICT environment security, where the "
            "breach results from the Partner's act or omission - in the amount "
            "corresponding to the penalty imposed on B2BNET by the Bank, in "
            "particular in the amount of PLN 50,000.00 for each instance of "
            "breach;",
        ),
        (
            "i",
            "d) a breach of the rules of personal provision of the Services, "
            "in particular substituting another person to provide the Services "
            "without the required consent of B2BNET or the Bank, or interruption of "
            "the provision of the Services by the Partner for reasons attributable "
            "to the Partner - in the amount corresponding to the penalty imposed on "
            "B2BNET by the Bank, in particular in the amount of PLN 25,000.00 for "
            "each instance of breach;",
        ),
        (
            "i",
            "e) a breach of the rules concerning subcontracting, in particular "
            "engaging a subcontractor without the required consent of the Bank or "
            "performing activities outside the territory of the European Union - in "
            "the amount corresponding to the penalty imposed on B2BNET by the Bank, "
            "in particular in the amount of PLN 10,000.00 for each instance of "
            "breach.",
        ),
        (
            "p",
            "3. The Partner bears liability for the contractual penalties "
            "referred to in sections 1 and 2 solely to the extent that they were "
            "imposed on B2BNET by the Bank and actually paid by B2BNET, and their "
            "imposition is directly related to the Partner's act or omission, the "
            "Partner's non-performance or improper performance of the Services, or "
            "the Partner's breach of obligations arising from the Agreement, this "
            "Appendix, the Bank's regulations, or instructions provided to the "
            "Partner.",
        ),
        (
            "p",
            "4. The Partner shall not bear liability for contractual penalties "
            "imposed on B2BNET by the Bank for reasons beyond the Partner's control, "
            "in particular for reasons attributable solely to B2BNET or the Bank.",
        ),
        (
            "p",
            "5. The reimbursement of the amount referred to in this paragraph "
            "shall take place within 14 days from the date of delivery to the "
            "Partner of the debit note together with information on the basis for "
            "the imposition of the penalty by the Bank and documentation confirming "
            "the connection of the penalty with the Partner's act or omission.",
        ),
        (
            "p",
            "6. The Partner's payment of the amount corresponding to the "
            "contractual penalty, damages, or other charge imposed on B2BNET by the "
            "Bank does not exclude B2BNET's right to claim from the Partner damages "
            "exceeding the amount of that sum, where the damage suffered by B2BNET "
            "is directly related to the Partner's act or omission, the Partner's "
            "non-performance or improper performance of the Services, or the "
            "Partner's breach of obligations arising from the Agreement, this "
            "Appendix, the Bank's regulations, or instructions provided to the "
            "Partner.",
        ),
        (
            "p",
            "7. B2BNET is entitled to set off the amounts arising from the "
            "contractual penalties referred to in this paragraph against the "
            "Partner's remuneration or other benefits due to the Partner, to which "
            "the Partner consents.",
        ),
        (
            "p",
            "8. The provision of this paragraph constitutes a detailing of § 9 "
            "section 5 of the Main Agreement with respect to projects carried out "
            "for Credit Agricole.",
        ),
        ("sh", "§ 14. Completion of the provision of the Services"),
        (
            "p",
            "1. The Partner undertakes to promptly inform B2BNET of the "
            "completion of the provision of the Services to Credit Agricole, in "
            "particular in order to enable the withdrawal of access, the return of "
            "equipment, and the performance of other activities required by Credit "
            "Agricole or B2BNET upon the completion of cooperation.",
        ),
        (
            "p",
            "2. In the event of completion of cooperation, termination or "
            "expiration of the Agreement, completion of the order, removal of the "
            "Partner from the provision of the Services, or a request of B2BNET or "
            "the Bank, the Partner undertakes to promptly provide B2BNET with all "
            "materials, documentation, source code, repositories, access data, "
            "logins, passwords, instructions, technical information, task statuses, "
            "and other elements necessary for the continuation of the provision of "
            "the Services by B2BNET, the Bank, or another contractor.",
        ),
        (
            "p",
            "3. The Partner undertakes to promptly return or permanently "
            "delete, in accordance with B2BNET's instructions, all confidential "
            "information, data, personal data, documents, media, devices, "
            "identifiers, tokens, materials, applications, and other assets provided "
            "to the Partner or created in connection with the provision of the "
            "Services.",
        ),
        (
            "p",
            "4. The activities referred to in this paragraph are covered by "
            "the Partner's remuneration and do not entitle the Partner to demand "
            "additional remuneration, unless the Parties expressly agree "
            "otherwise.",
        ),
        ("sh", "§ 15. Final provisions"),
        (
            "p",
            "1. The Partner undertakes to promptly inform B2BNET of any change "
            "in data, status, place of providing the Services, permissions, or "
            "legal, organizational, or factual situation that may affect the ability "
            "to provide the Services to the Bank.",
        ),
        (
            "p",
            "2. The provisions of this Appendix are in force for the period of "
            "performing the Services for the Bank, and with respect to "
            "confidentiality, banking secrecy, personal data protection, "
            "information security, intellectual property rights, recourse liability, "
            "contractual penalties, and obligations related to the completion of "
            "cooperation, also after the termination, notice, or expiration of the "
            "Agreement.",
        ),
        (
            "p",
            "3. In the event of any conflict between the provisions of this "
            "Appendix and the remaining provisions of the Agreement, the provisions "
            "of this Appendix shall prevail, but solely with respect to the Services "
            "provided to the Bank.",
        ),
        *_SIG_EN,
    )


def _ops_credit_agricole(lang: str) -> list[Op]:
    blocks = _ca_appendix_en() if lang == "en" else _ca_appendix_pl()
    return [("append_appendix", None, blocks)]


# ════════════════════════════════════════════════════════════════════════════
# Rejestr: needle(s) → builder operacji. Pierwsze trafienie wygrywa.
# ════════════════════════════════════════════════════════════════════════════

CLIENT_OVERRIDES: list[tuple[tuple[str, ...], object]] = [
    (("pfron", "rehabilitacji osób niepełnosprawnych"), _ops_pfron),
    (("centrum e-zdrowia", "e-zdrowia"), _ops_centrum),
    (("bnp paribas",), _ops_bnp),
    (("alior",), _ops_alior),
    (("credit agricole",), _ops_credit_agricole),
]
