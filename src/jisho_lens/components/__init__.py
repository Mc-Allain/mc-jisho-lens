"""Optional components: UniDic-lite / full UniDic (word splitting) and the JMdict, KANJIDIC2
and Wiktionary dictionaries. Nothing is installed by default."""

from jisho_lens.components.manager import (
    ComponentError,
    install,
    on_before_change,
    removal_effects,
    status,
    uninstall,
)
from jisho_lens.components.registry import (
    COMPONENTS,
    DICTIONARIES,
    UNIDICS,
    components_dir,
    installed,
    installed_unidics,
    is_installed,
)

__all__ = ["COMPONENTS", "DICTIONARIES", "UNIDICS", "ComponentError", "components_dir",
           "install", "installed", "installed_unidics", "is_installed", "on_before_change",
           "removal_effects", "status", "uninstall"]
