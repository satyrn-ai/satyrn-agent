from satyrn_agent._generated.config import ConfigDocument
from satyrn_agent.config import DFlashMode
from satyrn_agent.config_io import config_from_dict


def test_generated_config_document_feeds_the_parser() -> None:
    document = ConfigDocument(dflash="off")

    assert config_from_dict(document).dflash is DFlashMode.OFF
