"""HTML for the main window's text view: clickable words, furigana, romaji, word popup
with dictionary meanings, grammar and kanji details."""

from __future__ import annotations

import html
import json

from jisho_lens.core.analysis import Token
from jisho_lens.dictionary.enrich import PageDictionary

_CSS = """
html, body { margin: 0; padding: 0; background: #1d1f24; color: #f1f1f1;
  font-family: "Yu Gothic UI", "Yu Gothic", "Meiryo", sans-serif; }
body { padding: 8px 14px 14px; font-size: %(size)dpx; line-height: 1.25; }
.ln { margin: 0 0 10px 0; }
.jp { line-height: 2.1; }
ruby rt { font-size: 0.5em; color: #9fc4ff; }
body.no-furi .jp ruby rt { visibility: hidden; }
.ro { color: #9aa3ad; font-size: 0.62em; margin-top: -2px; font-family: "Segoe UI", sans-serif; }
body.no-romaji .ro { display: none; }
.w { cursor: pointer; border-radius: 4px; padding: 0 1px; }
.w:hover { background: #33405a; }
.w.sel { background: #3d5a8a; }
.w.unk { border-bottom: 1px dotted #c9a25a; }
.empty { color: #8a8f99; font-size: 15px; }
.error { color: #ff8a80; font-size: 15px; }
#pop { position: fixed; display: none; z-index: 10; width: 380px; max-width: calc(100vw - 12px);
  max-height: calc(100vh - 12px); overflow-y: auto;
  background: #2b2f38; border: 1px solid #4a5568; border-radius: 8px; padding: 10px 12px;
  box-shadow: 0 6px 18px rgba(0,0,0,.5); font-size: 14px; line-height: 1.45; }
#pop .big { font-size: 28px; line-height: 2.0; }
#pop .big rt { font-size: 13px; color: #9fc4ff; }
#pop .row { color: #c7ccd4; }
#pop .lbl { color: #8a8f99; display: inline-block; min-width: 118px; }
#pop .ro2 { font-family: "Segoe UI", sans-serif; }
#pop h4 { margin: 8px 0 3px; font-size: 12px; color: #8a8f99; text-transform: uppercase;
  letter-spacing: .05em; font-weight: 600; }
#pop ol { margin: 0; padding-left: 20px; }
#pop li { margin: 1px 0; }
#pop .pos { color: #8fb3e8; font-size: 12px; }
#pop .tag { color: #c9a25a; font-size: 12px; }
#pop .common { color: #7fd18b; font-size: 12px; margin-left: 6px; }
#pop .alt { color: #c7ccd4; margin-top: 4px; }
#pop .gram td { padding: 1px 8px 1px 0; vertical-align: top; }
#pop .gram td:first-child { font-size: 17px; white-space: nowrap; }
#pop .note { margin-top: 6px; color: #e6c27a; }
#pop .unk { margin-top: 6px; color: #c9a25a; }
#pop .guess { margin-top: 6px; color: #e6c27a; }
#pop .fixed { margin-top: 6px; color: #8a8f99; font-size: 12px; }
#pop .kc { display: inline-block; font-size: 20px; padding: 0 6px; margin: 2px 4px 2px 0;
  border: 1px solid #4a5568; border-radius: 6px; cursor: pointer; }
#pop .kc:hover { background: #33405a; }
#pop .kbig { font-size: 52px; line-height: 1.2; float: left; margin-right: 12px; }
#pop .used { background: #3d5a8a; border-radius: 4px; padding: 0 3px; color: #fff; }
#pop .back { color: #9fc4ff; cursor: pointer; font-size: 13px; }
#pop .clear { clear: both; }
"""

