"""REPORT.html: one self-contained page per run (no external assets) with the review on top and every
passing offer in a table that filters and sorts in the browser.

The review is what the person (or their agent) recorded with `neetscape mark ID STATUS --note ...`: the
latest mark per offer, grouped by status, with its note. Re-run `neetscape report` after marking to
refresh the page.
"""
from __future__ import annotations

import html
import json
from collections import defaultdict

from .details import detail
from .model import age_label, days_old
from .pay import pay_label
from .profile import Profile
from .store import GONE, MARK_STATUSES, Store

_REVIEW_ORDER = [s for s in MARK_STATUSES if s != "ignored"]

_CSS = """
:root{--bg:#fff;--fg:#1d1d1f;--muted:#6e6e73;--line:#e3e3e8;--card:#f6f6f8;--accent:#0b62d6;--warn:#b25000;--ok:#1a7f37}
@media (prefers-color-scheme:dark){:root{--bg:#111214;--fg:#ececf0;--muted:#a0a0a8;--line:#2c2d31;--card:#1b1c1f;
--accent:#6aa7ff;--warn:#ffa257;--ok:#56d364}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}
main{max-width:1200px;margin:0 auto;padding:16px}h1{font-size:22px;margin:4px 0}h2{font-size:17px;margin:28px 0 10px}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}.muted{color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.card .t{font-weight:600}.card .note{margin-top:6px;white-space:pre-wrap}.pill{display:inline-block;padding:0 7px;
border:1px solid var(--line);border-radius:99px;font-size:12px;margin-right:4px}.flag{color:var(--warn)}
table{border-collapse:collapse;width:100%}th,td{padding:5px 6px;border-bottom:1px solid var(--line);text-align:left;
vertical-align:top}th{cursor:pointer;position:sticky;top:0;background:var(--bg);user-select:none;white-space:nowrap}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}.filters input,.filters select{padding:5px 8px;border-radius:7px;
border:1px solid var(--line);background:var(--card);color:var(--fg)}.wrap{overflow-x:auto}td.n{text-align:right;white-space:nowrap}
details summary{cursor:pointer}
"""

_JS = """
const D=JSON.parse(document.getElementById('data').textContent);const T=document.querySelector('#offers tbody');
const q=document.getElementById('q'),fs=document.getElementById('fs'),fm=document.getElementById('fm'),
fn=document.getElementById('fn'),fh=document.getElementById('fh'),cnt=document.getElementById('cnt');let key='score',dir=-1;
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function draw(){const t=q.value.toLowerCase();let r=D.filter(d=>(!t||d.hay.includes(t))&&(!fs.value||d.searches.includes(fs.value))
&&(!fm.value||d.mode===fm.value)&&(!fn.checked||d.new)&&(!fh.checked||!d.mark));
r.sort((a,b)=>{const x=a[key],y=b[key];return (x>y?1:x<y?-1:0)*dir});cnt.textContent=r.length+' / '+D.length;
T.innerHTML=r.slice(0,2000).map(d=>`<tr><td class=n>${d.id}</td><td class=n>${d.score}</td><td>${d.new?'🆕 ':''}<a href="${esc(d.url)}"
target=_blank rel=noopener>${esc(d.title)}</a>${d.tags.map(x=>`<span class="pill${x[0]=='!'?' flag':''}">${esc(x)}</span>`).join('')}
${d.mark?`<span class=pill>${esc(d.mark)}</span>`:''}</td><td>${esc(d.company)}</td><td class=n>${esc(d.pay)}</td><td>${esc(d.mode)}</td>
<td>${esc(d.worktime)}</td><td>${esc(d.contracts)}</td><td>${esc(d.level)}</td><td class=n>${esc(d.age)}</td><td>${esc(d.boards)}</td></tr>`).join('')}
document.querySelectorAll('#offers th').forEach(th=>th.onclick=()=>{const k=th.dataset.k;dir=key===k?-dir:(k==='title'||k==='company'?1:-1);key=k;draw()});
[q,fs,fm,fn,fh].forEach(e=>e.oninput=draw);draw();
"""

_COLS = [("id", "#"), ("score", "score"), ("title", "offer"), ("company", "company"), ("pay_sort", "pay/mo"), ("mode", "mode"),
         ("worktime", "time"), ("contracts", "contract"), ("level", "level"), ("age_days", "age"), ("boards", "boards")]


def _e(s) -> str:
    return html.escape(str(s or ""))


def _href(url: str | None) -> str:
    """Only web links are clickable: a source's `javascript:` or `data:` URL would run in the report's page."""
    return url if (url or "").lower().startswith(("https://", "http://")) else ""


def _posting(det: dict | None) -> str:
    """A marked offer's stored posting (collapsed) with its hints, or why there is none and how to fetch it."""
    if not det or not det["text"] or det["text"].startswith("ERROR"):
        if det and det["status"] in GONE:
            return f'<div class=muted>posting gone (HTTP {det["status"]})</div>'
        why = "not fetched" if not det else {200: "empty", 0: "failed"}.get(det["status"], f"HTTP {det['status']}")
        return f'<div class=muted>posting {why} · <code>neetscape details --marked</code></div>'
    h = det["hints"]
    hints = [x for x in ("fully remote" if h.get("fully_remote") else "", ", ".join(h.get("years") or []),
                         ", ".join(h.get("degree") or []), ", ".join(h.get("languages") or [])) if x]
    return (f'<details><summary>posting ({len(det["text"])} chars{" · " + _e(" · ".join(hints)) if hints else ""})'
            f'</summary><div class=note>{_e(det["text"][:6000])}</div></details>')


