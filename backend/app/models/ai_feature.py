"""AI feature settings + usage log.

Inspired by Traffit's "Ustawienia AI" panel: each AI-powered capability
(scoring, job description generator, CV parser, candidate AI summary, etc.)
has its own toggle and monthly call limit. Calls are counted in `ai_usage_log`
and reset on the 1st of each month.

Why a config table instead of env vars:
- Admin can flip toggles in production without restart.
- Per-feature monthly limits are visible in the Settings UI alongside
  current usage (Traffit shows "2 994 / 20 000 scoringów").

Why a single global config (no per-tenant): NEXUS is single-tenant
(one B2B Network instance). Multi-tenant would add `org_id` everywhere.
"""

import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class AIFeatureKey(str, enum.Enum):
    """Stable keys for AI-powered capabilities exposed in Settings → AI.

    Adding a new feature: add the enum value here, run a migration to extend
    the Postgres enum, seed a default row in `ai_features`, then wrap the
    relevant endpoint with `@check_ai_quota(AIFeatureKey.X)`.
    """

    scoring = "scoring"
    job_description_generator = "job_description_generator"
    cv_parser = "cv_parser"
    candidate_summary = "candidate_summary"
    champion_draft = "champion_draft"
    order_parser = "order_parser"
    cv_requirement_map = "cv_requirement_map"
    cv_interactive_chat = "cv_interactive_chat"
    # Masowe uzupełnianie pól kandydata z tekstu CV (Fala 3). OSOBNY klucz od
    # `cv_parser`, żeby bieg na ~39 tys. CV nie wyczerpał miesięcznego limitu
    # rekruterów ani nie wymusił podniesienia go do poziomu, na którym przestaje
    # chronić funkcję interaktywną.
    cv_backfill = "cv_backfill"
    # Dopisywanie DAT do `experience` dla kandydatów, których ATLAS właśnie
    # pokazał na kartotece firmy (`integrations_companies`). OSOBNY kubełek od
    # `cv_backfill`, choć wołają ten sam moduł: 16.09 zgaszenie `cv_backfill`
    # w celu zatrzymania biegu masowego ubiło rykoszetem fazę
    # `candidates_cv_fields` nocnego syncu Traffita. Ścieżka uruchamiana
    # ruchem użytkownika musi dać się wyłączyć, nie gasząc nocnej.
    experience_dates_on_demand = "experience_dates_on_demand"
    # Cykliczna ekstrakcja faktów z notatek (pętla notes_insights_sync) —
    # osobny kubełek z tego samego powodu co cv_backfill.
    notes_extraction = "notes_extraction"
    champion_profile_parse = "champion_profile_parse"
    # Generowanie CV B2B — NAJDROŻSZE wywołanie Claude'a w produkcie (16 384
    # tokeny outputu, łańcuch Sonnet → Opus, do 3 prób na model), a do 0240
    # stało całkowicie poza systemem kwot: bez klucza nie było ani miesięcznego
    # sufitu, ani jednego wiersza w `ai_usage_log`, więc raport zużycia w
    # Ustawieniach → AI zaniżał realne wydatki dokładnie o tę powierzchnię.
    cv_generator = "cv_generator"
    # MINDY (DynaReporter): JEDEN kubełek na oba endpointy LLM — `/commentary`
    # i `/chat`. Rozdzielenie ich dałoby dwa sufity do pilnowania dla jednej
    # funkcji, a `/commentary` odpala się sam przy montowaniu strony, więc to
    # ten sam strumień wydatku co czat.
    mindy_chat = "mindy_chat"
    # Lint instrukcji klienta dla generatora CV przy zapisie reguły (0267):
    # tani model ocenia każdą linię — prezentacja czy dopisywanie faktów.
    # Osobny kubełek: inny strumień wydatku niż generacja, inna osoba płaci
    # (Delivery Lead przy setupie, nie rekruter przy każdym CV).
    cv_rule_lint = "cv_rule_lint"
    # Sprawdzenie opisu zakresu usług pod kątem znamion umowy o pracę
    # (Generator Umów B2B). Do 0270 stało CAŁKOWICIE poza systemem kwot:
    # ani sufitu, ani wiersza w `ai_usage_log`, a główny wyłącznik go nie
    # dotyczył — potwierdzone na prodzie 02.09 (15,4 s wywołania, licznik bez
    # ruchu). Klucz jest też WARUNKIEM zdjęcia `cv_generator_b2b/ai_client.py`
    # z `_RAW_CLIENT_BASELINE`: bez niego `_assert_declared` zaczyna widzieć tę
    # trasę, a handler łapie tylko `CVGeneratorAIError`/`ValueError`, więc
    # `AIQuotaUngated` wychodzi jako nieobsłużone 500.
    uop_check = "uop_check"
    # Uzupełnianie IMION z tekstu CV w nocnym syncu Traffita (faza
    # `candidates_enrich_names`). OSOBNY kubełek od `cv_backfill`, choć nazwy
    # modułów mylą: `cv_backfill` należy do `cv_field_backfill.py` i ma
    # ODWROTNĄ semantykę wyczerpanej kwoty — tam bieg się ZATRZYMUJE, a
    # `parse_cv(db=…)` tylko pomija Claude i leci fallbackiem. Dwa przeciwne
    # zachowania pod jednym kluczem są nie do wytłumaczenia operatorowi.
    # `cv_parser` też odpada: bieg na dziesiątkach tysięcy CV zjadłby sufit
    # rekruterów pracujących interaktywnie.
    cv_name_backfill = "cv_name_backfill"
    # Niezależna kontrola AI treści wygenerowanego/edytowanego CV (drugi
    # model, decyzja Artura 18.09.2026). OSOBNY kubełek od `cv_generator`,
    # choć biegnie w tym samym żądaniu: recenzent jest INNYM modelem (GPT
    # Luna — sędzia nie może oceniać własnej pracy), więc jego wydatek ma być
    # widoczny obok generacji, a `CV_FINAL_REVIEW_ENABLED` ma go dać zgasić
    # bez dotykania generatora.
    cv_factual_verification = "cv_factual_verification"
    # Jarvis — asystent-agent w shellu aplikacji (0330, zastępuje MINDY).
    # Jedna tura = pętla modelu z narzędziami, więc wiele wywołań dostawcy na
    # jedną operację. Osobny kubełek, bo to inny strumień wydatku niż MINDY
    # (każda rola, każdy ekran) i musi dać się policzyć i zgasić osobno.
    jarvis = "jarvis"
    # Szkic publicznego opisu rekrutacji na stronę kariery (0339). Osobny
    # kubełek: inny strumień wydatku (rekruter przy udostępnianiu linku) i inny
    # prompt (zakaz nazwy klienta i kwot).
    job_public_description = "job_public_description"
    # Podpowiedzi odpowiedzi na pytania screeningu przy przepięciu (0352).
    # Wyłącznie przyciskiem z warsztatu rekrutera; wynik nic nie zapisuje.
    screening_reassign_suggest = "screening_reassign_suggest"
    # Podpowiedzi dla zatwierdzającego DZ (0353): GPT-6 Luna porównuje CV
    # przygotowane dla klienta z oryginałem i zapytaniem klienta (must-have,
    # pogrubienia, pokrycie w doświadczeniu). Osobny kubełek — inny odbiorca
    # (Delivery Lead / Head of Recruitment) i inny strumień wydatku niż
    # recenzja faktów przy generacji.
    dz_review = "dz_review"
    # Ocena prepu z transkryptu Teams (0369): czy w Prepie 1/2 omówiono
    # must-have z Championa i przećwiczono pytania tego klienta — punkt po
    # punkcie z cytatem — plus krótkie podsumowanie do notatki kandydata.
    prep_review = "prep_review"


