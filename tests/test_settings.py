from jisho_lens.core.settings import Settings


def test_defaults_when_missing(tmp_path):
    s = Settings.load(tmp_path / "nope.toml")
    assert s.capture.hotkey == "Ctrl+Alt+J"
    assert s.ocr.engine == "rapid-v6"


def test_round_trip(tmp_path):
    path = tmp_path / "settings.toml"
    s = Settings()
    s.capture.hotkey = "Ctrl+Shift+K"
    s.capture.delay_seconds = 0.5
    s.window.geometry = [10, 20, 600, 300]
    s.save(path)
    loaded = Settings.load(path)
    assert loaded.capture.hotkey == "Ctrl+Shift+K"
    assert loaded.capture.delay_seconds == 0.5
    assert loaded.window.geometry == [10, 20, 600, 300]


def test_bad_values_fall_back(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text('[capture]\nhotkey = 5\ndelay_seconds = 1\n[ocr]\nengine = "windows"\n',
                    encoding="utf-8")
    s = Settings.load(path)
    assert s.capture.hotkey == "Ctrl+Alt+J"  # wrong type ignored
    assert s.capture.delay_seconds == 1.0  # int accepted for float
    assert s.ocr.engine == "windows"


def test_corrupt_file(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text("not = [valid", encoding="utf-8")
    assert Settings.load(path).ocr.engine == "rapid-v6"
