"""REPORT.html: one self-contained page per run (no external assets) for reviewing offers, laid out like a mail
client: a quiet list on the left (title, company, pay, age, a work-mode dot, the number of red flags), the
selected offer on the right (facts, the posting's red flags, the review note, the full posting, actions).

One embedded JSON document holds every offer passing the profile plus every marked offer (the review,
recorded with `neetscape mark ID STATUS --note ...`). Tabs: Review (marked) / All. The list groups by note
category (the first line of a multi-line note), status, tag, search, board or work mode, and sorts by
score, pay, date or company; the rest of the filters sit behind one "Filters" button. Keys: `j`/`k` (or
arrows) move, `o` opens the offer, `x` ticks it off, `/` searches. Ticks are a per-browser convenience
(localStorage); decisions are recorded with the `mark` command the page copies. `#review` / `#all` in the
URL pick the tab. Re-run `neetscape report` after marking.
"""
from __future__ import annotations

import html
import json

from .details import detail
from .model import age_label, days_old
from .pay import pay_label
from .profile import Profile
from .store import GONE, MARK_STATUSES, Store

_POSTING_CHARS = 8000
_LANG = {"pl": "pl", "de": "de"}  # page language by profile country; English otherwise (switchable in the page)

_CSS = r"""
:root{--bg:#fafafa;--fg:#1c1c1e;--muted:#74747c;--line:#e7e7ec;--panel:#fff;--sel:#edf3ff;--accent:#0a60d0;
--ok:#1b7f3a;--warn:#a34c00;--warnbg:#fff3e6;--bad:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#0e0f11;--fg:#e9e9ee;--muted:#8d8d96;--line:#24252a;--panel:#15161a;--sel:#1a2537;
--accent:#6ea8ff;--ok:#58d26c;--warn:#ffab5e;--warnbg:#33230f;--bad:#ff7b72}}
*{box-sizing:border-box}html,body{height:100%}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;display:flex;flex-direction:column}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}.muted{color:var(--muted)}
button,select,input{font:inherit;color:var(--fg)}kbd{font:11px ui-monospace,monospace;border:1px solid var(--line);border-radius:4px;padding:0 4px;color:var(--muted)}
header{height:52px;padding:0 16px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:center}
header h1{font-size:15px;margin:0;font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:260px}
.tabs{display:inline-flex;background:var(--line);border-radius:8px;padding:2px;flex:none}.tabs button{border:0;background:none;
font-size:13px;padding:4px 12px;border-radius:6px;cursor:pointer;white-space:nowrap}.tabs button.on{background:var(--panel);box-shadow:0 1px 2px #0002}
.tabs .n{color:var(--muted);margin-left:4px}
#q{flex:1;min-width:120px;max-width:420px;font-size:13px;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--panel)}
.tray{display:flex;gap:4px;align-items:center}.tray[hidden]{display:none}.tray button{font-size:13px;padding:5px 10px;border-radius:8px;
border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer;white-space:nowrap}.tray .x{background:none;color:var(--muted);border-color:var(--line)}
.view{margin-left:auto;position:relative}.view>summary{list-style:none;cursor:pointer;font-size:13px;padding:6px 11px;border:1px solid var(--line);
border-radius:8px;background:var(--panel);white-space:nowrap}.view>summary::-webkit-details-marker{display:none}
.view[open]>div{position:absolute;right:0;top:38px;z-index:9;background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:14px;display:grid;gap:10px;width:270px;box-shadow:0 10px 30px #0003}
.view select{width:100%;font-size:13px;padding:6px 8px;border:1px solid var(--line);border-radius:8px;background:var(--panel)}
.view label{display:flex;gap:8px;align-items:center;font-size:13px}.view hr{border:0;border-top:1px solid var(--line);margin:2px 0}
.view .help{font-size:12px;color:var(--muted);line-height:1.7}
.app{flex:1;display:grid;grid-template-columns:minmax(300px,380px) 1fr;min-height:0}
#list{overflow:auto;border-right:1px solid var(--line)}#detail{overflow:auto}
.lc{font-size:12px;color:var(--muted);padding:8px 16px 0}
.gh{position:sticky;top:0;z-index:1;background:var(--bg);font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);
padding:12px 16px 5px;display:flex;justify-content:space-between;cursor:pointer;user-select:none}
.row{padding:10px 16px;border-bottom:1px solid var(--line);cursor:pointer;display:grid;grid-template-columns:1fr auto;gap:3px 10px}
.row:hover{background:var(--panel)}.row.sel{background:var(--sel);box-shadow:inset 3px 0 var(--accent)}
.row .t{font-weight:550;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.row .s{font-size:12px;color:var(--muted);
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.row .p{font-size:12px;text-align:right;white-space:nowrap;color:var(--muted)}
.row .p.pay{color:var(--fg);font-weight:550}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;vertical-align:1px;background:var(--muted)}
.dot.remote{background:var(--ok)}.dot.hybrid{background:var(--warn)}.dot.onsite{background:var(--bad)}
.flagn{color:var(--warn)}.badge{font-size:11px;margin-left:6px;color:var(--accent)}.badge.rejected,.badge.ignored{color:var(--muted)}
.more{display:block;width:100%;padding:12px;border:0;background:none;color:var(--accent);cursor:pointer}
.bar{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:8px 28px;display:flex;gap:6px;align-items:center}
.bar button{border:1px solid var(--line);background:var(--panel);border-radius:7px;padding:3px 9px;cursor:pointer;font-size:13px}
.bar .pos{font-size:12px;color:var(--muted);margin:0 6px}.bar .sp{flex:1}
.bar .d{border:0;background:none;color:var(--muted);padding:3px 7px}.bar .d:hover{color:var(--fg)}.bar .d.on{color:var(--accent);font-weight:600}
#back{display:none}
.doc{padding:22px 28px 60px;max-width:860px}
.head{display:flex;gap:16px;align-items:baseline;justify-content:space-between}.head h2{font-size:21px;line-height:1.3;margin:0}
.head .pay{font-size:17px;font-weight:650;white-space:nowrap}.co{color:var(--muted);margin:4px 0 10px}
.line{font-size:13px;color:var(--muted);margin-bottom:14px}.line b{color:var(--fg);font-weight:550}
.flags{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}.flag{background:var(--warnbg);color:var(--warn);border-radius:6px;padding:2px 8px;font-size:12px}
.flag.good{background:none;color:var(--ok);border:1px solid var(--line)}
.note{white-space:pre-wrap;border-left:3px solid var(--accent);padding:2px 0 2px 12px;margin:0 0 16px}.note .y{color:var(--ok)}.note .r{color:var(--warn)}
.open{display:inline-block;background:var(--accent);color:#fff!important;border-radius:8px;padding:6px 14px;margin:0 0 18px;font-size:13px}
#note{width:100%;min-height:52px;font-size:13px;padding:8px 10px;border-radius:8px;border:1px solid var(--line);background:var(--panel);margin:0 0 18px;resize:vertical}
.posting{border-top:1px solid var(--line);padding-top:16px;font-size:15px;line-height:1.65;max-width:72ch}
.posting h4{font-size:15px;margin:20px 0 6px;font-weight:650}.posting h4:first-child{margin-top:0}.posting p{margin:0 0 10px}
.posting ul{margin:0 0 12px;padding-left:20px}.posting li{margin:3px 0}
.empty{color:var(--muted);padding:40px 16px;text-align:center}
#toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:var(--fg);color:var(--bg);padding:7px 13px;border-radius:8px;
font-size:13px;opacity:0;transition:opacity .2s;pointer-events:none}
@media (max-width:820px){header{gap:8px;padding:0 10px}header h1{display:none}.app{grid-template-columns:1fr}#list{border-right:0}
#detail{display:none;position:fixed;inset:0;background:var(--bg);z-index:20}body.reading #detail{display:block}#back{display:inline-block}
.bar{padding:8px 14px}.doc{padding:16px 16px 50px}.tabs .n{display:none}}
"""