# Human-readable labels surfaced in the Settings UI (PL — primary language
# of NEXUS recruiters; we don't expose the keys directly).
FEATURE_LABELS: dict[AIFeatureKey, str] = {
    AIFeatureKey.scoring: "Uzasadnienie dopasowania (AI)",
    AIFeatureKey.job_description_generator: "Generator ogłoszeń",
    AIFeatureKey.cv_parser: "Tworzenie kandydata z CV",
    AIFeatureKey.candidate_summary: "Podsumowanie kandydata",
    AIFeatureKey.champion_draft: "Profil Championa AI",
    AIFeatureKey.order_parser: "Odczyt danych z PDF zamówienia",
    AIFeatureKey.cv_requirement_map: "Interaktywne CV — kafelki wymagań",
    AIFeatureKey.cv_interactive_chat: "Interaktywne CV — chat klienta",
    AIFeatureKey.cv_backfill: "Masowe uzupełnianie pól z CV",
    AIFeatureKey.notes_extraction: "Fakty z notatek rekruterskich",
    AIFeatureKey.champion_profile_parse: "Odczyt profili Championa (Traffit)",
    AIFeatureKey.cv_generator: "Generator CV B2B",
    AIFeatureKey.mindy_chat: "MINDY — komentarz i czat (DynaReporter)",
    AIFeatureKey.cv_rule_lint: "Reguły CV klienta — lint instrukcji dla generatora",
    AIFeatureKey.uop_check: "Generator Umów B2B — sprawdzenie znamion umowy o pracę",
    AIFeatureKey.cv_name_backfill: "Uzupełnianie imion z CV (sync Traffita)",
    AIFeatureKey.cv_factual_verification: "Generator CV B2B — niezależna kontrola AI treści CV (drugi model)",
    AIFeatureKey.experience_dates_on_demand: "Daty zatrudnienia z CV (kartoteka firmy w ATLAS-ie)",
    AIFeatureKey.jarvis: "Jarvis — asystent i wykonawca zadań w aplikacji",
    AIFeatureKey.job_public_description: "Opis rekrutacji na stronę kariery",
    AIFeatureKey.screening_reassign_suggest: "Przepięcie — podpowiedzi odpowiedzi na pytania screeningu",
    AIFeatureKey.dz_review: "Przegląd DZ — podpowiedzi do CV dla klienta",
    AIFeatureKey.prep_review: "Ocena prepu z transkryptu Teams",
}


