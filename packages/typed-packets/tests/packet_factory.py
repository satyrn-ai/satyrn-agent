import json
from typing import Any


def valid_packet() -> dict[str, Any]:
    return {
        "schema_version": 0,
        "packet_id": "add-contact-rule",
        "task": "Add a contact validation rule.",
        "readable_files": ["app/domain.py"],
        "file_changes": [
            {"path": "app/domain.py", "operation": "modify"},
            {"path": "tests/test_domain.py", "operation": "create"},
        ],
        "consumes": [
            {
                "source": {"root_id": "workspace", "path": "app/domain.py"},
                "qualified_name": "Contact",
                "expected_signature": None,
            }
        ],
        "produces": [
            {
                "path": "app/domain.py",
                "qualified_name": "new_rule",
                "operation": "create",
                "kind": "function",
                "declaration": "def new_rule(value: str) -> bool:",
            }
        ],
        "imports": [],
        "tests": [
            {
                "path": "tests/test_domain.py",
                "operation": "create",
                "content": "def test_rule() -> None:\n    pass\n",
            }
        ],
        "gates": [
            {
                "argv": ["pytest", "tests/test_domain.py"],
                "cwd": ".",
                "before": {"exit_code": "nonzero", "reason": "New test fails."},
                "after": {"exit_code": 0, "reason": "New test passes."},
            }
        ],
        "known_facts": [],
        "acceptance_criteria": ["The rule accepts a valid contact."],
        "preserved_behavior": [],
    }


def valid_document() -> str:
    return json.dumps(valid_packet())
