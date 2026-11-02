"""Pytanie rekrutera i nazwa rekrutacji w karcie nie są dowodem (02.11.2026).

QC pisało przy Kubernetesie „kandydat mówił o tym w rozmowie, dopisz”, bo
słowo stało w pytaniu z karty, a przy nazwie usługi, bo stała w linii „Nazwa
Projektu”. Dane fikcyjne.
"""

from app.services import dz_review as dz
from app.services import must_text_evidence as mte
from app.services import note_kinds

CARD = (
    "<div><p><strong>Imię i nazwisko</strong>: Anna Przykładowa</p>"
    "<p><strong>Stawka:</strong> 110</p>"
    "<p><strong>Nazwa Projektu:</strong> Acme: Konsultant Red Hat Foundations_PKN1</p>"
    "<p><strong>Nazwa pliku CV:</strong> Acme Konsultant Red Hat Foundations</p>"
    "<p><strong>Odpowiedzi na pytania z profilu championa:</strong></p>"
    "<p>1. Jakie rozwiązania wdrażałeś na OpenShift lub Kubernetes i jak wyglądał "
    "proces przenoszenia między środowiskami?</p>"
    "<p>Pracuję przy platformie bankowej i wdrażam usługi na OpenShift przez Jenkinsa.</p>"
    "<p>2. Czy pracowałeś z Kafką?</p>"
    "<p>Tak, od 2023</p>"
    "</div>"
)


def evidence() -> str:
    return mte.evidence_note_text(note_kinds.CARD, CARD)


def test_word_only_in_a_question_is_not_evidence() -> None:
    assert dz.found_in(evidence(), dz.Requirement("Kubernetes", ("Kubernetes",))) is None


def test_answer_stays_evidence() -> None:
    assert dz.found_in(evidence(), dz.Requirement("OpenShift", ("OpenShift",)))
    assert dz.found_in(evidence(), dz.Requirement("Jenkins", ("Jenkins",)))


def test_short_yes_keeps_the_question_as_its_content() -> None:
    assert dz.found_in(evidence(), dz.Requirement("Kafka", ("Kafka", "Kafką")))
    assert mte.answer_confirms_question("Tak, od 2023")
    assert mte.answer_confirms_question("tak robił")
    assert not mte.answer_confirms_question("Nie, tylko lokalnie")
    assert not mte.answer_confirms_question(
        "Tak, ale głównie pracowałem z innymi narzędziami w poprzedniej firmie"
    )


def test_recruitment_name_is_not_evidence() -> None:
    text = evidence()
    assert "Red Hat Foundations" not in text


def test_other_notes_are_untouched() -> None:
    note = "Czy zna Kubernetes? Tak, trzy lata."
    assert mte.evidence_note_text(note_kinds.HUMAN, note) == note