# Description of what data is sent to the LLM per feature. Surfaced in the UI
# under each feature card so admins know what leaves NEXUS.
FEATURE_DATA_SENT: dict[AIFeatureKey, list[str]] = {
    AIFeatureKey.scoring: [
        "Treść CV kandydatów",
        "Nazwa stanowiska i wymagania",
        "Competence Category + skills",
    ],
    AIFeatureKey.job_description_generator: [
        "Szczegóły rekrutacji (tytuł, wymagania, lokalizacja)",
        "Kontekst klienta (Client Knowledge)",
        "Wybrany tone of voice",
    ],
    AIFeatureKey.cv_parser: [
        "Treść CV kandydatów (PDF/DOCX → tekst)",
    ],
    # Lustro polityki `candidate-summary-no-finance-v3`
    # (`candidate_activity_summary_service.CONTENT_POLICY_VERSION`): stawki,
    # kwoty i inne dane finansowe NIE trafiają do modelu — profil kandydata
    # mówi to wprost, więc ten opis nie może obiecywać czegoś odwrotnego (B13).
    AIFeatureKey.candidate_summary: [
        "Historia rekrutacji (etapy, powody odrzuceń — bez stawek)",
        "Feedback po interview i screeningi",
        "Notatki rekruterów (ostatnie 30)",
        "Umowy: klient, okres, tryb pracy, status (bez stawek i kwot)",
        "Profil: preferencje, dostępność, skills (bez oczekiwań finansowych)",
        "Podsumowania rozmów telefonicznych",
    ],
    AIFeatureKey.champion_draft: [
        "Treść CV kandydata-Championa",
        "Historia rekrutacji (top-K podobnych zamkniętych ról)",
    ],
    AIFeatureKey.order_parser: [
        "Tekst wyekstrahowany z PDF/DOCX zamówienia od klienta",
    ],
    AIFeatureKey.cv_backfill: [
        "Zapisany tekst CV kandydatów (bieg masowy, tylko puste pola)",
    ],
    AIFeatureKey.experience_dates_on_demand: [
        "Zapisany tekst CV kandydatów pokazanych na kartotece firmy w ATLAS-ie",
        "(tylko ci bez dat w historii zatrudnienia; zapis wyłącznie dat i ról)",
    ],
    AIFeatureKey.notes_extraction: [
        "Treść wewnętrznych notatek o kandydacie (ekstrakcja strukturalna;",
        "wynik zostaje w NEXUS — nie trafia do klienta ani do wektorów)",
    ],
    AIFeatureKey.champion_profile_parse: [
        "Treść dokumentu Profilu Championa (wymagania, stawka, kontekst projektu)",
    ],
    AIFeatureKey.cv_generator: [
        "Treść CV kandydata (PDF/DOCX → tekst)",
        "Profil Championa i wymagania rekrutacji",
        "Notatki ze screeningu (tryb upload)",
    ],
    AIFeatureKey.mindy_chat: [
        "Agregaty KPI rozmówcy (placementy, leady, oferty)",
        "Imię i e-mail rozmówcy",
        "Treść pytań zadanych MINDY",
    ],
    AIFeatureKey.cv_rule_lint: [
        "Treść instrukcji Delivery Leada dla generatora CV (bez danych kandydatów)",
    ],
    AIFeatureKey.cv_requirement_map: [
        "Treść wygenerowanego CV B2B (render_payload — bez notatek i stawek)",
        "Wymagania must/nice-have rekrutacji",
    ],
    AIFeatureKey.cv_interactive_chat: [
        "Treść wygenerowanego CV B2B (render_payload — bez notatek i stawek)",
        "Mapa wymagań z dowodami",
        "Pytania hiring managera z publicznego linku",
    ],
    AIFeatureKey.uop_check: [
        "Opis projektu i zakres usług wpisany do umowy B2B",
        "(bez danych kandydata, bez stawek — sam tekst zakresu)",
    ],
    AIFeatureKey.cv_name_backfill: [
        "Zapisany tekst CV kandydatów bez imienia (bieg nocny, tylko puste pola)",
    ],
    AIFeatureKey.cv_factual_verification: [
        "Pełny tekst źródłowego CV (ponumerowane linie)",
        "Notatki ze screeningu",
        "Imię i nazwisko kandydata",
        "Twierdzenia z wygenerowanego / edytowanego CV",
    ],
    AIFeatureKey.jarvis: [
        "Treść pytań i poleceń użytkownika",
        "Wyniki narzędzi — dokładnie to, co użytkownik widzi w NEXUSIE przez API "
        "(kandydaci, rekrutacje, klienci, kontrakty; kwoty tylko przy uprawnieniu)",
        "Ekran, na którym użytkownik jest (ścieżka i ID rekordu)",
    ],
    AIFeatureKey.job_public_description: [
        "Tytuł rekrutacji, opis projektu i stack z Profilu Championa",
        "(bez nazwy klienta, stawek i danych kandydatów)",
    ],
    AIFeatureKey.screening_reassign_suggest: [
        "Pytania screeningowe nowej rekrutacji (Profil Championa)",
        "Odpowiedzi kandydata ze screeningu w poprzedniej rekrutacji",
        "Ostatnie notatki rekruterów o kandydacie",
    ],
    AIFeatureKey.dz_review: [
        "Tekst CV przygotowanego dla klienta (z zaznaczonymi pogrubieniami)",
        "Tekst oryginalnego CV kandydata",
        "Must-have, nice-to-have i opis rekrutacji",
        "(bez stawek, kontaktów do klienta i notatek rekruterów)",
    ],
    AIFeatureKey.prep_review: [
        "Transkrypt prepu z Teams (wypowiedzi z podpisem: kandydat / zespół)",
        "Must-have rekrutacji i pytania, które zadaje ten klient",
        "(bez stawek, nazwy klienta i notatek rekruterów)",
    ],
}


