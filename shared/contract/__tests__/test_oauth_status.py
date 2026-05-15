"""Tests for the OAuthStatus enum.

Round-trip: every value in the enum must be reachable as a string and
re-parseable into the enum. Completeness: every status the contract
promises to recognise is present. The 2026-04-20 OAuth incident was caused
by the frontend silently treating unrecognised statuses as "still
pending"; this contract is the canonical truth that closes that gap.
"""
from __future__ import annotations

import pytest

from shared.contract.enums import OAuthStatus

# Every value Hermes (or our own translation layer) is permitted to emit.
# Order matters only for human readability — the test just checks set equality.
EXPECTED_VALUES: frozenset[str] = frozenset({
    'pending',
    'approved',
    'denied',
    'cancelled',
    'expired',
    'error',
})


def test_all_known_statuses_are_present() -> None:
    """Every documented OAuth status has an enum entry — and no extras."""
    actual = {member.value for member in OAuthStatus}
    assert actual == EXPECTED_VALUES, (
        f'OAuthStatus drift: missing={EXPECTED_VALUES - actual} '
        f'extra={actual - EXPECTED_VALUES}'
    )


@pytest.mark.parametrize('value', sorted(EXPECTED_VALUES))
def test_round_trip_value_to_enum(value: str) -> None:
    """Each string value round-trips: str -> enum -> str."""
    member = OAuthStatus(value)
    assert member.value == value
    # str-subclass: comparison with a plain string also holds.
    assert member == value


def test_str_subclass() -> None:
    """OAuthStatus is a str subclass so it serialises directly to JSON.

    This matters because FastAPI / pydantic both serialise str-Enum members as
    their string values without further coercion. Breaking this contract would
    silently change the wire format for every OAuth response.
    """
    assert isinstance(OAuthStatus.PENDING, str)
    assert OAuthStatus.PENDING == 'pending'


def test_unknown_value_raises() -> None:
    """Constructing the enum with an unknown value raises ValueError.

    The backend relies on this to reject statuses it doesn't recognise,
    rather than silently propagating them to the frontend (which would
    re-introduce the 2026-04-20 incident).
    """
    with pytest.raises(ValueError):
        OAuthStatus('gibberish')
