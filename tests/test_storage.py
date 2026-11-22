"""Duplicates, space limit, shared images, favorites and History deletion options."""

import os
import sqlite3
import time

from PIL import Image, ImageDraw

from jisho_lens.core.history import HistoryStore
from jisho_lens.core.ocr_data.corrections import CorrectionStore
from jisho_lens.core.ocr_data.store import OcrDataStore, png_bytes, sample_id
from jisho_lens.core.storage import clear_all, share_identical_images

LINE = "テララ\nそうた、探しに行くまえに"


def img(text: str = "a", size=(120, 40), shift: int = 0) -> Image.Image:
    im = Image.new("RGB", size, (20, 20, 20))
    ImageDraw.Draw(im).text((5 + shift, 10), text, fill=(255, 255, 255))
    return im


def add(store, image, text, speaker="テララ"):
    return store.add_capture(image, text, engine="rapid-v6", preset="none", seconds=1.0,
                             speaker=speaker)


# ---------- duplicates ----------
def test_other_crop_of_the_same_sentence_is_not_kept_twice(tmp_path):
    store = OcrDataStore(tmp_path)
    first = add(store, img("x"), LINE)
    again = add(store, img("x", shift=2), LINE)  # a slightly different crop
    assert again == first and len(store.all()) == 1
    assert add(store, img("y"), "べつのぶん") != first and len(store.all()) == 2


def test_new_ocr_matching_a_corrected_answer_is_a_duplicate(tmp_path):
    store = OcrDataStore(tmp_path)
    sid = add(store, img("x"), LINE)
    store.set_truth(sid, "そうだ、探しに行くまえに", "edited")  # truth has no speaker line
    # later OCR reads it right (with the speaker line)
    assert add(store, img("x", shift=3), "テララ\nそうだ、探しに行くまえに") == sid


def test_remove_duplicates_keeps_checked_and_favorites(tmp_path):
    store = OcrDataStore(tmp_path)
    ids = []
    for i in range(4):  # samples kept before duplicates were detected
        png = png_bytes(img("x", shift=i))
        sid = sample_id(png)
        from jisho_lens.core.ocr_data.store import Sample
        store.save(Sample(id=sid, ocr_text=LINE, created=f"2026-11-22T22:0{i}:00"), png)
        ids.append(sid)
    store.set_truth(ids[0], "そうだ", "edited")
    store.set_truth(ids[2], "そうだ、", "edited")
    mapping = store.remove_duplicates(keep={ids[3]})
    left = {s.id for s in store.all()}
    assert left == {ids[0], ids[2], ids[3]}  # both corrected ones stay, plus the favorite
    assert mapping == {ids[1]: ids[0]}


# ---------- space limit ----------
def test_limit_removes_oldest_unchecked_only(tmp_path):
    store = OcrDataStore(tmp_path)
    ids = []
    for i in range(5):
        sid = add(store, img(f"t{i}", size=(300, 100)), f"ぶん{i}")
        s = store.get(sid)
        s.created = f"2026-11-22T22:0{i}:00"
        store.save(s)
        ids.append(sid)
    store.set_truth(ids[0], "ぶん0", "confirmed")  # oldest, but checked
    def size(sid):
        return sum((tmp_path / "samples" / f"{sid}.{e}").stat().st_size for e in ("png", "json"))

    limit = store.size_bytes() - size(ids[2]) - size(ids[3])
    assert store.enforce_limit(limit, keep={ids[1]}) == 2  # ids[2], ids[3] go
    assert {s.id for s in store.all()} == {ids[0], ids[1], ids[4]}
    # checked and favorites stay even when still over the limit
    assert store.enforce_limit(1, keep={ids[1]}) == 1
    assert {s.id for s in store.all()} == {ids[0], ids[1]}
    assert store.enforce_limit(0) == 0  # no limit


def test_delete_all_keeps_favorites_samples(tmp_path):
    store = OcrDataStore(tmp_path)
    a, b = add(store, img("a"), "あ"), add(store, img("b"), "い")
    assert store.delete_all(keep={a}) == 1
    assert [s.id for s in store.all()] == [a]
    assert store.delete_all() == 1 and store.all() == []
    assert b


