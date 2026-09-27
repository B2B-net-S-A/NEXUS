"""Runda 9 (R9-N10-1): admin/DL nie czytają cudzej, niepowiązanej poczty."""

from types import SimpleNamespace

from app.api.email_threads import _can_access_email


def _email(owner_id: int, candidate_id):
    return SimpleNamespace(user_id=owner_id, candidate_id=candidate_id)


def test_owner_always_reads_own_mail():
    user = SimpleNamespace(id=7)
    assert _can_access_email(_email(7, None), user, privileged_role=False)


def test_privileged_reads_foreign_mail_linked_to_candidate():
    user = SimpleNamespace(id=1)
    assert _can_access_email(_email(7, 42), user, privileged_role=True)


def test_privileged_does_not_read_foreign_unlinked_mail():
    user = SimpleNamespace(id=1)
    assert not _can_access_email(_email(7, None), user, privileged_role=True)


def test_non_privileged_never_reads_foreign_mail():
    user = SimpleNamespace(id=1)
    assert not _can_access_email(_email(7, 42), user, privileged_role=False)
