from services.retrieval import RepositoryIndex


def test_code_search_finds_orders_handler(tmp_path):
    (tmp_path / "orders.py").write_text("def list_orders():\n    database.query('orders')\n")
    index = RepositoryIndex(tmp_path)
    index.ingest()
    result = index.search("which function queries orders database?")
    assert result[0]["path"] == "orders.py"
    assert "list_orders" in result[0]["text"]
