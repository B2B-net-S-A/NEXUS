from seed import _candidate_seed_payload


def test_candidate_seed_uses_canonical_location_and_drops_monthly_rate() -> None:
    payload = _candidate_seed_payload(
        {
            "name": "Anna",
            "lastname": "Nowak",
            "location": "Warszawa",
            "salary_expectation": 20_000,
            "salary_currency": "PLN",
        }
    )

    assert payload["city"] == "Warszawa"
    assert "country" not in payload
    assert payload["location"] == "Warszawa"
    assert "salary_expectation" not in payload
    assert "salary_currency" not in payload


def test_candidate_seed_preserves_explicit_canonical_location() -> None:
    payload = _candidate_seed_payload(
        {
            "city": "Berlin",
            "country": "DE",
            "location": "legacy value",
        }
    )

    assert payload["city"] == "Berlin"
    assert payload["country"] == "DE"
    assert payload["location"] == "Berlin, DE"
