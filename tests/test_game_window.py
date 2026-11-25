import core.game_window as gw


def test_foreground_process_name_is_lowercase_exe_or_none():
    name = gw.foreground_process_name()
    assert name is None or (name == name.lower() and name.endswith(".exe"))


def set_foreground(monkeypatch, process, cls):
    monkeypatch.setattr(gw, "foreground_process_name", lambda: process)
    monkeypatch.setattr(gw, "foreground_class_name", lambda: cls)


def test_is_game_foreground_matches_listed_names(monkeypatch):
    set_foreground(monkeypatch, "league of legends.exe", "SomeClass")
    assert gw.is_game_foreground(frozenset({"league of legends.exe"})) is True
    assert gw.is_game_foreground(frozenset({"chrome.exe"})) is False


def test_unreadable_process_and_unknown_class_counts_as_not_game(monkeypatch):
    set_foreground(monkeypatch, None, None)
    assert gw.is_game_foreground(frozenset({"league of legends.exe"})) is False
    set_foreground(monkeypatch, None, "Notepad")
    assert gw.is_game_foreground(frozenset({"league of legends.exe"})) is False


def test_riot_window_class_counts_as_game_even_when_process_unreadable(monkeypatch):
    """Vanguard / game chạy quyền cao hơn tool có thể làm không mở được process: lớp cửa sổ vẫn nhận ra game."""
    set_foreground(monkeypatch, None, "RiotWindowClass")
    assert gw.is_game_foreground(frozenset({"league of legends.exe"})) is True


def test_riot_window_class_counts_as_game_even_when_exe_renamed(monkeypatch):
    set_foreground(monkeypatch, "league_of_legends_moi.exe", "RiotWindowClass")
    assert gw.is_game_foreground(frozenset({"league of legends.exe"})) is True


def test_other_app_is_not_game_even_with_game_in_title(monkeypatch):
    """Tab trình duyệt tên 'League of Legends' không phải game: chỉ tin process hoặc lớp cửa sổ, không tin tiêu đề."""
    set_foreground(monkeypatch, "chrome.exe", "Chrome_WidgetWin_1")
    assert gw.is_game_foreground(frozenset({"league of legends.exe"})) is False


def test_window_class_and_title_of_no_window_are_empty():
    assert gw.window_class_name(None) is None
    assert gw.window_title(None) == ""


def test_describe_foreground_returns_text_and_never_raises():
    text = gw.describe_foreground()
    assert isinstance(text, str) and text


class TestTftClientProcess:
    """Log thật của người dùng: game là tftclient-win64-shipping.exe (lớp UnrealWindow), config cũ chỉ lưu League of Legends.exe."""

    def test_new_tft_client_is_game_even_with_the_old_saved_config(self, monkeypatch):
        from core.config import game_process_set

        set_foreground(monkeypatch, "tftclient-win64-shipping.exe", "UnrealWindow")
        assert gw.is_game_foreground(game_process_set(["League of Legends.exe"])) is True

    def test_other_unreal_games_are_not_game(self, monkeypatch):
        from core.config import game_process_set

        set_foreground(monkeypatch, "fortniteclient-win64-shipping.exe", "UnrealWindow")
        assert gw.is_game_foreground(game_process_set(["League of Legends.exe"])) is False


class TestSuspectGameProcess:
    NAMES = frozenset({"league of legends.exe"})

    def suspect(self, monkeypatch, process):
        monkeypatch.setattr(gw, "window_process_name", lambda hwnd: process)
        return gw.suspect_game_process(self.NAMES)

    def test_unlisted_tft_or_league_process_is_suggested(self, monkeypatch):
        assert self.suspect(monkeypatch, "tftclient-win64-shipping.exe") == "tftclient-win64-shipping.exe"
        assert self.suspect(monkeypatch, "leagueclientux.exe") == "leagueclientux.exe"

    def test_recognised_or_unrelated_process_is_not_suggested(self, monkeypatch):
        assert self.suspect(monkeypatch, "league of legends.exe") is None
        assert self.suspect(monkeypatch, "chrome.exe") is None  # kể cả khi tab có chữ TFT: chỉ xét tên process
        assert self.suspect(monkeypatch, None) is None

    def test_the_tool_itself_is_never_suggested(self, monkeypatch):
        assert self.suspect(monkeypatch, "tft_auto_buy.exe") is None
        monkeypatch.setattr(gw.sys, "executable", r"C:\Tools\tft_reroll_custom.exe")
        assert self.suspect(monkeypatch, "tft_reroll_custom.exe") is None