_JS = r"""
const M=JSON.parse(document.getElementById('meta').textContent),D=JSON.parse(document.getElementById('data').textContent);
const T={
en:{review:'Review',all:'All',search:'Search  /',g_auto:'Group: auto',g_category:'Group: note category',g_status:'Group: status',g_tag:'Group: tag',
 g_search:'Group: search',g_board:'Group: board',g_mode:'Group: work mode',g_none:'No groups',s_score:'Sort: score',s_pay:'Sort: pay',s_newest:'Sort: newest',
 s_company:'Sort: company',filters:'Filters',any_mode:'Any work mode',any_board:'Any board',f_new:'New in this run',f_posted:'With posting',
 f_unreviewed:'Not decided',f_hide:'Hide decided',remote_only:'Remote only',keys:'j/k move · o open · s/a/r/i decide · u undo · n note · / search',
 empty:'Nothing here. Clear the filters.',empty_review:'No review yet: decide in "All" or record one with neetscape mark.',select:'Select an offer.',
 pay:'pay / month',mode:'mode',time:'time',contract:'contract',level:'level',posted:'posted',on:'on',score:'score',ago:'ago',fully_remote:'fully remote',
 open:'Open offer ↗',back:'← list',note_ph:'Note: why · risk (saved with the decision)',copy:n=>`Copy ${n} command${n==1?'':'s'}`,clear:'Clear',
 copied:n=>`Copied ${n} command${n==1?'':'s'}: paste them in the terminal`,confirm_clear:'Forget the decisions made on this page?',
 decided:(a,b)=>`${a} / ${b} decided`,more:n=>`Show more (${n} left)`,offers:'offers',new:'new',errors:'board errors',cut:'cut listings',
 p_none:'Posting not fetched',p_empty:'Posting is empty',p_failed:'Fetching the posting failed',p_gone:'Offer removed',p_http:'Posting unavailable',
 other:'other',no_tag:'no tag',not_reviewed:'not reviewed',
 st:{shortlisted:'shortlisted',applied:'applied',interview:'interview',offer:'offer',rejected:'rejected',ignored:'ignored'},
 md:{remote:'remote',hybrid:'hybrid',onsite:'on-site',unknown:'unknown'},wt:{full_time:'full time',part_time:'part time',flexible:'flexible'}},
de:{review:'Auswahl',all:'Alle',search:'Suchen  /',g_auto:'Gruppe: automatisch',g_category:'Gruppe: Notiz-Kategorie',g_status:'Gruppe: Status',g_tag:'Gruppe: Tag',
 g_search:'Gruppe: Suche',g_board:'Gruppe: Börse',g_mode:'Gruppe: Arbeitsort',g_none:'Keine Gruppen',s_score:'Sortierung: Punkte',s_pay:'Sortierung: Gehalt',
 s_newest:'Sortierung: neueste',s_company:'Sortierung: Firma',filters:'Filter',any_mode:'Jeder Arbeitsort',any_board:'Jede Börse',f_new:'Neu in diesem Lauf',
 f_posted:'Mit Anzeigentext',f_unreviewed:'Nicht entschieden',f_hide:'Entschiedene ausblenden',remote_only:'Nur remote',
 keys:'j/k bewegen · o öffnen · s/a/r/i entscheiden · u rückgängig · n Notiz · / suchen',empty:'Nichts gefunden. Filter zurücksetzen.',
 empty_review:'Noch keine Auswahl: in „Alle“ entscheiden oder mit neetscape mark festhalten.',select:'Angebot auswählen.',
 pay:'Gehalt / Monat',mode:'Arbeitsort',time:'Umfang',contract:'Vertrag',level:'Level',posted:'veröffentlicht',on:'auf',score:'Punkte',ago:'her',
 fully_remote:'voll remote',open:'Angebot öffnen ↗',back:'← Liste',note_ph:'Notiz: warum · Risiko (wird mit der Entscheidung gespeichert)',
 copy:n=>`${n} Befehl${n==1?'':'e'} kopieren`,clear:'Leeren',copied:n=>`${n} Befehl${n==1?'':'e'} kopiert: im Terminal einfügen`,
 confirm_clear:'Die Entscheidungen auf dieser Seite verwerfen?',decided:(a,b)=>`${a} / ${b} entschieden`,more:n=>`Mehr zeigen (${n} übrig)`,
 offers:'Angebote',new:'neu',errors:'Börsenfehler',cut:'abgeschnittene Listen',p_none:'Anzeigentext nicht geladen',p_empty:'Anzeigentext leer',p_failed:'Laden des Anzeigentexts fehlgeschlagen',
 p_gone:'Angebot entfernt',p_http:'Anzeigentext nicht verfügbar',other:'sonstige',no_tag:'ohne Tag',not_reviewed:'nicht geprüft',
 st:{shortlisted:'vorgemerkt',applied:'beworben',interview:'Gespräch',offer:'Zusage',rejected:'abgelehnt',ignored:'ignoriert'},
 md:{remote:'remote',hybrid:'hybrid',onsite:'vor Ort',unknown:'unbekannt'},wt:{full_time:'Vollzeit',part_time:'Teilzeit',flexible:'flexibel'}},
pl:{review:'Przegląd',all:'Wszystkie',search:'Szukaj  /',g_auto:'Grupy: auto',g_category:'Grupy: kategoria notatki',g_status:'Grupy: status',g_tag:'Grupy: tag',
 g_search:'Grupy: wyszukiwanie',g_board:'Grupy: portal',g_mode:'Grupy: tryb pracy',g_none:'Bez grup',s_score:'Sortuj: wynik',s_pay:'Sortuj: stawka',
 s_newest:'Sortuj: najnowsze',s_company:'Sortuj: firma',filters:'Filtry',any_mode:'Każdy tryb pracy',any_board:'Każdy portal',f_new:'Nowe w tym przebiegu',
 f_posted:'Z opisem',f_unreviewed:'Bez decyzji',f_hide:'Ukryj zdecydowane',remote_only:'Tylko zdalne',
 keys:'j/k ruch · o otwórz · s/a/r/i decyzja · u cofnij · n notatka · / szukaj',empty:'Nic tu nie ma. Wyczyść filtry.',
 empty_review:'Brak przeglądu: zdecyduj w „Wszystkie” albo zapisz przez neetscape mark.',select:'Wybierz ofertę.',
 pay:'stawka / mies.',mode:'tryb',time:'wymiar',contract:'umowa',level:'poziom',posted:'dodana',on:'na',score:'wynik',ago:'temu',fully_remote:'w pełni zdalna',
 open:'Otwórz ofertę ↗',back:'← lista',note_ph:'Notatka: dlaczego · ryzyko (zapisywana z decyzją)',copy:n=>`Kopiuj komendy (${n})`,clear:'Wyczyść',
 copied:n=>`Skopiowano ${n}: wklej w terminalu`,confirm_clear:'Zapomnieć decyzje podjęte na tej stronie?',decided:(a,b)=>`${a} / ${b} z decyzją`,
 more:n=>`Pokaż więcej (zostało ${n})`,offers:'ofert',new:'nowych',errors:'błędów portali',cut:'uciętych list',p_none:'Opis niepobrany',p_empty:'Opis pusty',
 p_failed:'Nie udało się pobrać opisu',p_gone:'Oferta usunięta',p_http:'Opis niedostępny',other:'inne',no_tag:'bez tagu',not_reviewed:'nieprzejrzane',
 st:{shortlisted:'na liście',applied:'aplikowano',interview:'rozmowa',offer:'oferta',rejected:'odrzucone',ignored:'pominięte'},
 md:{remote:'zdalna',hybrid:'hybrydowa',onsite:'stacjonarna',unknown:'nieznany'},wt:{full_time:'pełny etat',part_time:'część etatu',flexible:'elastyczny'}}};

const X={en:{view:'View',prev:'Previous (k)',next:'Next (j)',shown:(a,b)=>`${a} of ${b}`,lang:'Language'},
 de:{view:'Ansicht',prev:'Zurück (k)',next:'Weiter (j)',shown:(a,b)=>`${a} von ${b}`,lang:'Sprache'},
 pl:{view:'Widok',prev:'Poprzednia (k)',next:'Następna (j)',shown:(a,b)=>`${a} z ${b}`,lang:'Język'}};
for(const k in X)Object.assign(T[k],X[k]);
const $=id=>document.getElementById(id),L=$('list'),P=$('detail');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const load=(k,v)=>{try{return JSON.parse(localStorage.getItem(M.key+k))??v}catch(e){return v}};
const keep=(k,v)=>{try{localStorage.setItem(M.key+k,JSON.stringify(v))}catch(e){}};
let lang=new URLSearchParams(location.search).get('lang')||load('-lang',M.lang);if(!T[lang])lang='en';let t=T[lang];
const dec=load('-dec',{}),ui=load('-ui',{}),hv=location.hash.slice(1);
const S={view:['review','all'].includes(hv)?hv:ui.view||(D.some(d=>d.mark)?'review':'all'),group:'auto',sort:'score',limit:200,sel:ui.sel??null,closed:{}};
const DECIDE={s:'shortlisted',a:'applied',r:'rejected',i:'ignored'},MODES=['remote','hybrid','onsite','unknown'];
const SORT={score:(a,b)=>(b.score??-1e9)-(a.score??-1e9)||b.pay_sort-a.pay_sort,pay:(a,b)=>b.pay_sort-a.pay_sort,
 newest:(a,b)=>a.age_days-b.age_days,company:(a,b)=>a.company.localeCompare(b.company)};
const status=d=>dec[d.id]?.s||d.mark||'',st=s=>t.st[s]||s;
const flags=d=>{const h=d.hints||{};return[...(h.years||[]),...(h.degree||[]),...(h.languages||[]),...(h.hybrid||[]).slice(0,1)]};
const payTxt=d=>d.pay==='—'?'':d.pay+(d.pay_sort?' '+M.currency:'');
function i18n(){document.documentElement.lang=lang;document.querySelectorAll('[data-t]').forEach(e=>{e.textContent=t[e.dataset.t]});
 $('q').placeholder=t.search;$('mode').querySelectorAll('option').forEach(o=>{o.textContent=o.value?(t.md[o.value]||o.value):t.any_mode});
 $('stats').textContent=`${M.n_rows} ${t.offers} · ${M.n_new} ${t.new}`+(M.errors?` · ${M.errors} ${t.errors}`:'')+(M.cut?` · ${M.cut} ${t.cut}`:'');$('lang').value=lang}
function keyOf(d,g){switch(g){case'category':return d.category||t.other;case'status':return status(d)?st(status(d)):t.not_reviewed;
 case'tag':return M.tags[d.tags[0]]||d.tags[0]||t.no_tag;case'search':return M.searches[d.searches[0]]||d.searches[0]||'—';
 case'board':return d.boards.split(',')[0];case'mode':return t.md[d.mode]||d.mode;default:return''}}
function rank(g,k){if(g==='status'){const i=[...M.statuses.map(st),t.not_reviewed].indexOf(k);return i<0?99:i}
 if(g==='mode')return MODES.map(m=>t.md[m]).indexOf(k);
 if(g==='category'){let m=1e15;for(const d of D)if(d.category===k)m=Math.min(m,d.marked_at);return m}return 0}
const inView=d=>S.view==='review'?(d.mark||dec[d.id]):d.listed;
function visible(){const q=$('q').value.toLowerCase().trim(),mode=$('remote').checked?'remote':$('mode').value,board=$('board').value;
 return D.filter(d=>inView(d)&&(!q||d.hay.includes(q)||(dec[d.id]?.n||'').toLowerCase().includes(q))&&(!mode||d.mode===mode)&&
  (!board||d.boards.split(',').includes(board))&&(!$('new').checked||d.new)&&(!$('posted').checked||d.posting)&&
  (!$('hide').checked||!dec[d.id])&&(!$('unmarked').checked||!status(d))).sort(SORT[S.sort])}
function group(){return S.group!=='auto'?S.group:S.view==='review'?(D.some(d=>d.category)?'category':'status'):'none'}
function row(d){const f=flags(d).length,s=status(d);return `<div class="row${d.id===S.sel?' sel':''}" data-id="${d.id}">
<div class=t>${esc(d.title)}</div><div class="p pay">${esc(payTxt(d))}</div>
<div class=s><span class="dot ${esc(d.mode)}"></span>${esc(d.company||'—')} · ${esc(d.age)}${dec[d.id]?`<span class="badge ${esc(s)}">${esc(st(s))}</span>`:''}</div>
<div class=p>${f?`<span class=flagn>⚠ ${f}</span>`:''}</div></div>`}
let shown=[];
function tray(){const n=Object.keys(dec).length;$('tray').hidden=!n;$('copy').textContent=t.copy(n)}
function drawList(){const r=visible(),g=group(),total=D.filter(inView).length;
 const ac=['new','posted','hide','unmarked','remote'].filter(id=>$(id).checked).length+($('mode').value?1:0)+($('board').value?1:0);
 $('vlabel').textContent='⚙ '+t.view+(ac?` · ${ac}`:'');
 const groups=new Map();for(const d of r.slice(0,g==='none'?S.limit:r.length)){const k=keyOf(d,g);if(!groups.has(k))groups.set(k,[]);groups.get(k).push(d)}
 const keys=[...groups.keys()].sort((a,b)=>rank(g,a)-rank(g,b)||a.localeCompare(b));shown=[];
 let h=r.length<total?`<div class=lc>${t.shown(r.length,total)}</div>`:'';
 for(const k of keys){const items=groups.get(k);if(g!=='none')h+=`<div class=gh data-g="${esc(k)}"><span>${S.closed[k]?'▸':'▾'} ${esc(k)}</span><span>${items.length}</span></div>`;
  if(!S.closed[k]){h+=items.map(row).join('');shown.push(...items)}}
 if(g==='none'&&r.length>S.limit)h+=`<button class=more id=more>${t.more(r.length-S.limit)}</button>`;
 L.innerHTML=shown.length||h?h:`<div class=empty>${S.view==='review'?t.empty_review:t.empty}</div>`;
 document.querySelectorAll('.tabs button').forEach(b=>b.classList.toggle('on',b.dataset.v===S.view));tray();
 if(!shown.some(d=>d.id===S.sel))select(shown[0]?.id??null,false);else drawDetail()}
function noteHtml(d){const ls=String(d.note).split('\n');if(d.category&&ls[0].trim()===d.category)ls.shift();
 return esc(ls.join('\n')).split('\n').map(l=>/^\s*(✅|\+)/.test(l)?`<span class=y>${l}</span>`:/^\s*(⚠|!)/.test(l)?`<span class=r>${l}</span>`:l).join('\n')}
function fmtPosting(text){const ls=text.split('\n').map(l=>l.trim()).filter(Boolean);let h='',ul=false;
 const close=()=>{if(ul){h+='</ul>';ul=false}};
 ls.forEach((l,i)=>{const bullet=/^[•·▪◦\-–*✓✔➤►]\s*/.test(l);
  if(bullet){if(!ul){h+='<ul>';ul=true}h+=`<li>${esc(l.replace(/^[•·▪◦\-–*✓✔➤►]\s*/,''))}</li>`;return}close();
  const next=ls[i+1]||'';const heading=l.length<=60&&!/[.,;]$/.test(l)&&(/:$/.test(l)||/^[•·▪◦\-–*✓✔➤►]/.test(next)||next.length>l.length*1.5);
  h+=heading?`<h4>${esc(l.replace(/:$/,''))}</h4>`:`<p>${esc(l)}</p>`});close();return h}
function postingState(d){const s=d.posting_state;return s==='not fetched'?t.p_none:s==='empty'?t.p_empty:s==='failed'?t.p_failed:s.startsWith('gone')?t.p_gone:t.p_http}
function drawDetail(){const d=D.find(x=>x.id===S.sel);if(!d){P.innerHTML=`<div class=empty>${t.select}</div>`;return}
 const i=shown.findIndex(x=>x.id===d.id),h=d.hints||{},cur=dec[d.id]?.s;
 const facts=[t.md[d.mode]||d.mode,t.wt[d.worktime],d.contracts&&d.contracts.replace(/,/g,', '),d.level!=='unknown'&&d.level,
  d.age!=='?'&&`${d.age} ${t.ago}`,d.boards.replace(/,/g,', ')].filter(Boolean);
 const decs=Object.entries(DECIDE).map(([k,s])=>`<button class="d${cur===s?' on':''}" data-dec="${s}" title="${k}">${esc(st(s))}</button>`).join('');
 P.innerHTML=`<div class=bar><button id=back>${t.back}</button><button id=prev title="${esc(t.prev)}">↑</button><button id=next title="${esc(t.next)}">↓</button>
 <span class=pos>${i+1} / ${shown.length}</span><span class=sp></span>${decs}</div><div class=doc>
 <div class=head><h2>${esc(d.title)}</h2>${payTxt(d)?`<span class=pay>${esc(payTxt(d))}</span>`:''}</div>
 <div class=co>${esc(d.company||'—')}${d.mark?` · ${esc(st(d.mark))}`:''}</div>
 <div class=line>${facts.map(esc).join(' · ')}</div>
 ${flags(d).length||h.fully_remote?`<div class=flags>${h.fully_remote?`<span class="flag good">${t.fully_remote}</span>`:''}${flags(d).map(f=>`<span class=flag>${esc(f)}</span>`).join('')}</div>`:''}
 ${d.note?`<div class=note>${noteHtml(d)}</div>`:''}
 ${d.url?`<a class=open href="${esc(d.url)}" target=_blank rel=noopener>${t.open}</a>`:''}
 ${cur?`<textarea id=note placeholder="${esc(t.note_ph)}">${esc(dec[d.id].n??'')}</textarea>`:''}
 ${d.posting?`<div class=posting>${fmtPosting(d.posting)}</div>`:`<div class=muted>${postingState(d)}${d.posting_state==='not fetched'?` — <code>neetscape details --pick ${d.id}</code>`:''}</div>`}</div>`}
function select(id,scroll=true){S.sel=id;keep('-ui',{view:S.view,sel:id});document.querySelectorAll('.row').forEach(r=>r.classList.toggle('sel',+r.dataset.id===id));
 if(scroll){const r=L.querySelector(`.row[data-id="${id}"]`);if(r)r.scrollIntoView({block:'nearest'})}drawDetail();P.scrollTop=0}
function step(n){const i=shown.findIndex(d=>d.id===S.sel);const d=shown[i+n];if(d)select(d.id)}
function redrawRow(id){const r=L.querySelector(`.row[data-id="${id}"]`),d=D.find(x=>x.id===id);if(r&&d)r.outerHTML=row(d)}
function decide(s){if(S.sel==null)return;const id=S.sel,old=dec[id];
 if(!s||old?.s===s)delete dec[id];else dec[id]={s,n:old?.n??''};keep('-dec',dec);redrawRow(id);tray();drawDetail()}
const quote=s=>"'"+String(s).replace(/'/g,"'\\''")+"'";
async function copyAll(){const ids=Object.keys(dec);if(!ids.length)return;
 const cmd=ids.map(id=>`neetscape mark ${id} ${dec[id].s}`+(dec[id].n?` --note ${quote(dec[id].n)}`:'')).concat(['neetscape report']).join('\n');
 try{await navigator.clipboard.writeText(cmd);toast(t.copied(ids.length))}catch(e){prompt('',cmd)}}
function toast(x){const e=$('toast');e.textContent=x;e.style.opacity=1;clearTimeout(toast.t);toast.t=setTimeout(()=>e.style.opacity=0,2200)}
L.addEventListener('click',e=>{const g=e.target.closest('.gh');if(g){S.closed[g.dataset.g]=!S.closed[g.dataset.g];drawList();return}
 if(e.target.id==='more'){S.limit+=200;drawList();return}const r=e.target.closest('.row');if(r){select(+r.dataset.id,false);document.body.classList.add('reading')}});
P.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.dec)decide(b.dataset.dec);
 else if(b.id==='back')document.body.classList.remove('reading');else if(b.id==='prev')step(-1);else if(b.id==='next')step(1)});
P.addEventListener('input',e=>{if(e.target.id!=='note'||!dec[S.sel])return;dec[S.sel].n=e.target.value;keep('-dec',dec)});
$('copy').onclick=copyAll;$('clear').onclick=()=>{if(confirm(t.confirm_clear)){for(const k in dec)delete dec[k];keep('-dec',dec);drawList()}};
document.querySelector('.tabs').addEventListener('click',e=>{const b=e.target.closest('button');if(b){S.view=b.dataset.v;S.limit=200;
 history.replaceState(null,'',location.search+'#'+S.view);keep('-ui',{view:S.view,sel:S.sel});drawList()}});
['q','mode','board','new','posted','hide','unmarked','remote'].forEach(id=>$(id).addEventListener('input',()=>{S.limit=200;drawList()}));
$('group').addEventListener('input',e=>{S.group=e.target.value;S.closed={};drawList()});$('sort').addEventListener('input',e=>{S.sort=e.target.value;drawList()});
$('lang').addEventListener('input',e=>{lang=e.target.value;t=T[lang];keep('-lang',lang);i18n();drawList()});
document.addEventListener('keydown',e=>{if(e.target.matches('input,select,textarea')){if(e.key==='Escape')e.target.blur();return}
 if(e.ctrlKey||e.metaKey||e.altKey)return;
 if(e.key==='/'){e.preventDefault();$('q').focus()}else if(e.key==='j'||e.key==='ArrowDown'){e.preventDefault();step(1)}
 else if(e.key==='k'||e.key==='ArrowUp'){e.preventDefault();step(-1)}
 else if(e.key==='o'){const d=D.find(x=>x.id===S.sel);if(d&&d.url)window.open(d.url,'_blank','noopener')}
 else if(DECIDE[e.key])decide(DECIDE[e.key]);else if(e.key==='u')decide(null);
 else if(e.key==='n'&&$('note')){e.preventDefault();$('note').focus()}});
i18n();drawList();
"""

_PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>neetscape run {run_id}</title><style>{css}</style></head><body>
<header><h1 title="run {run_id} · {started}">{label}</h1>
<div class=tabs><button data-v=review><span data-t=review></span><span class=n>{n_marked}</span></button><button data-v=all><span data-t=all></span><span class=n>{n_rows}</span></button></div>
<input type=search id=q>
<div class=tray id=tray hidden><button id=copy></button><button id=clear class=x title="clear">×</button></div>
<details class=view><summary id=vlabel></summary><div>
<div class=help id=stats></div>
<select id=group><option value=auto data-t=g_auto></option><option value=category data-t=g_category></option><option value=status data-t=g_status></option>
<option value=tag data-t=g_tag></option><option value=search data-t=g_search></option><option value=board data-t=g_board></option>
<option value=mode data-t=g_mode></option><option value=none data-t=g_none></option></select>
<select id=sort><option value=score data-t=s_score></option><option value=pay data-t=s_pay></option><option value=newest data-t=s_newest></option>
<option value=company data-t=s_company></option></select><hr>
<label><input type=checkbox id=remote><span data-t=remote_only></span></label>
<select id=mode><option value=""></option>{modes}</select><select id=board><option value="" data-t=any_board></option>{boards}</select>
<label><input type=checkbox id=new><span data-t=f_new></span></label><label><input type=checkbox id=posted><span data-t=f_posted></span></label>
<label><input type=checkbox id=unmarked><span data-t=f_unreviewed></span></label><label><input type=checkbox id=hide><span data-t=f_hide></span></label><hr>
<select id=lang><option value=en>English</option><option value=de>Deutsch</option><option value=pl>Polski</option></select>
<div class=help data-t=keys></div></div></details>
</header>
<div class=app><div id=list></div><div id=detail></div></div><div id=toast></div>
<script type="application/json" id=meta>{meta}</script>
<script type="application/json" id=data>{data}</script><script>{js}</script></body></html>"""


def _e(s) -> str:
    return html.escape(str(s or ""))


def _href(url: str | None) -> str:
    """Only web links are clickable: a source's `javascript:` or `data:` URL would run in the report's page."""
    return url if (url or "").lower().startswith(("https://", "http://")) else ""


def _posting(det: dict | None) -> tuple[str, str, dict]:
    """(text, state, hints) of an offer's stored posting; state says why there is no text."""
    if det and det["text"] and not det["text"].startswith("ERROR"):
        return det["text"][:_POSTING_CHARS], "fetched", det["hints"]
    if det and det["status"] in GONE:
        return "", f"gone (HTTP {det['status']})", {}
    return "", "not fetched" if not det else {200: "empty", 0: "failed"}.get(det["status"], f"HTTP {det['status']}"), {}