_JS = r"""
const T = %(tokens)s;
const KJ = %(kanji)s;
const DICT = %(dict_state)s;  // 'ok' | 'off' (turned off in Settings) | 'missing'
const pop = document.getElementById('pop');
let current = null;
function esc(s) { const d = document.createElement('div'); d.textContent = s ?? ''; return d.innerHTML; }
function hira(s) { return (s || '').replace(/[ァ-ヶ]/g, c => String.fromCharCode(c.charCodeAt(0) - 0x60)); }
function setOpt(name, on) {
  document.body.classList.toggle(name === 'furi' ? 'no-furi' : 'no-romaji', !on);
}
function hidePop() {
  pop.style.display = 'none'; current = null;
  document.querySelectorAll('.w.sel').forEach(e => e.classList.remove('sel'));
}
function place(el) {
  pop.style.display = 'block';
  const r = el.getBoundingClientRect(), pw = pop.offsetWidth, ph = pop.offsetHeight;
  let x = Math.min(Math.max(4, r.left), window.innerWidth - pw - 4);
  let y = r.bottom + 6;
  if (y + ph > window.innerHeight - 4) y = Math.max(4, r.top - ph - 6);
  pop.style.left = x + 'px'; pop.style.top = y + 'px';
}
function isKanji(c) { return /[㐀-鿿豈-﫿々〆ヵヶ]/.test(c); }
function entryHtml(e, first) {
  let h = '';
  const forms = e.forms.length ? e.forms.join('、') + ' ' : '';
  if (!first) h += `<div class="alt"><b>${esc(forms)}</b>${esc(e.readings.join('、'))}${e.common ? '<span class="common">common</span>' : ''}</div>`;
  h += '<ol>';
  for (const s of e.senses) {
    const pos = s.pos.length ? `<span class="pos">${esc(s.pos.join(', '))}</span> ` : '';
    const tags = s.misc.concat(s.info).length ? ` <span class="tag">${esc(s.misc.concat(s.info).join('; '))}</span>` : '';
    const src = s.src.length ? ` <span class="tag">(from ${esc(s.src.join(', '))})</span>` : '';
    h += `<li>${pos}${esc(s.gloss.join('; '))}${tags}${src}</li>`;
  }
  h += '</ol>';
  if (e.more) h += `<div class="tag">+ ${e.more} more meanings</div>`;
  if (e.source === 'wiktionary') h += '<div class="tag">From Wiktionary (not in JMdict)</div>';
  return h;
}
function showPop(el) {
  const i = +el.dataset.i, t = T[i], d = t.d || {};
  hidePop();
  current = el; el.classList.add('sel');
  let h = `<div class="big">${el.innerHTML}</div>`;
  const entries = d.entries || [];
  if (entries.length && entries[0].common) h = h.replace('</div>', '<span class="common">common word</span></div>');
  if (t.r && t.r !== t.s) h += `<div class="row"><span class="lbl">Reading</span>${esc(t.r)}</div>`;
  h += `<div class="row"><span class="lbl">Romaji</span><span class="ro2">${esc(t.ro)}</span></div>`;
  h += `<div class="row"><span class="lbl">Word type</span>${esc(t.wclass || t.posEn)}</div>`;
  if (t.base && t.base !== t.s) {
    const br = t.baseR && t.baseR !== t.base ? ` (${esc(t.baseR)})` : '';
    h += `<div class="row"><span class="lbl">Dictionary form</span>${esc(t.base)}${br}</div>`;
  }
  if (entries.length) {
    h += '<h4>Meaning</h4>' + entryHtml(entries[0], true);
    for (const e of entries.slice(1)) h += entryHtml(e, false);
  } else if (DICT === 'ok') {
    h += '<div class="unk">Not in the dictionary — probably a name, a game term or a rare word. The reading is a guess.</div>';
  } else if (DICT === 'missing') {
    h += '<div class="unk">No dictionary installed — add JMdict or Wiktionary in Settings → Components.</div>';
  } else if (t.known === false) {
    h += '<div class="unk">Unknown word — probably a name or a game term. The reading is a guess.</div>';
  }
  if (t.grammar && t.grammar.length > 1) {
    h += `<h4>Grammar — ${esc(t.phrase)}</h4><table class="gram">`;
    for (const [s, lbl] of t.grammar) h += `<tr><td>${esc(s)}</td><td>${esc(lbl)}</td></tr>`;
    h += '</table>';
  }
  if (d.longer && d.longer.length) {
    h += '<h4>Part of</h4>';
    for (const x of d.longer) h += `<div class="row"><b>${esc(x.word)}</b> (${esc(x.reading)}) — ${esc(x.gloss)}</div>`;
  }
  if (d.compound) {
    const g = d.compound.guess ? ` — maybe read <b>${esc(d.compound.guess)}</b>?` : '';
    h += `<div class="guess">Possibly one coined word: <b>${esc(d.compound.text)}</b>${g} (guessed from the kanji's Chinese-derived readings)</div>`;
  }
  if (t.note) h += `<div class="note">${esc(t.note)}</div>`;
  if (t.fixed) h += '<div class="fixed">Word split adjusted using the dictionary.</div>';
  const ks = [...t.s].filter(c => isKanji(c) && KJ[c]);
  if (ks.length) {
    h += '<h4>Kanji</h4>' + ks.map(c => `<span class="kc" data-k="${esc(c)}">${esc(c)}</span>`).join('');
  }
  pop.innerHTML = h;
  pop.querySelectorAll('.kc').forEach(k => k.addEventListener('click', ev => {
    ev.stopPropagation(); showKanji(k.dataset.k, el);
  }));
  place(el);
}
function usedReading(t, k) {
  for (const [text, ruby] of (t.fg || [])) if (text === k && ruby) return hira(ruby);
  return null;
}
function unvoice(s) {
  const map = {'が':'か','ぎ':'き','ぐ':'く','げ':'け','ご':'こ','ざ':'さ','じ':'し','ず':'す','ぜ':'せ','ぞ':'そ','だ':'た','ぢ':'ち','づ':'つ','で':'て','ど':'と','ば':'は','び':'ひ','ぶ':'ふ','べ':'へ','ぼ':'ほ','ぱ':'は','ぴ':'ひ','ぷ':'ふ','ぺ':'へ','ぽ':'ほ'};
  return s ? (map[s[0]] || s[0]) + s.slice(1) : s;
}
function readingMatches(used, r) {
  if (!used) return false;
  const base = hira(r).split('.')[0].replace(/-/g, '');
  if (!base) return false;
  if (used === base || unvoice(used) === unvoice(base)) return true;
  if (used.endsWith('っ') && base.startsWith(used.slice(0, -1)) && base.length === used.length) return true;
  return false;
}
function showKanji(k, el) {
  const t = T[+el.dataset.i], info = KJ[k], used = usedReading(t, k);
  const fmt = (list) => list.map(r => {
    const shown = esc(r);
    return readingMatches(used, r) ? `<span class="used">${shown}</span>` : shown;
  }).join('、') || '—';
  let h = `<div class="back">← ${esc(t.s)}</div>`;
  h += `<div class="kbig">${esc(k)}</div><div><b>${esc(info.meanings.join(', '))}</b></div>`;
  const facts = [];
  if (info.strokes) facts.push(`${info.strokes} strokes`);
  if (info.grade) facts.push(info.grade <= 6 ? `grade ${info.grade}` : (info.grade === 8 ? 'secondary school' : 'name kanji'));
  if (info.jlpt) facts.push(`old JLPT ${info.jlpt}`);
  if (info.freq) facts.push(`#${info.freq} most used`);
  h += `<div class="tag">${esc(facts.join(' · '))}</div><div class="clear"></div>`;
  h += `<div class="row"><span class="lbl">On'yomi</span>${fmt(info.on)}</div>`;
  h += `<div class="row"><span class="lbl">Kun'yomi</span>${fmt(info.kun)}</div>`;
  if (used) h += `<div class="tag">Read <b>${esc(used)}</b> in this word${(info.on.concat(info.kun)).some(r => readingMatches(used, r)) ? '' : ' (a special reading for this word)'}.</div>`;
  if (info.examples.length) {
    h += '<h4>Common words</h4>';
    for (const [w, r, g] of info.examples) h += `<div class="row"><b>${esc(w)}</b> (${esc(r)}) — ${esc(g)}</div>`;
  }
  pop.innerHTML = h;
  pop.querySelector('.back').addEventListener('click', ev => { ev.stopPropagation(); showPop(el); });
  place(el);
}
document.addEventListener('click', e => {
  const w = e.target.closest('.w');
  if (w) { showPop(w); e.stopPropagation(); }
  else if (!e.target.closest('#pop')) hidePop();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') hidePop(); });
setOpt('furi', %(furi)s); setOpt('romaji', %(romaji)s);
"""


