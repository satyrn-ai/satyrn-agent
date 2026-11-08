import pytest

from plan_comparison.cli import main


def test_pilot_cli_requires_both_approvals_before_loading_factory(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        main(
            [
                "run",
                "--factory",
                "missing.module:factory",
                "--mode",
                "pilot",
                "--experiment-id",
                "pilot-one",
            ]
        )

    assert error.value.code == 2
    assert "both approval references" in capsys.readouterr().err


def test_deciding_cli_requires_registration_before_loading_factory(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        main(
            [
                "run",
                "--factory",
                "missing.module:factory",
                "--mode",
                "deciding",
                "--experiment-id",
                "overnight-one",
                "--live-authorization-ref",
                "approval-record",
                "--disposable-policy-ref",
                "sandbox-policy",
            ]
        )

    assert error.value.code == 2
    assert "registration document" in capsys.readouterr().err
