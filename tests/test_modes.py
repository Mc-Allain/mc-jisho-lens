import pytest

from jisho_lens.core.analysis import available_modes, shared_analyzer
from jisho_lens.core.analysis.analyzer import DictionaryMissing, unidic_dir
from jisho_lens.core.analysis.pipeline import analyze_text
from jisho_lens.core.settings import Settings

LITE = available_modes()["lite"] is None


def test_default_is_plain_text():
    s = Settings()
    assert s.analysis.word_splitting == "none"
    assert not s.analysis.dictionary_active
    s.analysis.word_splitting = "lite"
    assert s.analysis.dictionary_active


def test_none_mode_gives_plain_text():
    result = analyze_text(["村長の家に寄るぞ。"], "none", use_dictionary=True)
    assert not result.has_words and result.dictionary is None
    assert shared_analyzer("none") is None


def test_modes_report_install_hint_when_missing():
    for mode, reason in available_modes().items():
        if mode == "none":
            assert reason is None
        elif reason is not None:
            assert "Components" in reason
            with pytest.raises(DictionaryMissing):
                unidic_dir(mode)


@pytest.mark.skipif(not LITE, reason="UniDic-lite component not installed")
def test_lite_without_dictionary():
    result = analyze_text(["村長の家に寄るぞ。"], "lite", use_dictionary=False)
    assert result.has_words and result.dictionary is None
    assert any(t.surface == "村長" for t in result.tokens[0])


def test_missing_unidic_falls_back_to_plain_text():
    missing = [m for m, reason in available_modes().items() if reason is not None]
    if not missing:
        pytest.skip("every UniDic is installed here")
    result = analyze_text(["村長の家"], missing[0], use_dictionary=True)
    assert not result.has_words and result.warning


def test_settings_round_trip(tmp_path):
    s = Settings()
    s.analysis.word_splitting = "lite"
    s.save(tmp_path / "s.toml")
    assert Settings.load(tmp_path / "s.toml").analysis.word_splitting == "lite"
