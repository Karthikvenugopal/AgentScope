from app import status_response


def test_status_response_matches_public_contract() -> None:
    assert status_response() == {"status": "ok"}