def _category(note: str) -> str:
    """A multi-line note's first line names its category ("Main job", "Side jobs", "Stretch"...)."""
    lines = [x.strip() for x in (note or "").splitlines() if x.strip()]
    return lines[0][:60] if len(lines) > 1 else ""


def _item(d: dict, listed: bool, mark=None, det: dict | None = None) -> dict:
    days = days_old(d.get("published"))
    text, state, hints = _posting(det)
    v = {"id": d["id"], "score": d.get("score"), "new": bool(d.get("is_new")), "title": d.get("title") or d.get("url") or "",
         "company": d.get("company") or "", "pay": pay_label(d), "pay_sort": d.get("pay_max") or 0, "mode": d.get("mode") or "unknown",
         "worktime": d.get("worktime") or "unknown", "contracts": d.get("contracts") or "", "level": d.get("level") or "unknown",
         "age": age_label(d.get("published")), "age_days": 9999 if days is None else days,
         "boards": d.get("boards") or d.get("board") or "", "searches": d.get("searches") or [], "tags": d.get("tags") or [],
         "url": _href(d.get("url")), "listed": listed, "posting": text, "posting_state": state, "hints": hints,
         "mark": mark["status"] if mark else (d.get("mark") or ""), "note": (mark["note"] or "") if mark else "",
         "category": _category(mark["note"]) if mark else "", "marked_at": mark["id"] if mark else 0}
    v["hay"] = " ".join(str(x) for x in (v["title"], v["company"], v["boards"], v["contracts"], v["note"],
                                         " ".join(d.get("why") or []))).lower()
    return v


