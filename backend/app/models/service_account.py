"""Konta serwisowe i klucze API — uwierzytelnianie automatyzacji bez człowieka.

Dlaczego to w ogóle powstało: jedyną drogą do API był dotąd JWT użytkownika
(8 h życia, wybijany zmianą hasła i bumpem ``authorization_version``). Skrypt
operacyjny, cron albo CI musiał więc albo podszywać się pod rekrutera tokenem
wyklikanym w przeglądarce, albo wymuszać globalne wydłużenie
``ACCESS_TOKEN_EXPIRE_MINUTES`` — czyli osłabić sesje WSZYSTKIM rekruterom w
systemie trzymającym dane kandydatów pod RODO. To zła wymiana, więc automatyzacja
dostaje własną klasę poświadczeń.

Dwie tabele, nie jedna — ``ServiceAccount`` (tożsamość) osobno od
``ServiceAccountKey`` (poświadczenie). Powód jest wprost operacyjny: **rotacja
bez przestoju**. Przy jednej tabeli wymiana klucza to skasowanie wiersza i
stworzenie nowego, czyli albo okno bez działającej automatyzacji, albo drugi byt
o innej tożsamości — a wtedy audyt pokazuje dwa różne podmioty tam, gdzie
operacyjnie cały czas działa ten sam „traffit-ops". Przy dwóch: dokładasz drugi
klucz do TEGO SAMEGO konta, wdrażasz, rewokujesz stary. Tożsamość w logach
i historii się nie rwie.

Sekret jest widoczny **raz** — w odpowiedzi na utworzenie klucza. W bazie ląduje
wyłącznie SHA-256, dokładnie jak w ``cv_generated_share_tokens`` (migracja 0217).
Świadomie NIE bcrypt, którego używa ``oauth_clients``: tam hash liczy się raz na
godzinę przy wymianie poświadczeń na token, a tu przy KAŻDYM requeście. bcrypt
przy domyślnym koszcie to ~100 ms CPU, więc byłby jednocześnie podatkiem na
każde wywołanie i darmowym wektorem DoS (anonim pali CPU serwera zmyślonymi
kluczami). Rozciąganie hasha chroni sekrety o niskiej entropii; tutaj sekret to
256 bitów z ``secrets.token_urlsafe`` — nie ma czego rozciągać.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.user import User


class ServiceScope(str, enum.Enum):
    """Słownik uprawnień kluczy API — celowo WĄSKI i celowo osobny.

    Zasada: jeden scope = jedna powierzchnia operacyjna, nazwa ``<zasób>:<akcja>``.
    Klucz do odpalania syncu Traffita nie ma jak sięgnąć po dane kandydata, bo
    takiego scope'u po prostu nie ma w tym słowniku — to nie jest kwestia
    ostrożnej konfiguracji, tylko braku istniejącego uprawnienia.

    Dlaczego NIE ``OAuthScope`` (``app/models/oauth_client.py``): tamten słownik
    jest kontraktem zgodności dla integracji migrujących z Traffita (jego
    docstring mówi to wprost) i opisuje dostęp do danych domenowych —
    ``candidate:read``, ``job:write``. Dolepienie do niego scope'ów operacyjnych
    zlałoby dwa różne zobowiązania w jedną listę: „co obiecaliśmy zewnętrznym
    systemom" i „co wolno naszemu cronowi". Konsolidacja obu słowników jest
    możliwa, ale to decyzja produktowa, nie refaktor przy okazji.

    Dodanie scope'u: wpis w enumie + etykieta w ``SCOPE_LABELS`` + użycie
    w guardzie endpointu. Bez migracji — kolumna trzyma stringi, nie enum DB.
    """

    traffit_sync = "traffit:sync"
    traffit_read = "traffit:read"
    ops_snapshot = "ops:snapshot"
    # Eksport kontraktorów dla COMPASSA. Nazwa CELOWO nie brzmi
    # ``candidate:read`` ani ``client:read`` — te dwie są przez
    # `test_no_candidate_data_scope_exists` jawnie zakazane w tym słowniku,
    # bo klucz API nie ma sięgać po dane domenowe. Ten scope otwiera JEDNĄ
    # wąską trasę: tożsamość i zaangażowanie osób pracujących u klientów,
    # bez stawek i bez marż.
    contractors_read = "contractors:read"


SCOPE_LABELS: dict[ServiceScope, str] = {
    ServiceScope.traffit_sync: "Uruchamianie synchronizacji Traffit",
    ServiceScope.traffit_read: "Odczyt statusu synchronizacji Traffit",
    ServiceScope.ops_snapshot: "Odczyt migawki operacyjnej (/api/admin/snapshot)",
    ServiceScope.contractors_read: "Eksport kontraktorów dla COMPASSA (bez kwot)",
}


class ServiceAccount(Base, TimestampMixin):
    """Nieosobowa tożsamość automatyzacji (cron, CI, skrypt operacyjny).

    Świadomie **nie jest** wierszem w ``users``. Konto serwisowe udające
    użytkownika wyciekłoby do list userów, dashboardów, KPI, leaderboardów,
    powiadomień i eksportów RODO — wszędzie tam, gdzie kod pyta „którzy ludzie
    są w systemie". Osobna tabela oznacza też, że ``ServiceAccount`` nie ma
    ``role``, więc żaden istniejący guard rolowy nie przepuści go przypadkiem.

    Uprawnienia są **własne i wyłącznie własne** — konto nie dziedziczy roli
    tego, kto je założył. Dziedziczenie roli ma dwie wady, obie ciche:
    klucz zyskuje uprawnienia, gdy właściciel awansuje, i traci je (albo umiera),
    gdy właściciel odchodzi z firmy. Automatyzacja przestaje wtedy działać
    z powodu niezwiązanego z automatyzacją. Do tego rola ``admin`` to „wszystko",
    więc dziedziczenie roli wyklucza najmniejsze uprawnienia z definicji.
    """

    __tablename__ = "service_accounts"
    __table_args__ = (
        # Lustro ``ck_users_roles_array``. Gdyby ``scopes`` przestało być tablicą
        # (ręczny UPDATE, zły import), sprawdzenie uprawnień w Pythonie zrobiłoby
        # z operatora ``in`` test podciągu — ``"traffit:sync" in "traffit:sync-x"``
        # jest prawdą. Baza odrzuca taki wiersz zamiast pozwolić mu cicho
        # rozszerzyć uprawnienia.
        CheckConstraint(
            "jsonb_typeof(scopes) = 'array'",
            name="ck_service_accounts_scopes_array",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Stabilny, czytelny identyfikator w logach i audycie ("traffit-ops").
    # Nazwa wyświetlana bywa zmieniana, slug nie — inaczej historia w Grafanie
    # rozpada się na dwa byty przy zwykłym przemianowaniu.
    slug: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    scopes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Kill-switch całego konta: gasi wszystkie jego klucze jednym PATCH-em,
    # bez wyliczania ich po kolei. Rewokacja pojedynczego klucza żyje na kluczu.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ``selectin`` NIE obciąża ścieżki gorącej. Sprawdzone pomiarem: uwierzytelnienie
    # klucza ładuje ``ServiceAccountKey`` i dociąga jego konto przez ``lazy="joined"``,
    # a ten loader kolekcji się na tak wczytane konto NIE propaguje — decyzja
    # autoryzacyjna kosztuje jedno zapytanie niezależnie od tej opcji. Zostaje więc
    # dla bezpieczeństwa: bez niego każdy przyszły odczyt ``account.keys`` bez jawnego
    # ``selectinload`` kończy się ``MissingGreenlet`` (czyli 500), bo leniwe ładowanie
    # w asyncu nie działa.
    keys: Mapped[list["ServiceAccountKey"]] = relationship(
        "ServiceAccountKey",
        back_populates="service_account",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    creator: Mapped[Optional["User"]] = relationship(
        "User", lazy="select", foreign_keys=[created_by]
    )

    def granted_scopes(self) -> frozenset[str]:
        """Uprawnienia konta, fail-closed przy uszkodzonym wierszu.

        CHECK w bazie pilnuje kształtu, ale ta metoda jest ostatnią bramką przed
        decyzją autoryzacyjną i nie zakłada, że wiersz przyszedł z bazy z tym
        CHECK-iem (fixture w teście, stary snapshot, ręczna naprawa produkcji).
        Cokolwiek nie jest listą stringów → pusty zbiór, czyli brak uprawnień.
        """
        raw = self.scopes
        if not isinstance(raw, list):
            return frozenset()
        return frozenset(item for item in raw if isinstance(item, str))

    def __repr__(self) -> str:  # pragma: no cover - diagnostyka
        return f"<ServiceAccount id={self.id} slug={self.slug} active={self.is_active}>"


class ServiceAccountKey(Base):
    """Pojedyncze poświadczenie konta serwisowego (N kluczy na konto).

    Klucz na drucie ma kształt ``nxs_v2_<key_id_hex>_<sekret>`` i jest rozcinany
    na dwie części o różnym statusie:

    * ``key_id`` (jawne, PK jako ``v2$<hex>``) — po nim idzie SELECT. Ponieważ
      nie jest sekretem, wyszukiwanie po indeksie nie ma jak wyciec kanałem
      czasowym i wolno go logować, więc audyt „którym kluczem" jest w ogóle
      wykonalny.
    * sekret — nigdy nie zapisywany; w bazie tylko ``secret_sha256``,
      porównywany ``hmac.compare_digest``.

    Prefiks ``v2$`` w ``key_id`` to konwencja z ``cv_generated_share_tokens``:
    wersja schematu jest wpisana w samo poświadczenie, więc ewentualna zmiana
    funkcji skrótu daje się wdrożyć bez zgadywania, jak zahaszowano dany wiersz.
    """

    __tablename__ = "service_account_keys"

    # PK = revoke-key ``v2$<hex>``. Nie jest sekretem: pojawia się w listingu
    # kluczy, w logach i w komunikatach błędów.
    key_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    service_account_id: Mapped[int] = mapped_column(
        ForeignKey("service_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    secret_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    # Po co ten konkretny klucz istnieje ("GitHub Actions deploy", "cron ops").
    # Bez tego przy rotacji nie wiadomo, który z dwóch żywych kluczy wolno ubić.
    label: Mapped[str] = mapped_column(String(120), nullable=False)

    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # NOT NULL świadomie — poświadczenie bez daty ważności nie jest nigdy
    # przeglądane ponownie i przeżywa odejścia ludzi, migracje i zmiany zakresu.
    # Termin jest wyliczany przy tworzeniu (domyślnie 90 dni, sufit z configu),
    # więc rotacja jest wymuszona kalendarzem, a nie dobrą wolą.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoke_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # „Czy ta integracja jeszcze żyje" — ten sam sygnał co
    # ``oauth_clients.last_used_at``. Stempel jest DŁAWIONY (patrz
    # ``service_account_auth.stamp_key_usage``): zapis przy każdym requeście
    # zamieniałby każdy odczyt w zapis. Świadomie NIE ma tu licznika wywołań —
    # zdławiony licznik kłamie, a prawdziwy zliczają logi i metryki.
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    service_account: Mapped["ServiceAccount"] = relationship(
        "ServiceAccount", back_populates="keys", lazy="joined"
    )

    def __repr__(self) -> str:  # pragma: no cover - diagnostyka
        return (
            f"<ServiceAccountKey key_id={self.key_id} "
            f"account={self.service_account_id} revoked={self.revoked_at is not None}>"
        )


__all__ = [
    "SCOPE_LABELS",
    "ServiceAccount",
    "ServiceAccountKey",
    "ServiceScope",
]
