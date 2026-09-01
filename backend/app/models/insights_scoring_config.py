"""Konfigurowalna punktacja Insights — jedna powierzchnia dla Ligi i seniority.

Klucz-wartość z wartościami CAŁKOWITYMI. Powód, dla którego to jest tabela,
a nie stałe w kodzie: formuła Ligi Mistrzów rozdziela realne pieniądze
(5000/3000/2000 PLN kwartalnie), a progi „Ścieżki rozwoju" przyznają awanse.
Strojenie jednego i drugiego nie może wymagać deployu — i musi zostawiać ślad,
kto i kiedy je zmienił.

Dlaczego progi seniority mieszkają TUTAJ, a nie we własnej tabeli: obie funkcje
odpowiadają na to samo pytanie („ile placementów się liczy i ile są warte"),
a dwie osobne powierzchnie konfiguracji oznaczałyby dwa miejsca do sprawdzenia,
gdy liczby na dwóch ekranach przestaną się zgadzać.

Wartości są `int`, nie `numeric`: punkty i progi są liczbami sztuk. Ułamkowa
waga („placement = 150,5 pkt") nie ma znaczenia operacyjnego, a wpuszczenie
typu zmiennoprzecinkowego do formuły, której wynik jest ZAMRAŻANY niezmiennie
razem z nagrodą, zamieniłoby remis w kwestię reprezentacji binarnej.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InsightsScoringConfig(Base):
    """Jeden nadpisany klucz konfiguracji punktacji.

    Brak wiersza NIE jest błędem — znaczy „obowiązuje wartość domyślna
    z kodu" (`app.services.insights_scoring_config.SCORING_DEFAULTS`).
    Tabela trzyma wyłącznie ODSTĘPSTWA od domyślnych, więc świeża instalacja
    i instalacja po „przywróć domyślne" wyglądają tak samo.
    """

    __tablename__ = "insights_scoring_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    # `SET NULL`, nie `CASCADE`: usunięcie konta admina nie może cofnąć
    # obowiązującej wagi punktowej do domyślnej. Wartość zostaje, ginie
    # wyłącznie atrybucja.
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
