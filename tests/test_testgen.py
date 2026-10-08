from sentinel.testgen import guard

VALID = """
from fastapi.testclient import TestClient
from shop.app import app


def test_items_fast():
    assert TestClient(app).get("/items").status_code == 200
"""


def test_guard_accepts_a_plain_behavioural_test():
    assert guard(VALID) == []


def test_guard_rejects_dangerous_or_vacuous_tests():
    assert any("forbidden import os" in p for p in guard("import os\n" + VALID))
    assert any("forbidden call open" in p for p in guard(VALID + "\nopen('x', 'w')\n"))
    assert any("skipped" in p for p in guard("import pytest\n" + VALID.replace("def test_", "@pytest.mark.skip\ndef test_")))
    assert "no assert statement" in guard("def test_nothing():\n    pass\n")
    assert guard("def test_(:\n")[0].startswith("syntax error")
