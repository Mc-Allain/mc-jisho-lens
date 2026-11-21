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
