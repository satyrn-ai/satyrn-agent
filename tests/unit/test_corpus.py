import pytest
from ds4py._json import is_string_key_mapping

from tests.e2e import corpus as corpus_module
from tests.e2e.corpus import CorpusCase, is_corpus, is_corpus_case


def _case() -> CorpusCase:
    return {
        "name": "validation",
        "prompt": "prompt",
        "seed": 1,
        "temperature": 0.0,
        "max_tokens": 1,
        "branches": [],
    }


def _document() -> dict[str, object]:
    return {
        "format_version": 1,
        "target": {
            "architecture": "qwen35",
            "path_env": "SATYRN_TEST_MODEL",
            "sha256": "a" * 64,
            "quantization": "Q4_K_M",
            "sampling_defaults": {
                "temperature": 0.6,
                "top_k": 20,
                "top_p": 0.95,
                "min_p": 0.0,
            },
        },
        "drafter": {
            "path_env": "SATYRN_TEST_DRAFTER",
            "sha256": "b" * 64,
            "quantization": "Q4_0",
        },
        "cases": [],
    }


def test_valid_document_is_accepted() -> None:
    assert is_corpus(_document())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temperature", float("nan")),
        ("top_k", True),
        ("top_k", -1),
        ("top_p", "0.95"),
        ("top_p", 1.1),
        ("min_p", -0.1),
    ],
)
def test_sampling_defaults_are_validated(field: str, value: object) -> None:
    document = _document()
    raw_target = document["target"]
    assert is_string_key_mapping(raw_target)
    target = dict(raw_target)
    raw_defaults = target["sampling_defaults"]
    assert is_string_key_mapping(raw_defaults)
    defaults = dict(raw_defaults)
    defaults[field] = value
    target["sampling_defaults"] = defaults
    document["target"] = target

    assert not is_corpus(document)


def test_unknown_branch_is_rejected() -> None:
    case = dict(_case())
    case["branches"] = ["not-a-branch"]

    assert not is_corpus_case(case)


def test_unknown_expected_reason_is_rejected() -> None:
    case = dict(_case())
    case["expected_reason"] = "not-a-reason"

    assert not is_corpus_case(case)


@pytest.mark.parametrize("sha256", ["a" * 63, "A" * 64, "g" * 64])
def test_sha256_must_be_lowercase_hex(sha256: str) -> None:
    document = _document()
    raw_target = document["target"]
    assert is_string_key_mapping(raw_target)
    target = dict(raw_target)
    target["sha256"] = sha256
    document["target"] = target

    assert not is_corpus(document)


def _metrics() -> dict[str, object]:
    return {
        "committed_blocks": 1,
        "drafts_offered": 2,
        "drafts_accepted": 1,
        "replacement_anchors": 0,
        "discarded_tails": 1,
    }


def test_expected_metrics_is_valid() -> None:
    assert corpus_module.is_expected_metrics(_metrics())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("committed_blocks", -1),
        ("drafts_offered", True),
        ("drafts_accepted", 1.5),
    ],
)
def test_expected_metrics_rejects_invalid_values(field: str, value: object) -> None:
    metrics = _metrics()
    metrics[field] = value

    assert not corpus_module.is_expected_metrics(metrics)


def test_expected_metrics_rejects_missing_counter() -> None:
    metrics = _metrics()
    del metrics["committed_blocks"]

    assert not corpus_module.is_expected_metrics(metrics)


def test_expected_reason_must_be_a_known_string() -> None:
    case = dict(_case())
    case["expected_reason"] = []

    assert not is_corpus_case(case)
    case["expected_reason"] = "context_reserve"
    assert not is_corpus_case(case)


def test_think_must_be_nonnegative() -> None:
    case = _case()
    case["think"] = -1

    assert not is_corpus_case(case)
    case["think"] = 0
    assert is_corpus_case(case)


def test_optional_ints_must_be_positive() -> None:
    ctx_case = _case()
    ctx_case["ctx"] = 0
    assert not is_corpus_case(ctx_case)

    drafts_case = _case()
    drafts_case["draft_tokens"] = 0
    assert not is_corpus_case(drafts_case)
