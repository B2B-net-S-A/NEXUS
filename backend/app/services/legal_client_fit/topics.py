"""Tematy back-to-back: wymogi umowy ramowej klienta, które muszą przejść na Partnera.

Katalog jest kodem, nie wynikiem modelu: model ocenia tylko tematy z tej
listy, a klucz tematu jest kluczem ustalenia (``UNIQUE (client_id, topic)``),
więc ponowne sprawdzenie nadpisuje ustalenie zamiast dokładać drugie.
Zapytanie ``query`` szuka fragmentów umowy klienta (słowa i znaczenie,
``framework_contract_index.search``) — po polsku i po angielsku, bo część
umów ramowych jest po angielsku.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Topic:
    key: str
    label: str
    #: Czego szukamy w umowie klienta (słowa i znaczenie).
    query: str
    #: Co sprawdzić w naszym wzorze — podpowiedź dla modelu.
    ours: str
    #: Następny krok przy luce (zdanie kodu, nie modelu).
    gap_step: str


TOPICS: tuple[Topic, ...] = (
    Topic(
        key="ict_training",
        label="Szkolenia ICT i DORA ludzi podwykonawcy",
        query="szkolenia bezpieczeństwo ICT DORA świadomość personel podwykonawcy "
        "security awareness training staff subcontractor",
        ours="obowiązek udziału Partnera w szkoleniach z bezpieczeństwa ICT "
        "i programach świadomości wymaganych przez klienta",
        gap_step="Dopisz obowiązek szkoleń w aneksie do umów B2B u tego klienta "
        "i zaproponuj klauzulę do nowych umów.",
    ),
    Topic(
        key="incident_reporting",
        label="Zgłaszanie incydentów i zdarzeń",
        query="zgłaszanie incydentów zdarzenie naruszenie bezpieczeństwa niezwłocznie "
        "incident notification report breach without undue delay",
        ours="obowiązek i termin zgłaszania incydentów oraz naruszeń bezpieczeństwa",
        gap_step="Dopisz w aneksie obowiązek i termin zgłaszania incydentów "
        "taki jak w umowie klienta.",
    ),
    Topic(
        key="data_location",
        label="Lokalizacja danych i praca spoza EOG",
        query="lokalizacja danych przetwarzanie poza EOG państwo trzecie praca zdalna "
        "z zagranicy data location outside EEA third country remote work abroad",
        ours="zakaz albo zgoda na pracę i przetwarzanie danych spoza EOG",
        gap_step="Dopisz w aneksie, skąd Partner może pracować i gdzie mogą być "
        "przetwarzane dane klienta.",
    ),
    Topic(
        key="nda_client_template",
        label="NDA na wzorze klienta",
        query="oświadczenie o zachowaniu poufności wzór klienta zobowiązanie do "
        "poufności załącznik confidentiality undertaking template personnel NDA",
        ours="deklaracja poufności Partnera i czy jest na wzorze klienta",
        gap_step="Zbierz od Partnerów oświadczenie o poufności na wzorze klienta "
        "albo dopisz je w aneksie.",
    ),
    Topic(
        key="consultant_replacement",
        label="Wymiana konsultanta z uprzedzeniem",
        query="wymiana konsultanta zastępstwo okres wypowiedzenia uprzedzenie "
        "zmiana personelu replacement of consultant notice period personnel change",
        ours="okres wypowiedzenia Partnera i obowiązek uprzedzenia o zakończeniu "
        "albo zastępstwie",
        gap_step="Sprawdź, czy okres wypowiedzenia w umowach B2B daje czas na "
        "wymianę konsultanta wymagany przez klienta; jeśli nie — aneks.",
    ),
    Topic(
        key="copyright",
        label="Prawa autorskie i licencje",
        query="przeniesienie autorskich praw majątkowych pola eksploatacji licencja "
        "utwór intellectual property transfer of copyright licence",
        ours="przeniesienie autorskich praw majątkowych na B2BNET i pola eksploatacji",
        gap_step="Uzupełnij w aneksie pola eksploatacji i moment przeniesienia praw "
        "tak, żeby B2BNET mógł je przenieść na klienta.",
    ),
    Topic(
        key="personal_data",
        label="Dane osobowe i dalsze powierzenie",
        query="powierzenie przetwarzania danych osobowych dalsze powierzenie "
        "podprzetwarzający zgoda sub-processor data processing agreement RODO GDPR",
        ours="umowa powierzenia przetwarzania danych (DPA) i zasady dalszego "
        "powierzenia",
        gap_step="Sprawdź, czy umowa powierzenia z Partnerem pozwala na dalsze "
        "powierzenie na warunkach klienta; jeśli nie — aneks.",
    ),
    Topic(
        key="audit_rights",
        label="Prawo audytu i dostępu klienta",
        query="audyt kontrola dostęp do informacji organ nadzoru prawo inspekcji "
        "audit rights access inspection supervisory authority",
        ours="zgoda Partnera na audyt i kontrolę klienta oraz organu nadzoru",
        gap_step="Dopisz w aneksie zgodę Partnera na audyt klienta i organu nadzoru.",
    ),
)

TOPIC_BY_KEY: dict[str, Topic] = {topic.key: topic for topic in TOPICS}

DECIDE_STEP = (
    "Do decyzji: porównaj oba zapisy z Delivery Leadem klienta; przy karze "
    "umownej albo sporze — z prawnikiem."
)