def _card(store: Store, m, cur: str) -> str:
    """One mark: the offer (or the bare URL marked from elsewhere), its note and posting."""
    o = store.offer(m["url"])
    facts = f'{_e(pay_label(dict(o)))} {cur}/mo · {_e(o["mode"])} · {_e(o["board"])} · ' if o else ""
    return (f'<div class=card><div class=t><a href="{_e(_href(m["url"]))}" target=_blank rel=noopener>{_e(m["title"] or m["url"])}</a></div>'
            f'<div class=muted>{_e(m["company"]) or "—"} · {facts}since {_e(m["at"][:10])} · listed: {_e(m["listed"])}</div>'
            + (f'<div class=note>{_e(m["note"])}</div>' if m["note"] else "")
            + (_posting(detail(store, o["id"])) if o else "") + "</div>")


def _review(store: Store, run_id: int, cur: str) -> str:
    """The latest mark per offer, grouped by status (rejected collapsed, ignored left out)."""
    by: dict[str, list] = defaultdict(list)
    for m in store.tracked(run_id):
        by[m["status"]].append(m)
    if not by:
        return ('<p class=muted>No review yet. Record decisions with <code>neetscape mark ID shortlisted --note "why · risk"</code>'
                " and run <code>neetscape report</code> again.</p>")
    out = []
    for status in _REVIEW_ORDER:
        marks = by.get(status)
        if not marks:
            continue
        head, cards = f"{_e(status)} ({len(marks)})", "".join(_card(store, m, cur) for m in marks)
        out.append(f"<details><summary>{head}</summary><div class=cards>{cards}</div></details>" if status == "rejected"
                   else f"<h3>{head}</h3><div class=cards>{cards}</div>")
    return "".join(out)


def _boards(store: Store, run_id: int) -> str:
    body = "".join(f"<tr><td>{_e(r['board'])}</td><td class=n>{r['n']}</td><td class=n>{r['pages']}</td><td class=n>{r['found']}</td>"
                   f"<td class=n>{r['complete']}/{r['n']}</td><td class=n{' style=color:var(--warn)' if r['errors'] else ''}>"
                   f"{r['errors'] or 0}</td></tr>" for r in store.board_stats(run_id))
    return ("<details><summary>Boards in this run</summary><table><tr><th>board</th><th>requests</th><th>pages</th>"
            f"<th>offers</th><th>complete</th><th>errors</th></tr>{body}</table></details>")


def _data(rows: list[dict]) -> list[dict]:
    out = []
    for d in rows:
        days = days_old(d["published"])
        v = {"id": d["id"], "score": d["score"], "new": bool(d["is_new"]), "title": d["title"], "company": d["company"] or "",
             "pay": pay_label(d), "pay_sort": d["pay_max"] or 0, "mode": d["mode"], "worktime": d["worktime"],
             "contracts": d["contracts"] or "", "level": d["level"], "age": age_label(d["published"]),
             "age_days": 9999 if days is None else days, "boards": d["boards"] or d["board"], "searches": d["searches"],
             "tags": d["tags"], "mark": d["mark"] or "", "url": _href(d["url"])}
        v["hay"] = " ".join(str(v[k]) for k in ("title", "company", "boards", "contracts")).lower() + " " + " ".join(d["why"]).lower()
        out.append(v)
    return out


def _script_json(value) -> str:
    """JSON safe inside <script>: no `<` at all, so neither `</script>` nor `<!--` can end or reshape the block."""
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")


def write_html(store: Store, profile: Profile, run_id: int, rows: list[dict], path) -> None:
    run = store.run(run_id)
    cur = profile.currency
    label = profile.raw.get("label") or "neetscape"
    data = _script_json(_data(rows))
    searches = "".join(f'<option value="{_e(s.id)}">{_e(s.label)}</option>' for s in profile.searches)
    head = "".join(f'<th data-k="{k}">{_e(t if k != "pay_sort" else f"pay {cur}/mo")}</th>' for k, t in _COLS)
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>neetscape run {run_id}</title><style>{_CSS}</style></head><body><main>
<h1>{_e(label)}</h1><div class=muted>run {run_id} · {_e(run['started_at'][:16])} · {len(rows)} offers pass the profile
({sum(d['is_new'] for d in rows)} new)</div>
<h2>Review</h2>{_review(store, run_id, cur)}
<h2>All passing offers</h2>{_boards(store, run_id)}
<div class=filters><input id=q placeholder="filter: title, company, board, rule…" size=34>
<select id=fs><option value="">all searches</option>{searches}</select>
<select id=fm><option value="">any mode</option><option>remote</option><option>hybrid</option><option>onsite</option><option>unknown</option></select>
<label><input type=checkbox id=fn> new only</label><label><input type=checkbox id=fh> hide marked</label>
<span id=cnt class=muted></span></div>
<div class=wrap><table id=offers><thead><tr>{head}</tr></thead><tbody></tbody></table></div>
<p class=muted>Click a column to sort. Offers marked rejected/ignored are not listed. Generated by neetscape.</p>
</main><script type="application/json" id=data>{data}</script><script>{_JS}</script></body></html>"""
    path.write_text(page)
