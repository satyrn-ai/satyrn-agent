import subprocess

from satyrn_agent._generated.config import ConfigDocument


def test_production_config_dto_is_generated() -> None:
    document = ConfigDocument(dflash="auto", drafter_path=None)

    assert document == {"dflash": "auto", "drafter_path": None}


def test_named_generation_jobs_are_current() -> None:
    subprocess.run(["datamodel-codegen", "--all-jobs", "--check"], check=True)
