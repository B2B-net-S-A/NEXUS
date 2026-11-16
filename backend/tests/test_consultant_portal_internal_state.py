"""Stan „Tylko zespół” (``internal``) bez bazy: czytnik działa, panel i maile zamknięte."""

import pytest

from app.services.consultant_portal.portal_settings import PortalSettings
from app.services.consultant_portal_schema import STATES


def test_internal_reads_mail_but_opens_nothing() -> None:
    state = PortalSettings(state="internal", activated_contract_ids=frozenset({7}))
    assert state.reads_mailbox is True
    assert state.any_sender is True
    assert state.is_on is False
    # Aktywacja nie otwiera panelu ani maila: ``open_for`` pilnuje każdej wysyłki.
    assert state.open_for(7) is False


@pytest.mark.parametrize(
    ("value", "reads", "any_sender", "is_on"),
    [
        ("off", False, False, False),
        ("pilot", True, False, True),
        ("all", True, True, True),
    ],
)
def test_other_states_keep_their_meaning(value, reads, any_sender, is_on) -> None:
    state = PortalSettings(state=value)
    assert (state.reads_mailbox, state.any_sender, state.is_on) == (
        reads,
        any_sender,
        is_on,
    )


def test_internal_is_a_known_state() -> None:
    assert "internal" in STATES
