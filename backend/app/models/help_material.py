from typing import Optional
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class HelpMaterial(Base):
    """Materiały firmowe w zakładce Pomoc — biblioteka LINKÓW do SharePointa.

    NEXUS nie hostuje tych dokumentów. Pliki zostają w SharePoincie, gdzie są
    natywnie edytowalne w Word Online i wersjonowane przez M365; tutaj trzymamy
    wyłącznie metadane i adres. Dzięki temu „edycja materiału" nigdy nie oznacza
    rozjazdu dwóch kopii tego samego dokumentu.

    ``is_editable_template`` wyróżnia nasze własne wzory (szablon umowy, profil
    Championa, notatka po screeningu), które zespół poprawia na bieżąco — FE
    dokłada im przycisk „Edytuj". Formularze onboardingowe klientów to cudze
    dokumenty, więc zostają tylko do otwarcia.

    ``url`` jest renderowany jako ``<a href>``, więc schemat waliduje warstwa
    API — dozwolone wyłącznie http/https (ochrona przed stored-XSS przez
    ``javascript:``/``data:``).

    Wiersz jest ALBO linkiem (``url``), ALBO szablonem treści
    (``template_subject`` + ``template_body``) — szablon zaproszenia
    kalendarzowego nie ma adresu w SharePoincie, bo nie jest plikiem.
    Dlatego ``url`` jest nullable, a spójności pilnuje CHECK
    ``ck_help_materials_link_or_template``: wiersz bez adresu i bez treści
    wyrenderowałby się w Pomocy jako martwa pozycja bez żadnej akcji.
    """

    __tablename__ = "help_materials"
    __table_args__ = (
        CheckConstraint(
            "url IS NOT NULL OR template_body IS NOT NULL",
            name="ck_help_materials_link_or_template",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    slug: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    category: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Szablon treści — wypełniony zamiast ``url`` dla pozycji, które nie są
    # plikiem (dziś: zaproszenie kalendarzowe przygotowujące kandydata do
    # rozmowy z klientem). ``template_subject`` trafia w temat wydarzenia,
    # ``template_body`` w jego opis.
    template_subject: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    template_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_editable_template: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", index=True
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )

    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    author = relationship("User", foreign_keys=[created_by])
    editor = relationship("User", foreign_keys=[updated_by])

    def __repr__(self) -> str:
        return f"<HelpMaterial id={self.id} slug={self.slug!r}>"
