from jisho_lens.core.ocr.base import OcrLine
from jisho_lens.core.ocr.cleanup import clean, find_speaker, strip_key_icons


def L(text, box=None):  # noqa: N802
    return OcrLine(text=text, box=box)


def test_strip_key_icons():
    lines = ["キボに乗る T", "マウントホイールを開く T を長押し", "G", "[Esc]", "キボスターリンク"]
    expected = ["キボに乗る", "マウントホイールを開く T を長押し", "キボスターリンク"]
    assert strip_key_icons(lines) == expected


def test_key_letters_inside_text_are_kept():
    # 'Fキーで…' : the F is part of the sentence, keep it
    assert strip_key_icons(["Fキーで協力攻撃を発動"]) == ["Fキーで協力攻撃を発動"]
    assert strip_key_icons(["HP 1,250"]) == ["HP 1,250"]


def test_speaker_detected_when_centred():
    lines = [
        L("テララ", (420, 10, 480, 34)),
        L("そうだ、探しに行くまえにじっちゃ……村長の家に寄るぞ。", (150, 50, 750, 74)),
        L("森の異変のことを報告して、ついでに準備も手伝ってもらうんだ！", (130, 90, 770, 114)),
    ]
    out = clean(lines)
    assert out.speaker == "テララ"
    assert out.lines[0].startswith("そうだ")


def test_no_speaker_for_menu_text():
    lines = [L("【鍵×1】を消費して宝箱を開けますか？"), L("キャンセル")]
    assert find_speaker(lines) is None
    lines = [L("確認"), L("キャンセル")]  # body not longer than first line
    assert find_speaker(lines) is None


def test_no_speaker_when_off_centre():
    lines = [
        L("第一章V 迫り来る影", (0, 0, 200, 20)),
        L("武器屋の職人と話す（任意）", (0, 30, 300, 50)),
    ]
    assert find_speaker(lines) is None  # has a digit / quest-tracker title
    lines = [L("土地の休養", (0, 0, 100, 20)), L("作物を収穫する 3/5", (0, 30, 600, 50))]
    assert find_speaker(lines) is None  # left-aligned, not centred


def test_detection_can_be_disabled():
    lines = [L("テララ"), L("村長の家に寄るぞ。それから")]
    assert clean(lines).speaker == "テララ"
    assert clean(lines, detect_speaker=False).speaker is None