# ---------- one image file for History and OCR data ----------
def test_history_shares_the_sample_image(tmp_path):
    data = OcrDataStore(tmp_path / "ocr-data")
    h = HistoryStore(tmp_path)
    image = img("x")
    png = png_bytes(image)
    sid = add(data, image, LINE)
    cid = h.add(image, "そうた", sample_id=sid, png=png, same_file=data.png_path(sid))
    c = h.get(cid)
    assert os.path.samefile(c.image_path, data.png_path(sid))
    h.delete(cid)  # deleting the History copy leaves the sample
    assert data.png_path(sid).exists()
    h.close()


def test_share_identical_images_for_old_captures(tmp_path):
    data = OcrDataStore(tmp_path / "ocr-data")
    h = HistoryStore(tmp_path)
    image = img("x")
    sid = add(data, image, LINE)
    cid = h.add(image, "そうた", sample_id=sid, png=png_bytes(image))  # stored twice
    assert share_identical_images(h, data) == 1
    assert os.path.samefile(h.get(cid).image_path, data.png_path(sid))
    assert share_identical_images(h, data) == 0
    h.close()


# ---------- favorites and deleting ----------
def _history(tmp_path, n=5):
    h = HistoryStore(tmp_path)
    ids = [h.add(img(str(i)), f"ぶん{i}") for i in range(n)]
    return h, ids


def test_favorites_cannot_be_deleted(tmp_path):
    h, ids = _history(tmp_path)
    h.set_favorite(ids[0], True)
    assert not h.delete(ids[0]) and h.get(ids[0]) is not None
    assert len(h.delete_many(ids[:3])) == 2
    assert len(h.delete_all()) == 2
    assert [c.id for c in h.list()] == [ids[0]]
    h.set_favorite(ids[0], False)  # remove the star, then it can go
    assert h.delete(ids[0]) and h.count() == 0
    h.close()


def test_retention_skips_favorites(tmp_path):
    h, ids = _history(tmp_path)
    h.set_favorite(ids[0], True)  # oldest
    assert h.enforce_retention(2) == 2
    assert {c.id for c in h.list()} == {ids[0], ids[3], ids[4]}
    h.close()


def test_delete_time_range(tmp_path):
    h, ids = _history(tmp_path)
    now = time.time()
    with h._lock:  # spread the captures over five hours
        for i, cid in enumerate(ids):
            h._db.execute("UPDATE captures SET created_at = ? WHERE id = ?",
                          (now - (4 - i) * 3600, cid))
        h._db.commit()
    h.set_favorite(ids[2], True)
    start, end = now - 3 * 3600 - 1, now - 1 * 3600 + 1  # ids[1] .. ids[3]
    assert h.count_range(start, end) == (2, 1)
    assert {c.id for c in h.delete_range(start, end)} == {ids[1], ids[3]}
    assert {c.id for c in h.list()} == {ids[0], ids[2], ids[4]}
    h.close()


def test_filters(tmp_path):
    h, ids = _history(tmp_path)
    h.set_favorite(ids[1], True)
    h.set_edited(ids[2], "なおした")
    assert [c.id for c in h.list(show="favorites")] == [ids[1]]
    assert [c.id for c in h.list(show="corrected")] == [ids[2]]
    assert len(h.list(show="all")) == 5
    h.close()


def test_old_history_gets_the_favorite_column(tmp_path):
    db = sqlite3.connect(tmp_path / "history.db")
    db.executescript("""CREATE TABLE captures (id INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at REAL NOT NULL, image_file TEXT NOT NULL, ocr_text TEXT NOT NULL,
      edited_text TEXT, speaker TEXT, engine TEXT, preset TEXT, seconds REAL, sample_id TEXT);
      INSERT INTO captures (created_at, image_file, ocr_text) VALUES (1, 'a.png', 'あ');""")
    db.commit()
    db.close()
    h = HistoryStore(tmp_path)
    assert h.list()[0].favorite is False
    h.close()


def test_clear_all_keeps_favorites(tmp_path):
    data = OcrDataStore(tmp_path / "ocr-data")
    h = HistoryStore(tmp_path)
    corrections = CorrectionStore(tmp_path / "ocr-data")
    corrections.learn(["そうた、"], ["そうだ、"])
    a = add(data, img("a"), "あいう")
    b = add(data, img("b"), "えおか")
    data.set_truth(b, "えおが", "edited")
    fav = h.add(img("a"), "あいう", sample_id=a)
    h.add(img("b"), "えおか", sample_id=b)
    h.set_favorite(fav, True)
    assert clear_all(h, data, corrections) == (1, 1, 1)
    assert [c.id for c in h.list()] == [fav]
    assert [s.id for s in data.all()] == [a]
    assert corrections.all() == []
    h.close()
