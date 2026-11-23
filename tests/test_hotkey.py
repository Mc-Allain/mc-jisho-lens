import pytest

from jisho_lens.core.hotkey import MOD_ALT, MOD_CONTROL, MOD_SHIFT, parse_hotkey


def test_parse_basic():
    hk = parse_hotkey("Ctrl+Alt+J")
    assert hk.modifiers == MOD_CONTROL | MOD_ALT
    assert hk.vk == ord("J")
    assert hk.text == "Ctrl+Alt+J"


def test_parse_lowercase_and_function_key():
    assert parse_hotkey("ctrl+shift+f8").vk == 0x77
    assert parse_hotkey("ctrl+shift+f8").modifiers == MOD_CONTROL | MOD_SHIFT
    assert parse_hotkey("F9").modifiers == 0  # function keys allowed alone


@pytest.mark.parametrize("bad", ["", "J", "Ctrl+", "Hyper+J", "Ctrl+Ü"])
def test_parse_rejects(bad):
    with pytest.raises(ValueError):
        parse_hotkey(bad)


def test_named_hotkeys_and_esc():
    from PySide6.QtWidgets import QApplication

    from jisho_lens.core.hotkey import ESC, HotkeyManager

    app = QApplication.instance() or QApplication([])
    hk = HotkeyManager(app)
    try:
        # unusual combos so a running copy of the app doesn't hold them
        assert hk.register("Ctrl+Alt+Shift+F11", "show") == (True, "Ctrl+Alt+Shift+F11")
        assert hk.current_for("show") == "Ctrl+Alt+Shift+F11"
        ok, _ = hk.register_key(ESC, "cancel")
        assert ok and hk.current_for("cancel") == "Esc"
        hk.unregister("cancel")
        assert hk.current_for("cancel") is None
        assert hk.register("", "show") == (True, "")  # empty removes it
        assert hk.current_for("show") is None
        assert hk.register("Ctrl+Hyper", "show")[0] is False
    finally:
        hk.unregister()
