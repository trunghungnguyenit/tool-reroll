import core.game_window as gw


def test_foreground_process_name_is_lowercase_exe_or_none():
    name = gw.foreground_process_name()
    assert name is None or (name == name.lower() and name.endswith(".exe"))


def test_is_game_foreground_matches_only_listed_names(monkeypatch):
    monkeypatch.setattr(gw, "foreground_process_name", lambda: "league of legends.exe")
    assert gw.is_game_foreground(frozenset({"league of legends.exe"})) is True
    assert gw.is_game_foreground(frozenset({"chrome.exe"})) is False


def test_unreadable_foreground_process_counts_as_not_game(monkeypatch):
    monkeypatch.setattr(gw, "foreground_process_name", lambda: None)
    assert gw.is_game_foreground(frozenset({"league of legends.exe"})) is False
