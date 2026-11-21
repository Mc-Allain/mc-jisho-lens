"""Character classes and kana conversion."""

from __future__ import annotations

_KATA_START, _KATA_END = 0x30A1, 0x30F6  # ァ..ヶ
_HIRA_OFFSET = 0x60

# Characters that behave like kanji for furigana: 々 (repeat), 〆, ヶ / ヵ (as in 一ヶ月).
_KANJI_LIKE = set("々〆ヶヵ")


def is_kanji(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF  # CJK unified
        or 0x3400 <= cp <= 0x4DBF  # extension A
        or 0xF900 <= cp <= 0xFAFF  # compatibility
        or 0x20000 <= cp <= 0x2FA1F  # extensions B+
        or ch in _KANJI_LIKE
    )


def is_kana(ch: str) -> bool:
    cp = ord(ch)
    return 0x3041 <= cp <= 0x309F or 0x30A0 <= cp <= 0x30FF or ch in "ー"


def has_kanji(text: str) -> bool:
    return any(is_kanji(ch) for ch in text)


def has_japanese(text: str) -> bool:
    return any(is_kanji(ch) or is_kana(ch) for ch in text)


def is_all_kana(text: str) -> bool:
    return bool(text) and all(is_kana(ch) for ch in text)


def to_hiragana(text: str) -> str:
    """Katakana -> hiragana (ヴ, ヵ, ヶ included; ー and others unchanged)."""
    out = []
    for ch in text:
        cp = ord(ch)
        if _KATA_START <= cp <= _KATA_END and ch not in "ヵヶ":
            out.append(chr(cp - _HIRA_OFFSET))
        else:
            out.append(ch)
    return "".join(out)
