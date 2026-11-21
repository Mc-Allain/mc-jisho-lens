"""Component rules, checked in a temporary components folder with stand-in installs
(no downloads)."""

import json

import pytest

from jisho_lens import components
from jisho_lens.components import registry


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv("JISHO_LENS_COMPONENTS", str(tmp_path))
    return tmp_path


def fake_install(component_id: str) -> None:
    d = registry.component_dir(component_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "installed.json").write_text(json.dumps({"fake": True}), encoding="utf-8")


def test_nothing_installed_by_default(folder):
    assert components.installed() == []
    assert all(not c["installed"] for c in components.status())


def test_dictionaries_need_a_unidic(folder):
    for dictionary in components.DICTIONARIES:
        with pytest.raises(components.ComponentError, match="needs word splitting"):
            components.install(dictionary)


def test_removing_last_unidic_removes_dictionaries(folder):
    for c in ("unidic-lite", "unidic-full", "jmdict", "kanjidic2", "wiktionary"):
        fake_install(c)
    # another UniDic remains: nothing else goes
    assert components.removal_effects("unidic-full") == []
    assert components.uninstall("unidic-full") == ["unidic-full"]
    assert components.is_installed("jmdict")
    # the last one: the dictionaries go too
    assert set(components.removal_effects("unidic-lite")) == {"jmdict", "kanjidic2",
                                                              "wiktionary"}
    removed = components.uninstall("unidic-lite")
    assert set(removed) == {"unidic-lite", "jmdict", "kanjidic2", "wiktionary"}
    assert components.installed() == []


def test_each_dictionary_is_removable_on_its_own(folder):
    for c in ("unidic-lite", "jmdict", "kanjidic2", "wiktionary"):
        fake_install(c)
    assert components.uninstall("kanjidic2") == ["kanjidic2"]
    assert set(components.installed()) == {"unidic-lite", "jmdict", "wiktionary"}


def test_unknown_component(folder):
    with pytest.raises(components.ComponentError):
        components.install("nope")
