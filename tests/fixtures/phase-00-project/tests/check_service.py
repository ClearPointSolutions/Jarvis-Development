from acceptance_app import version


def check_version() -> None:
    assert version() == "0.1.0"
