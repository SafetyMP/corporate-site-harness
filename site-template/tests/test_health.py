from siteapp import health


def test_health() -> None:
    assert health() == "ok"