class AIFeatureConfig(Base, TimestampMixin):
    """Per-feature toggle + monthly limit configuration.

    Single global config (no per-tenant). One row per `AIFeatureKey`.
    """

    __tablename__ = "ai_features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    feature: Mapped[AIFeatureKey] = mapped_column(
        Enum(AIFeatureKey, name="aifeaturekey"),
        nullable=False,
        unique=True,
        index=True,
    )

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    monthly_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Monthly call cap. 0 = unlimited.",
    )

    # Stempel ostatniego ostrzeżenia o zużyciu (migracja 0241). Trwały, bo prod
    # restartuje się przy każdym pushu — zbiór w pamięci alertowałby od nowa po
    # każdym deployu, a przy `--workers > 1` osobno w każdym procesie. Ten sam
    # błąd naprawiono już w `slack_sla_alerts`.
    #
    # `spend_alert_level` to KROTNOŚĆ progu, przy której ostatnio ostrzegaliśmy
    # (3, potem 6, 12...). Bez tego jednorazowy alert milczałby, gdy zużycie
    # rośnie dalej — a to właśnie wtedy jest najciekawsze.
    spend_alert_period: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    spend_alert_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class AIMasterToggle(Base, TimestampMixin):
    """Global kill-switch for all AI features.

    A single-row table (id=1). When `enabled=False`, every quota-checked
    endpoint returns 503 regardless of per-feature `AIFeatureConfig.enabled`.

    Stored as a row (not env var) so admin can flip without redeploy.
    """

    __tablename__ = "ai_master_toggle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class AIUsageLog(Base):
    """Read-only legacy monthly counts; no new writes after migration 0280.

    New admissions and responses belong to AIOperation / AIProviderCall.
    Legacy counts still contribute to quotas; legacy tokens are unreliable
    because nullable actors allowed duplicate rows and token-update fanout.

    `period_start` = first day of the calendar month (UTC). The 1st-of-month
    reset is enforced by query: SELECT … WHERE period_start = date_trunc('month', NOW()).
    """

    __tablename__ = "ai_usage_log"
    __table_args__ = (
        UniqueConstraint(
            "feature", "user_id", "period_start", name="uq_ai_usage_feature_user_period"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)

    feature: Mapped[AIFeatureKey] = mapped_column(
        Enum(AIFeatureKey, name="aifeaturekey"),
        nullable=False,
        index=True,
    )

    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="NULL = system-initiated call (background task).",
    )

    period_start: Mapped[datetime] = mapped_column(
        Date,
        nullable=False,
        index=True,
        doc="First day of the calendar month (UTC). Used as quota window key.",
    )

    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Tokeny sumowane w tym samym oknie co `count` (0270). Osobno od licznika
    # wywołań, bo jedna generacja CV B2B (16 384 tokeny outputu, łańcuch dwóch
    # modeli) waży tyle co kilkadziesiąt linii MINDY — alarm o skoku liczący
    # WYWOŁANIA nie widzi tej różnicy i milczy dokładnie wtedy, gdy rachunek
    # rośnie najszybciej.
    #
    # Zapisywane DRUGIM UPDATE-em, nie w upsercie naliczającym: kwota jest
    # naliczana PRZED wywołaniem dostawcy (charge-before-spend, patrz
    # `ai_quota.ai_feature`), a `message.usage` znamy dopiero PO. Wypełnia je
    # `ai_feature` w bloku `finally`, z akumulatora, który karmi `call_claude`.
    #
    # BigInteger, nie Integer: 105,8 mln tokenów wejściowych w jednym biegu
    # masowym (Fala 3, 08.2026) to jedna dziesiąta zakresu `int4` — przy
    # sumowaniu miesięcznym przepełnienie jest kwestią czasu, a objawiłoby się
    # wyjątkiem w ścieżce, która ma być niewidoczna dla użytkownika.
    input_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    output_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    last_call_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
