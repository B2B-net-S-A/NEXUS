"""Rozdziel zamówienia MD/kosztowe od okresowych i cofnij ich skutki uboczne.

Revision ID: 0261_separate_md_periodic
Revises: 0260_seniority_alt_thresholds

Zgłoszenie (BNP Paribas, Polkomtel, BIK, Lotte Wedel): u konsultantów
obsadzonych na zamówieniu rozliczanym w MD powstały RÓWNOLEGLE zamówienia
okresowe. Oba wiersze wiszą na tym samym kontrakcie, więc „Zakończ" z karty
okresowej wypowiadało CAŁĄ umowę, a to domykało również linię MD.

Migracja robi dwie rzeczy, obie regułą — bez ani jednego ID klienta w SQL-u.
Czterej klienci ze zgłoszenia są przypadkiem reguły, nie jej definicją; lista
w migracji zestarzałaby się przy pierwszym piątym kliencie, a nazwy klientów
nadpisuje import z Traffita.

A. **Duplikaty.** Dla kontraktu z OTWARTĄ linią grupową (MD/kosztową):
   * pusty szkic-zaślepka (`(bez numeru)`, bez pliku, bez budżetu, bez
     `filled_at`) jest USUWANY — to wiersz, który nigdy nie był zamówieniem,
     tylko zaproszeniem do wpisania numeru przez hook zatrudnienia;
   * każde inne otwarte zamówienie samodzielne jest ANULOWANE, nie kasowane.
     Może nieść numer i PDF od klienta, a `DELETE` skasowałby też plik — bywa
     jedyną kopią dokumentu w systemie.

B. **Data zakończenia umowy przepisana z zamówienia.** Szkic kontraktu zakładany
   przy obsadzie linii dziedziczył datę końca linii/zamówienia, więc umowa B2B,
   która miała być bezterminowa, dostawała datę końca, której nikt nie
   zadeklarował — a nocny `_promote_statuses` przestawiał ją na „Kończąca się",
   potem „Zakończona". Czyścimy tę datę i przywracamy `active` WYŁĄCZNIE tam,
   gdzie widać, że nikt współpracy nie zakończył: brak `terminated_at`, brak
   powodu wypowiedzenia, brak aneksu `early_termination`, a linia grupowa dalej
   obowiązuje dzisiaj. `draft` zostaje `draft` — nigdy nie przeszedł aktywacji.

Wynik obu kroków ląduje w `app_settings` jako paragon do przeglądu na
produkcji. Migracja jest jednorazowa (marker + advisory lock) i nieodwracalna
w dół: `downgrade` nie zna oryginalnych dat ani statusów.
"""

from alembic import op

from app.services.order_separation_repair import SEPARATE_MD_PERIODIC_SQL

revision = "0261_separate_md_periodic"
down_revision = "0260_seniority_alt_thresholds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(SEPARATE_MD_PERIODIC_SQL)


def downgrade() -> None:
    # Świadomie pusty: migracja kasuje puste szkice, anuluje duplikaty i czyści
    # daty, których oryginałów nie da się odtworzyć z samej bazy. Ślad każdej
    # zmiany jest w `activities` i w paragonie `app_settings`.
    pass
