"""Log wygenerowanych umów B2B — numeracja + audyt.

Standalone render (bez rekordu `Contract`) zapisuje tu wiersz przy pobraniu
finalnego DOCX. `contract_number` jest zawsze kanoniczny („1434/2026”), a `seq`
to jego liczbowy prefiks — stąd UNIQUE(year, seq) gwarantuje na poziomie DB,
że numer umowy nie powtórzy się w obrębie roku (race-safe, w odróżnieniu od
samego SELECT-checku w API).

Legacy (wiersze sprzed PR #469, id 5-7 na prod): `seq` był licznikiem wierszy
niezależnym od numeru — dlatego constraint NIE jest na (year, contract_number)
(prod ma historyczny duplikat „1434/2026”, którego nie ruszamy bez decyzji).
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class B2BGeneratedContract(Base, TimestampMixin):
    __tablename__ = "b2b_generated_contracts"
    __table_args__ = (
        # Częściowy od 0358: wiersze z Excela z numerem spoza formatu („264A”,
        # „bez numeru”, „zlecenie”) nie mają `seq`, a numer kanoniczny nadal
        # nie może się powtórzyć w obrębie roku.
        Index(
            "uq_b2b_generated_contracts_year_seq",
            "year",
            "seq",
            unique=True,
            postgresql_where=text("seq IS NOT NULL"),
            sqlite_where=text("seq IS NOT NULL"),
        ),
        # Wiersz z Excela ma stały klucz (numer albo skrót wiersza) — po nim
        # ponowny import aktualizuje zamiast dopisywać duplikat.
        Index(
            "ux_b2b_generated_contracts_excel_source_key",
            "source_key",
            unique=True,
            postgresql_where=text("source = 'excel'"),
            sqlite_where=text("source = 'excel'"),
        ),
        CheckConstraint(
            "source IN ('generator', 'excel')",
            name="ck_b2b_generated_contracts_source",
        ),
        CheckConstraint(
            "contract_kind IS NULL OR "
            "contract_kind IN ('b2b', 'mandate', 'work', 'employment')",
            name="ck_b2b_generated_contracts_contract_kind",
        ),
        CheckConstraint(
            "start_date_mode IS NULL OR "
            "start_date_mode IN ('exact', 'not_later', 'not_earlier')",
            name="ck_b2b_generated_contracts_start_date_mode",
        ),
        CheckConstraint(
            "signature_status IN ('unsigned', 'signed_both')",
            name="ck_b2b_generated_contracts_signature_status",
        ),
        CheckConstraint(
            "signature_source IS NULL OR "
            "signature_source IN ('manual_confirmation', 'validated_upload')",
            name="ck_b2b_generated_contracts_signature_source",
        ),
        CheckConstraint(
            "contract_status IN "
            "('active', 'in_progress', 'cancelled', 'suspended', 'closed')",
            name="ck_b2b_generated_contracts_contract_status",
        ),
        # Katalog powodów opisuje KONIEC PROJEKTU (migracja 0226). Trzy wartości
        # z 0203 (`resignation_before_signing`, `termination`,
        # `mutual_agreement`) opisywały ROZSTANIE Z PARTNEREM i zniknęły
        # z pickera, ale zostają tutaj: produkcja ma wiersze `closed`, które je
        # niosą. CHECK jest domeną dopuszczalnych wartości, nie listą
        # podpowiedzi w UI — zawężenie go wywaliłoby walidację constraintu, a
        # nawet gdyby przeszło, historyczny powód zamieniłby się w puste
        # miejsce.
        CheckConstraint(
            "closure_reason IS NULL OR closure_reason IN ("
            "'no_client_budget', 'contractor_found_other_project', "
            "'contractor_health_reasons', 'contractor_underperformance', "
            "'project_completed', 'internalization', 'other', "
            "'resignation_before_signing', 'termination', 'mutual_agreement')",
            name="ck_b2b_generated_contracts_closure_reason",
        ),
        # Domknięcie stanu: „Zakończona" bez powodu albo bez daty zakończenia
        # jest bezużyteczna (nie wiadomo, co i kiedy się skończyło), a „Aktywna"
        # z wypełnionym powodem to sprzeczność. Wymuszamy to w bazie, nie tylko
        # w API, bo dane wchodzą tu również safety-netem entrypointu.
        #
        # `in_progress` jest tu traktowany jak `active` (migracja 0224): umowa
        # w drodze do podpisu nie ma i nie może mieć pól zamknięcia. Gdyby ta
        # gałąź została przypięta wyłącznie do `active`, wiersz `in_progress`
        # łamałby OBIE gałęzie → IntegrityError na każdym generowaniu umowy.
        #
        # `suspended` jest traktowany jak `closed` (migracja 0226): umowa bez
        # projektu MUSI powiedzieć, co i kiedy się skończyło — inaczej zakładka
        # „Umowy bez projektu" pokazywałaby wiersze bez daty i powodu, czyli
        # dokładnie to, czego ten status miał uniknąć.
        #
        # `cancelled` (0328) idzie do gałęzi „pola zamknięcia puste", razem
        # z `active`/`in_progress`: umowa, która NIE DOSZŁA DO SKUTKU, nie ma
        # czego ani kiedy kończyć. Wymuszanie powodu i daty zamieniłoby
        # jednoklikowe anulowanie (i powrót na „W trakcie") w formularz
        # o zakończeniu czegoś, co nigdy się nie zaczęło.
        CheckConstraint(
            "("
            "contract_status IN ('active', 'in_progress', 'cancelled')"
            " AND closure_reason IS NULL"
            " AND closure_date IS NULL"
            " AND closure_reason_other IS NULL"
            ") OR ("
            "contract_status IN ('closed', 'suspended')"
            " AND closure_reason IS NOT NULL"
            " AND closure_date IS NOT NULL"
            " AND ((closure_reason = 'other') = (closure_reason_other IS NOT NULL))"
            ")",
            name="ck_b2b_generated_contracts_closure_coherence",
        ),
        CheckConstraint(
            "partner_entity_type IS NULL "
            "OR partner_entity_type IN ('sole_trader', 'company')",
            name="ck_b2b_generated_contracts_partner_entity_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Oba NULL-owalne od 0358: wiersz z Excela bez daty podpisania nie ma
    # roku, a numer spoza formatu „liczba/rok” nie ma `seq` (surowy numer
    # żyje w `raw_contract_number`).
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    seq: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    contract_number: Mapped[str] = mapped_column(String(64), nullable=False)
    # UWAGA: to IMIĘ I NAZWISKO osoby fizycznej (pole „Imię i nazwisko"
    # w generatorze), NIE nazwa firmy. Nazwa firmy z GUS/CEIDG siedzi
    # w `partner_legal_name`. Cała kolumna „Partner" na liście rozbija się o tę
    # pomyłkę: kto wyświetli tutaj `partner_name`, pokaże nazwisko zamiast firmy.
    partner_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Nazwa firmy odczytana z rejestru (GUS/CEIDG) w momencie generowania.
    # Dla JDG to pełna nazwa działalności („Management Services - Jan Kowalski"),
    # która z mocy prawa zawiera imię i nazwisko właściciela. NULL = wiersz
    # sprzed migracji 0224, którego payload nie miał tego klucza.
    partner_legal_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    # NIP kanonicznie do samych cyfr — surowe formatowanie („123-456-32-18")
    # zostaje w `render_payload`, żeby dokument renderował się bez zmian.
    partner_nip: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Binarny sygnał z rejestru: CEIDG → `sole_trader`, KRS → `company`.
    # SNAPSHOT z momentu generowania, nie przeliczany później — forma prawna
    # Partnera po podpisaniu umowy przestaje być bieżącą informacją.
    # NULL znaczy dokładnie „brak sygnału z rejestru" (wiersz historyczny),
    # a nie „nie wiemy" — dla takich wierszy typ wyznacza heurystyka po nazwie
    # w warstwie serializacji.
    partner_entity_type: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )
    client_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    language: Mapped[str] = mapped_column(String(2), default="pl", nullable=False)
    signing_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Data rozpoczęcia świadczenia Usług — NIE data podpisania (`signing_date`).
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Business state of the generated legal document. This is deliberately a
    # varchar + CHECK (not a PostgreSQL enum) so the one-way workflow remains
    # additively deployable and easy to extend without enum DDL.
    signature_status: Mapped[str] = mapped_column(
        String(32), default="unsigned", server_default="unsigned", nullable=False
    )
    # ``manual_confirmation`` is an audited declaration by a trusted user. It
    # must never be confused with DocumentSignature/QES evidence.
    signature_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Status handlowy umowy — NIEZALEŻNY od `signature_status`. Umowa podpisana
    # też bywa zamykana (wypowiedzenie, porozumienie), a niepodpisana bywa
    # zamknięta rezygnacją przed podpisem. Zamknięcie NIE usuwa wiersza —
    # kończy jego bieg i zostaje w rejestrze.
    #
    # Pięć wartości: `in_progress` → `active` → (`suspended` ⇄ `active`) →
    # `closed`, plus `cancelled` obok toru głównego. `in_progress` ustawia
    # generowanie, `active` WYŁĄCZNIE potwierdzenie podpisu obustronnego (0224),
    # a `suspended` (0226) opisuje umowę, która nadal obowiązuje, choć
    # kontraktor nie ma przypisanego projektu — zasila zakładkę „Umowy bez
    # projektu".
    #
    # `cancelled` (0328) to umowa, która NIE DOSZŁA DO SKUTKU — Partner wycofał
    # się przed podpisem. To NIE to samo co `closed`: tam skończył się projekt,
    # tu umowa nigdy nie zaczęła obowiązywać. Wiersz zostaje w rejestrze, bo
    # numer jest już zużyty i nie wraca do puli (UNIQUE(year, seq)).
    #
    # Zawiesić można WYŁĄCZNIE umowę `active`: „nadal obowiązuje" nie opisuje
    # dokumentu przed podpisem. Bez tej reguły `in_progress → suspended`
    # tworzyłby ślepy zaułek, bo powrót na `active` wymaga powiązanego
    # kontraktu (409), który powstaje dopiero przy potwierdzeniu podpisu.
    #
    # Anulować można każdą umowę, która nie jest podpisana obustronnie; wyjście
    # z `cancelled` prowadzi WYŁĄCZNIE na `in_progress` (jedyny ręczny wybór
    # tego statusu) — na `active` znów wpuszcza tylko potwierdzenie podpisu.
    #
    # Default kolumny ZOSTAJE `active` i to nie jest przeoczenie: opisuje wiersz
    # wstawiony bez decyzji o statusie (seed, safety-net entrypointu, surowy
    # INSERT). Zmiana defaultu na `in_progress` przepisałaby historię każdego
    # takiego wiersza.
    contract_status: Mapped[str] = mapped_column(
        String(16), default="active", server_default="active", nullable=False
    )
    # Wymagany przy `closed` (patrz ck_..._closure_coherence).
    closure_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Własny powód wpisany przez użytkownika — wymagany dokładnie wtedy, gdy
    # `closure_reason == 'other'`, i zabroniony w każdym innym przypadku.
    closure_reason_other: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Data faktycznego zakończenia umowy (nie data kliknięcia w UI) — obowiązkowa
    # dla statusu `closed`.
    closure_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # RESTRICT is intentional: once a signed generated document points at a
    # Contract, hard-deleting that Contract would destroy its audit linkage.
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signed_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Surowy payload `/render` (B2BRenderRequest jako JSON) — pozwala odtworzyć i
    # pobrać DOCX ponownie z zakładki „Wygenerowane umowy". NULL = wiersz sprzed
    # tej funkcji (re-download niedostępny). JSON+wariant JSONB by działał też na
    # SQLite w testach (constraint-test tworzy tabelę na sqlite).
    render_payload: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    # Wersja wzoru umowy, z której wydano dokument (0357). Od niej zależą
    # numery paragrafów cytowane w aneksach i okres wypowiedzenia
    # (services/b2b_documents/contract_versions.py). NULL = nieznana
    # (wiersz z importu Excela) — formularz dokumentu pyta wtedy o paragraf.
    template_version: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    # ── Rejestr z Excela działu (0358) ──────────────────────────────────────
    # Excel „UMOWY I ZAMÓWIENIA” jest prowadzony RÓWNOLEGLE z NEXUSEM, więc
    # import jest powtarzalny. `generator` = wiersz wydany w NEXUSIE (import go
    # nigdy nie zmienia), `excel` = wiersz z pliku, tylko do odczytu poza
    # statusem handlowym (services/b2b_register_import).
    source: Mapped[str] = mapped_column(
        String(16), default="generator", server_default="generator", nullable=False
    )
    # Klucz wiersza w Excelu: „n:<numer>” albo „h:<skrót>” dla „bez numeru” /
    # „zlecenie”. Unikalny wśród wierszy `excel` (indeks częściowy).
    source_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Numer dokładnie tak, jak stoi w kolumnie B („264A”, „bez numeru”).
    raw_contract_number: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    # b2b | mandate (zlecenie) | work (dzieło) | employment (UoP).
    contract_kind: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # exact | not_later („nie później niż”) | not_earlier („nie wcześniej niż”).
    start_date_mode: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    position: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    recruiter_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # UWAGI, ZMIANY W UMOWIE, rozliczenia, mail powitalny, kolory komórek,
    # flagi (`flags`) — wszystko, co nie ma własnej kolumny.
    legacy_data: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    # Umowa podpisana przed założeniem działalności — czeka na aneks
    # „uzupełnienie danych firmy” (arkusz „Bez działalności”).
    needs_business_data_annex: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    business_data_annex_done_at: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )
    import_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("b2b_register_import_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Wiersza nie było w ostatnio wgranym pliku — nie kasujemy, oznaczamy.
    excel_missing_since: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<B2BGeneratedContract id={self.id} number={self.contract_number!r}>"