def _data(store: Store, run_id: int, rows: list[dict]) -> list[dict]:
    """Every listed offer plus every marked one (rejected and marked-elsewhere offers are not in the listing)."""
    marks = {m["url"]: m for m in store.tracked(run_id)}
    by_cluster = {}
    for url, m in marks.items():
        o = store.offer(url)
        if o:
            by_cluster.setdefault(o["cluster_id"], m)
    out, seen = [], set()
    for d in rows:
        m = marks.get(d["url"]) or by_cluster.get(d["cluster_id"])
        out.append(_item(d, True, m, detail(store, d["id"])))
        seen.add(m["url"] if m else d["url"])
        seen.add(d["url"])
    for url, m in marks.items():
        if url in seen or m["status"] == "ignored":
            continue
        o = store.offer(url)
        d = dict(o) if o else {"id": -len(out) - 1, "url": url, "title": m["title"] or url}
        out.append(_item(d, False, m, detail(store, o["id"]) if o else None))
    return out


def _script_json(value) -> str:
    """JSON safe inside <script>: no `<` at all, so neither `</script>` nor `<!--` can end or reshape the block."""
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")


def write_html(store: Store, profile: Profile, run_id: int, rows: list[dict], path) -> None:
    run = store.run(run_id)
    data = _data(store, run_id, rows)
    meta = {"key": f"neetscape-{path.parent.name}", "currency": profile.currency, "lang": _LANG.get(profile.country.code, "en"),
            "statuses": [s for s in MARK_STATUSES if s != "ignored"], "n_rows": len(rows), "n_new": sum(d["is_new"] for d in rows),
            "errors": sum(r["errors"] or 0 for r in store.board_stats(run_id)),
            # listings this run did not fetch to their end (over a result cap, or a board's max_pages; see REPORT.md)
            "cut": len(store.capped(run_id)) + sum(not c["deliberate"] for c in store.page_limited(run_id)),
            "cut_deliberate": sum(c["deliberate"] for c in store.page_limited(run_id)),
            "searches": {s.id: s.label for s in profile.searches}, "tags": {t["id"]: t["label"] for t in profile.tags}}
    opt = lambda values: "".join(f'<option value="{_e(v)}">{_e(v)}</option>' for v in values)
    path.write_text(_PAGE.format(
        run_id=run_id, css=_CSS, js=_JS, label=_e(profile.raw.get("label") or "neetscape"), started=_e(run["started_at"][:16]),
        n_marked=sum(1 for d in data if d["mark"]), n_rows=len(rows), modes=opt(["remote", "hybrid", "onsite", "unknown"]),
        boards=opt(sorted({b for d in data for b in d["boards"].split(",") if b})), meta=_script_json(meta), data=_script_json(data)))
