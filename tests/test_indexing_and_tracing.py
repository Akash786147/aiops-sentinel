import textwrap

from sentinel.context import ChangedRange, EvidencePacket, behavioural_change, redact
from sentinel.indexing import CodeIndex, chunk_python, tokenize
from sentinel.registry import load_registry
from sentinel.tracing import decide, rank, rank_recent_changes

APP = textwrap.dedent('''
    from fastapi import FastAPI
    from shop import repo

    app = FastAPI()


    @app.get("/items")
    def list_items():
        return repo.load_items()
''')
REPO = textwrap.dedent('''
    import time

    ROUND_TRIP = 0.001


    def load_items():
        """All items with their owner."""
        return [dict(i, owner=load_owner(i)) for i in range(10)]


    def load_owner(item):
        time.sleep(ROUND_TRIP)
        return "x"


    def unrelated_report():
        return "report"
''')


def _workspace(tmp_path):
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "app.py").write_text(APP)
    (tmp_path / "shop" / "repo.py").write_text(REPO)
    (tmp_path / "services.yaml").write_text(
        "server: s\nservices:\n  - {name: shop, owner: team, path: shop, module: shop.app:app, port: 1}\nshared_code: []\n")
    return tmp_path


def _packet(changes=()):
    incident = {"id": "INC-1", "symptoms": ["latency"], "routes": ["GET /items"],
                "signals": [{"kind": "latency", "route": "GET /items", "baseline": 5, "observed": 90, "z": 40}]}
    return EvidencePacket(incident=incident, service="shop", owner="team", code_path="shop", changes=list(changes))


def test_chunks_follow_the_syntax_tree_and_keep_routes_and_refs():
    chunks = {c.symbol: c for c in chunk_python("shop/app.py", APP)}
    assert chunks["list_items"].routes == ["GET /items"]
    assert "load_items" in chunks["list_items"].refs
    assert "app" not in chunks["list_items"].refs  # decorators are wiring, not calls
    assert chunks["app (module)"].kind == "module"


def test_tokenizer_splits_identifiers():
    assert {"load", "owner", "load_owner"} <= set(tokenize("load_owner"))


def test_call_graph_reaches_helpers_from_the_route_handler(tmp_path):
    index = CodeIndex(_workspace(tmp_path), dense=False)
    handler = index.handlers("GET /items")
    depth = {index.chunks[i].symbol: d for i, d in index.reachable(handler).items()}
    assert depth["list_items"] == 0 and depth["load_items"] == 1 and depth["load_owner"] == 2
    assert "unrelated_report" not in depth


def test_changed_code_on_the_call_path_ranks_first(tmp_path):
    root = _workspace(tmp_path)
    index = CodeIndex(root, dense=False)
    change = ChangedRange("shop/repo.py", 7, 9, "abc", "Show owner", 1, True)
    suspects = rank(index, _packet([change]), load_registry(root))
    assert suspects[0].symbol == "load_items"
    assert decide(_packet().incident, suspects)["action"] == "code_fix"


def test_cosmetic_change_is_not_counted_as_evidence(tmp_path):
    root = _workspace(tmp_path)
    index = CodeIndex(root, dense=False)
    cosmetic = ChangedRange("shop/repo.py", 16, 17, "abc", "Docs", 1, False)
    suspects = rank(index, _packet([cosmetic]), load_registry(root))
    assert suspects[0].features["changed_lines"] == 0.0
    assert [s.symbol for s in rank_recent_changes(index, _packet([cosmetic]))] == ["unrelated_report"]


def test_behavioural_change_ignores_docstrings_and_comments():
    assert not behavioural_change('def f():\n    "a"\n    return 1\n', 'def f():\n    "b"  # note\n    return 1\n')
    assert behavioural_change("def f():\n    return 1\n", "def f():\n    return 2\n")


def test_redaction_removes_secrets_but_keeps_numbers():
    text = redact('api_key="sk-123" card 4111111111111111 score 0.12345678901234567')
    assert "sk-123" not in text and "4111111111111111" not in text and "0.12345678901234567" in text
