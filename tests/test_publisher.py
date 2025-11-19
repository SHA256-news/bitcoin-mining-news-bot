import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.publisher import publish  # noqa: E402


def test_publish_dry_run(monkeypatch, capsys):
    monkeypatch.setenv("DRY_RUN", "1")
    id1, id2 = publish("hello", "world")
    assert id1 == "" and id2 == ""
    out = capsys.readouterr().out
    assert "[DRY-RUN]" in out
