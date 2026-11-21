"""HTML for the main window's text view: clickable words, furigana, romaji, word popup."""

from __future__ import annotations

import html
import json

from jisho_lens.core.analysis import Token

_CSS = """
html, body { margin: 0; padding: 0; background: #1d1f24; color: #f1f1f1;
  font-family: "Yu Gothic UI", "Yu Gothic", "Meiryo", sans-serif; }
body { padding: 8px 14px 14px; font-size: %(size)dpx; line-height: 1.25; }
.ln { margin: 0 0 10px 0; }
.jp { line-height: 2.1; }
ruby rt { font-size: 0.5em; color: #9fc4ff; }
body.no-furi ruby rt { visibility: hidden; }
.ro { color: #9aa3ad; font-size: 0.62em; margin-top: -2px; font-family: "Segoe UI", sans-serif; }
body.no-romaji .ro { display: none; }
.w { cursor: pointer; border-radius: 4px; padding: 0 1px; }
.w:hover { background: #33405a; }
.w.sel { background: #3d5a8a; }
.w.unk { border-bottom: 1px dotted #c9a25a; }
.empty { color: #8a8f99; font-size: 15px; }
.error { color: #ff8a80; font-size: 15px; }
#pop { position: fixed; display: none; z-index: 10; max-width: 340px; min-width: 200px;
  background: #2b2f38; border: 1px solid #4a5568; border-radius: 8px; padding: 10px 12px;
  box-shadow: 0 6px 18px rgba(0,0,0,.5); font-size: 14px; line-height: 1.45; }
#pop .big { font-size: 28px; line-height: 2.0; }
#pop .big rt { font-size: 13px; }
#pop .row { color: #c7ccd4; }
#pop .lbl { color: #8a8f99; display: inline-block; min-width: 92px; }
#pop .ro2 { font-family: "Segoe UI", sans-serif; }
#pop .note { margin-top: 6px; color: #e6c27a; }
#pop .unk { margin-top: 6px; color: #c9a25a; }
"""

_JS = """
const T = %(tokens)s;
const pop = document.getElementById('pop');
function esc(s) { const d = document.createElement('div'); d.textContent = s ?? ''; return d.innerHTML; }
function setOpt(name, on) {
  document.body.classList.toggle(name === 'furi' ? 'no-furi' : 'no-romaji', !on);
}
function hidePop() {
  pop.style.display = 'none';
  document.querySelectorAll('.w.sel').forEach(e => e.classList.remove('sel'));
}
function showPop(el) {
  const t = T[+el.dataset.i];
  hidePop();
  el.classList.add('sel');
  let rows = '';
  if (t.r && t.r !== t.s) rows += `<div class="row"><span class="lbl">Reading</span>${esc(t.r)}</div>`;
  rows += `<div class="row"><span class="lbl">Romaji</span><span class="ro2">${esc(t.ro)}</span></div>`;
  rows += `<div class="row"><span class="lbl">Word type</span>${esc(t.posEn)}</div>`;
  if (t.base) {
    const br = t.baseR && t.baseR !== t.base ? ` (${esc(t.baseR)})` : '';
    rows += `<div class="row"><span class="lbl">Dictionary form</span>${esc(t.base)}${br}</div>`;
  }
  if (t.conj) rows += `<div class="row"><span class="lbl">Conjugation</span>${esc(t.conj)}</div>`;
  if (t.note) rows += `<div class="note">${esc(t.note)}</div>`;
  if (!t.known) rows += `<div class="unk">Not in the word list — probably a name or a game term. The reading is a guess.</div>`;
  pop.innerHTML = `<div class="big">${el.innerHTML}</div>` + rows;
  pop.style.display = 'block';
  const r = el.getBoundingClientRect(), pw = pop.offsetWidth, ph = pop.offsetHeight;
  let x = Math.min(Math.max(4, r.left), window.innerWidth - pw - 4);
  let y = r.bottom + 6;
  if (y + ph > window.innerHeight - 4) y = Math.max(4, r.top - ph - 6);
  pop.style.left = x + 'px'; pop.style.top = y + 'px';
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


def page_for_tokens(lines: list[list[Token]], font_size: int, furigana: bool,
                    romaji: bool) -> str:
    flat: list[dict] = []
    body = []
    for tokens in lines:
        jp = []
        for tok in tokens:
            jp.append(_token_html(tok, len(flat)))
            flat.append(tok.to_dict())
        body.append(f"<div class='ln'><div class='jp'>{''.join(jp)}</div>"
                    f"<div class='ro'>{_romaji_line(tokens)}</div></div>")
    return _page("".join(body), font_size, flat, furigana, romaji)


def page_for_message(message: str, font_size: int, error: bool = False) -> str:
    cls = "error" if error else "empty"
    return _page(f"<p class='{cls}'>{html.escape(message)}</p>", font_size, [], True, False)


def _page(body: str, font_size: int, tokens: list[dict], furigana: bool, romaji: bool) -> str:
    js = _JS % {
        "tokens": json.dumps(tokens, ensure_ascii=False).replace("</", "<\\/"),
        "furi": "true" if furigana else "false",
        "romaji": "true" if romaji else "false",
    }
    return (
        "<!doctype html><html lang='ja'><head><meta charset='utf-8'><style>"
        + _CSS % {"size": font_size}
        + "</style></head><body>" + body + "<div id='pop'></div><script>" + js
        + "</script></body></html>"
    )
