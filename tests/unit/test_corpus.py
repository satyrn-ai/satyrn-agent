from tests.e2e.corpus import CorpusCase, is_corpus_case


def _case() -> CorpusCase:
    return {
        "name": "validation",
        "prompt": "prompt",
        "seed": 1,
        "temperature": 0.0,
        "max_tokens": 1,
        "branches": [],
    }


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