def _token_html(tok: Token, index: int) -> str:
    inner = "".join(
        f"<ruby>{html.escape(text)}<rt>{html.escape(ruby)}</rt></ruby>" if ruby
        else html.escape(text)
        for text, ruby in tok.furigana
    )
    if not tok.clickable:
        return inner
    cls = "w" if tok.known else "w unk"
    return f'<span class="{cls}" data-i="{index}">{inner}</span>'


def _romaji_line(tokens: list[Token]) -> str:
    parts = []
    for tok in tokens:
        if tok.romaji:
            parts.append(tok.romaji + (" " if tok.space_after else ""))
    return html.escape("".join(parts).strip())


def page_for_tokens(lines: list[list[Token]], font_size: int, furigana: bool, romaji: bool,
                    dictionary: PageDictionary | None = None) -> str:
    flat: list[dict] = []
    body = []
    words = dictionary.words if dictionary is not None else []
    for tokens in lines:
        jp = []
        for tok in tokens:
            jp.append(_token_html(tok, len(flat)))
            d = tok.to_dict()
            d["fg"] = [[t, r] for t, r in tok.furigana]
            if len(flat) < len(words):
                d["d"] = words[len(flat)]
            flat.append(d)
        body.append(f"<div class='ln'><div class='jp'>{''.join(jp)}</div>"
                    f"<div class='ro'>{_romaji_line(tokens)}</div></div>")
    kanji = dictionary.kanji if dictionary is not None else {}
    # "ok": a word dictionary is installed, so "not in the dictionary" is meaningful
    state = "ok" if dictionary is not None and dictionary.has_words else "off"
    return _page("".join(body), font_size, flat, kanji, state, furigana, romaji)


def page_for_plain(lines: list[str], font_size: int) -> str:
    """Plain OCR text (word splitting turned off)."""
    body = "".join(f"<div class='ln'><div class='jp'>{html.escape(line)}</div></div>"
                   for line in lines)
    return _page(body, font_size, [], {}, "off", True, False)


def page_for_message(message: str, font_size: int, error: bool = False) -> str:
    cls = "error" if error else "empty"
    return _page(f"<p class='{cls}'>{html.escape(message)}</p>", font_size, [], {}, "off",
                 True, False)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _page(body: str, font_size: int, tokens: list[dict], kanji: dict, dict_state: str,
          furigana: bool, romaji: bool) -> str:
    js = _JS % {
        "tokens": _json(tokens),
        "kanji": _json(kanji),
        "dict_state": _json(dict_state),
        "furi": "true" if furigana else "false",
        "romaji": "true" if romaji else "false",
    }
    return (
        "<!doctype html><html lang='ja'><head><meta charset='utf-8'><style>"
        + _CSS % {"size": font_size}
        + "</style></head><body>" + body + "<div id='pop'></div><script>" + js
        + "</script></body></html>"
    )
