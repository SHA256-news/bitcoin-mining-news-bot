from src.publisher import publish


def test_publish_dry_run(monkeypatch, capsys):
    monkeypatch.setenv("DRY_RUN", "1")
    id1, id2 = publish("hello", "world")
    assert id1 == "" and id2 == ""
    out = capsys.readouterr().out
    assert "[DRY-RUN]" in out
