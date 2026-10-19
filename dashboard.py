"""Build output/dashboard.html: pick a row by id and see its Jev scores and the itemization tree."""
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "output"
ORIG_COLS = {"Invoice/Bill ID": "invoice", "Carrier": "carrier", "Dispute Status": "dispute_status",
             "Invoice Amount": "invoice_amount", "Shipment Amount": "shipment_amount", "Event Date": "event_date",
             "Source City": "src", "Destination City": "dst"}


def r3(x):
    return round(float(x), 3)


def main():
    meta = json.loads((OUT / "meta.json").read_text())
    rows = pd.read_csv(OUT / "row_summary.csv", keep_default_na=False, na_values=[""])
    items = pd.read_csv(OUT / "items.csv")
    orig = pd.read_excel(OUT / "itemized.xlsx", sheet_name="original_with_row_id").set_index("row_id")
    jev = json.loads((OUT / "jev_answers.json").read_text())
    cats = list(meta["categories"])

    descs = {}
    for did, d in jev.items():
        a = d["answers"]
        descs[did] = {
            "count": {"p": [r3(a["n_expenses"]["probabilities"][str(k)]) for k in range(6)],
                      "score": r3(a["n_expenses"]["score"]), "conf": r3(a["n_expenses"]["confidence"])},
            "range": {"p": [r3(a["max_range"]["probabilities"][r]) for r in meta["ranges"]],
                      "choice": a["max_range"]["choice"], "conf": r3(a["max_range"]["confidence"])},
            "nouls": [r3(a[f"has_{c}"]["noul"]) for c in cats],
            "cands": [{
                "id": c["id"], "text": c["text"], "value": c["value"], "s": c["start"], "e": c["end"],
                "role": {k: r3(v) for k, v in a[f"role_{c['id']}"]["probabilities"].items()},
                "role_conf": r3(a[f"role_{c['id']}"]["confidence"]),
                # top 3 categories keep the page small; the rest is in output/jev_answers.json
                "cat": sorted(((k, r3(v)) for k, v in a[f"cat_{c['id']}"]["probabilities"].items()),
                              key=lambda kv: -kv[1])[:3],
                "cat_conf": r3(a[f"cat_{c['id']}"]["confidence"]),
            } for c in d["candidates"]],
            "qty": [q[0] for q in d["quantities"]],
        }

    items_by_row = {}
    for it in items.itertuples():
        items_by_row.setdefault(it.row_id, []).append({
            "id": it.item_id, "cat": it.category, "amount": None if pd.isna(it.amount) else it.amount,
            "src": it.amount_source, "text": None if pd.isna(it.source_text) else it.source_text,
            "span": None if pd.isna(it.source_span) else it.source_span,
            "role_p": None if pd.isna(it.role_prob) else it.role_prob,
            "noul": None if pd.isna(it.category_noul) else it.category_noul,
        })

    out_rows = []
    for r in rows.itertuples():
        o = orig.loc[r.row_id]
        extra = {}
        for col, k in ORIG_COLS.items():
            v = o.get(col)
            extra[k] = None if pd.isna(v) else (str(v) if not isinstance(v, (int, float)) else v)
        out_rows.append({
            "id": r.row_id, "did": r.desc_id, "desc": r.description if isinstance(r.description, str) else "",
            "reason": str(r.reason_code).replace("PPGTM.", ""), "delta": r.delta, "sum": r.items_sum,
            "argmax_sum": r.argmax_sum, "n_items": int(r.n_items), "n": int(r.jev_n_expenses),
            "count_ok": bool(r.count_agrees), "code_range": r.code_max_range, "range_ok": bool(r.range_agrees),
            "recon": r.reconciliation, "joint": r.assignment_joint_prob, "status": r.status,
            "items": items_by_row.get(r.row_id, []), **extra,
        })

    data = {"rows": out_rows, "descs": descs, "cats": cats, "cat_desc": meta["categories"],
            "ranges": meta["ranges"], "roles": list(meta["roles"]), "role_desc": meta["roles"],
            "count_levels": meta["count_levels"]}
    html = TEMPLATE.replace("__DATA__", json.dumps(data, separators=(",", ":"), default=str).replace("</", "<\\/"))
    (OUT / "dashboard.html").write_text(html)
    print("wrote", OUT / "dashboard.html", f"{len(html) / 1e6:.1f} MB")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Itemization Dashboard</title>
<style>
:root{color-scheme:light;--bg:#f6f6f4;--surface:#fcfcfb;--surface2:#f0efec;--border:#e4e3df;--text:#0b0b0b;--text2:#52514e;--muted:#7a7974;
--series:#2a78d6;--track:#ecebe7;--r-charge:#2a78d6;--r-rate:#eb6834;--r-total:#1baf7a;--r-reference:#eda100;--r-not_money:#e87ba4;
--good:#0ca30c;--warn:#fab219;--crit:#d03b3b;--sel:#e6effb}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#111110;--surface:#1a1a19;--surface2:#232322;--border:#2e2e2c;
--text:#fff;--text2:#c3c2b7;--muted:#8e8d86;--series:#3987e5;--track:#2a2a28;--r-charge:#3987e5;--r-rate:#d95926;--r-total:#199e70;
--r-reference:#c98500;--r-not_money:#d55181;--sel:#1c2a3d}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#111110;--surface:#1a1a19;--surface2:#232322;--border:#2e2e2c;--text:#fff;--text2:#c3c2b7;
--muted:#8e8d86;--series:#3987e5;--track:#2a2a28;--r-charge:#3987e5;--r-rate:#d95926;--r-total:#199e70;--r-reference:#c98500;
--r-not_money:#d55181;--sel:#1c2a3d}
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--text);font:13.5px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
.app{display:grid;grid-template-columns:320px 1fr;height:100vh}
aside{border-right:1px solid var(--border);background:var(--surface);display:flex;flex-direction:column;min-height:0}
.side-top{padding:14px;border-bottom:1px solid var(--border);display:flex;flex-direction:column;gap:8px}
.side-top h1{font-size:15px;margin:0}.side-top .m{color:var(--text2);font-size:12px}
input,select,button{font:inherit;color:var(--text);background:var(--surface);border:1px solid var(--border);border-radius:7px;padding:6px 9px}
button{cursor:pointer}button:hover{background:var(--surface2)}
.frow{display:flex;gap:6px}.frow>*{flex:1;min-width:0}
#list{overflow-y:auto;flex:1;min-height:0}
.li{padding:8px 14px;border-bottom:1px solid var(--border);cursor:pointer}
.li:hover{background:var(--surface2)}.li.on{background:var(--sel)}
.li .t{display:flex;justify-content:space-between;gap:8px;font-size:12px}.li .d{color:var(--text2);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mono{font-family:ui-monospace,Menlo,monospace;font-size:12px}
main{overflow-y:auto;padding:18px 20px 60px;min-height:0}
.bar-top{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
.bar-top h2{font-size:20px;margin:0 8px 0 0}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;margin-bottom:14px}
.card h3{font-size:14px;margin:0 0 2px}.note{color:var(--muted);font-size:12px;margin:0 0 10px}
.desc{font-size:15px;line-height:1.9;word-break:break-word}
.num{border-bottom:3px solid;padding:0 1px;cursor:default;white-space:nowrap}
.num sup{font-size:10px;color:var(--text2);margin-left:2px}
.meta{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px 16px;margin-top:12px}
.meta div{font-size:12px;color:var(--text2)}.meta b{display:block;overflow-wrap:anywhere;color:var(--text);font-weight:600;font-size:13px;font-variant-numeric:tabular-nums}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.cols.wide{grid-template-columns:minmax(0,1.7fr) minmax(280px,1fr)}@media (max-width:1100px){.cols.wide{grid-template-columns:1fr}}
.status{display:inline-flex;align-items:center;gap:5px;font-size:12px;white-space:nowrap}.dot{width:8px;height:8px;border-radius:50%}
.pill{display:inline-block;border:1px solid var(--border);border-radius:999px;padding:1px 8px;font-size:12px;white-space:nowrap;color:var(--text2)}
/* distribution bars */
.dist{display:flex;align-items:flex-end;gap:4px;height:120px;padding-top:16px}
.dist .c{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;position:relative}
.dist .b{width:100%;background:var(--series);border-radius:4px 4px 0 0;min-height:1px;opacity:.35}
.dist .c.top .b{opacity:1}
.dist .v{font-size:11px;color:var(--text);font-variant-numeric:tabular-nums;margin-bottom:3px}
.dist .l{font-size:10.5px;color:var(--text2);margin-top:4px;white-space:nowrap}
.hb{display:grid;grid-template-columns:150px 1fr 44px;align-items:center;gap:8px;margin:3px 0;font-size:12px}
.hb .tr{position:relative;height:12px;background:var(--track);border-radius:4px}
.hb .fi{position:absolute;left:0;top:0;bottom:0;background:var(--series);border-radius:4px;opacity:.35}
.hb.yes .fi{opacity:1}.hb .th{position:absolute;left:50%;top:-3px;bottom:-3px;border-left:1.5px dashed var(--muted)}
.hb .lab{color:var(--text2);text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.hb.yes .lab{color:var(--text);font-weight:600}
.hb .n{font-variant-numeric:tabular-nums;text-align:right}
/* stacked role bar */
.stack{display:inline-flex;gap:2px;height:10px;width:110px;flex:none;border-radius:4px;overflow:hidden;background:var(--track);vertical-align:middle}
.stack span{display:block;height:100%}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--text2);margin-bottom:10px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
/* tree */
.tree,.tree ul{list-style:none;margin:0;padding:0}
.tree ul{margin-left:11px;padding-left:18px;border-left:1.5px solid var(--border)}
.tree li{position:relative;padding:4px 0;display:flex;flex-wrap:wrap;align-items:flex-start}.tree li>ul{flex-basis:100%}
.tree ul>li::before{content:"";position:absolute;left:-18px;top:15px;width:14px;border-top:1.5px solid var(--border)}
.tree ul>li:last-child::after{content:"";position:absolute;left:-20px;top:16px;bottom:0;border-left:3px solid var(--surface)}
.node{display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap;padding:3px 8px;border:1px solid var(--border);border-radius:8px;background:var(--surface)}
.node.root{background:var(--surface2);font-weight:600}
.node.item{border-color:var(--good)}.node.excl{border-style:dashed;color:var(--muted)}.node.noamt{border-style:dashed}
.tog{cursor:pointer;user-select:none;color:var(--muted);width:14px;flex:none;padding-top:5px;font-size:11px}
.k{color:var(--text2);font-size:12px}.sc{font-variant-numeric:tabular-nums;font-weight:600}
.collapsed>ul{display:none}
table{border-collapse:collapse;width:100%;font-size:12.5px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--border)}
th{color:var(--text2);font-weight:600}td.r{text-align:right;font-variant-numeric:tabular-nums}
.tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:8px 10px;
font-size:12px;box-shadow:0 4px 16px rgba(0,0,0,.14);max-width:320px;display:none;z-index:9}.tip .m{color:var(--text2)}
@media (max-width:820px){.app{grid-template-columns:1fr;height:auto}aside{max-height:45vh}main{overflow:visible}}
</style></head><body>
<div class="app">
<aside>
 <div class="side-top">
  <h1>Itemization dashboard</h1><div class="m" id="sidem"></div>
  <input id="q" placeholder="Row id (R00045) or text" list="ids" autocomplete="off"><datalist id="ids"></datalist>
  <div class="frow"><select id="fs"><option value="">All statuses</option><option>high</option><option>medium</option><option>low</option></select>
  <select id="fn"><option value="">Any count</option><option>0</option><option>1</option><option>2</option><option>3</option><option>4</option><option value="5">5+</option></select></div>
  <label class="m"><input type="checkbox" id="fu" style="vertical-align:-2px"> one row per unique description</label>
 </div>
 <div id="list"></div>
</aside>
<main id="main"></main>
</div><div class="tip" id="tip"></div>
<script>
const D=__DATA__;
const byId=Object.fromEntries(D.rows.map(r=>[r.id,r]));
const ROLE_LABEL={charge:'charge',rate:'rate',total:'total',reference:'paid / approved / billed',not_money:'not money'};
const RANGE_LABEL=r=>({no_amount:'none','500-1000':'500–1k','1000-2500':'1k–2.5k','2500+':'2.5k+'})[r]||r.replace('-','–');
const statusColor={high:'var(--good)',medium:'var(--warn)',low:'var(--crit)'},statusIcon={high:'✓',medium:'!',low:'✕'};
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=v=>v==null||v===''?'—':Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const p2=v=>v==null?'—':Number(v).toFixed(2);
const st=s=>`<span class="status"><span class="dot" style="background:${statusColor[s]}"></span>${statusIcon[s]} ${s}</span>`;
const tip=document.getElementById('tip');
document.addEventListener('mousemove',e=>{const t=e.target.closest('[data-tip]');if(!t){tip.style.display='none';return}
 tip.innerHTML=t.dataset.tip;tip.style.display='block';tip.style.left=Math.min(e.clientX+14,innerWidth-tip.offsetWidth-8)+'px';
 tip.style.top=Math.min(e.clientY+14,innerHeight-tip.offsetHeight-8)+'px'});
const roleTop=c=>Object.entries(c.role).sort((a,b)=>b[1]-a[1])[0];
function stack(c){return `<span class="stack" data-tip="${esc(D.roles.map(k=>`${ROLE_LABEL[k]}: <b>${p2(c.role[k])}</b>`).join('<br>'))}">`+
 D.roles.map(k=>c.role[k]>0.005?`<span style="width:${c.role[k]*100}%;background:var(--r-${k})"></span>`:'').join('')+'</span>'}

// ---------- sidebar ----------
let current=null,filtered=[];
document.getElementById('sidem').textContent=`${D.rows.length} rows · ${D.rows.reduce((s,r)=>s+r.items.length,0)} items · ${Object.keys(D.descs).length} unique descriptions`;
document.getElementById('ids').innerHTML=D.rows.map(r=>`<option value="${r.id}">`).join('');
function renderList(){const q=document.getElementById('q').value.trim().toLowerCase(),fs=document.getElementById('fs').value,
 fn=document.getElementById('fn').value,fu=document.getElementById('fu').checked,seen=new Set();
 filtered=D.rows.filter(r=>{if(fu){if(seen.has(r.did))return false;}const ok=(!q||r.id.toLowerCase().includes(q)||r.desc.toLowerCase().includes(q))&&(!fs||r.status===fs)&&(!fn||String(r.n)===fn);
  if(ok&&fu)seen.add(r.did);return ok});
 document.getElementById('list').innerHTML=filtered.slice(0,600).map(r=>`<div class="li${r.id===current?' on':''}" data-id="${r.id}">
  <div class="t"><span class="mono">${r.id}</span><span>${r.n===5?'5+':r.n} exp · ${st(r.status)}</span></div><div class="d">${esc(r.desc)||'<i>(blank)</i>'}</div></div>`).join('')
  +(filtered.length>600?`<div class="li"><div class="d">${filtered.length-600} more, refine the search</div></div>`:'');
 if(!filtered.length)document.getElementById('list').innerHTML='<div class="li"><div class="d">No rows match</div></div>'}
document.getElementById('list').addEventListener('click',e=>{const li=e.target.closest('.li[data-id]');if(li)select(li.dataset.id)});
['q','fs','fn','fu'].forEach(id=>document.getElementById(id).addEventListener('input',()=>{renderList();const v=document.getElementById('q').value.trim().toUpperCase();if(byId[v])select(v)}));
document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT'&&e.target.type!=='checkbox')return;if(!['j','k','ArrowDown','ArrowUp'].includes(e.key))return;
 e.preventDefault();const i=filtered.findIndex(r=>r.id===current),n=filtered[Math.max(0,Math.min(filtered.length-1,i+(e.key==='j'||e.key==='ArrowDown'?1:-1)))];if(n)select(n.id)});

// ---------- main ----------
function select(id){current=id;history.replaceState(null,'','#'+id);
 document.querySelectorAll('.li').forEach(li=>li.classList.toggle('on',li.dataset.id===id));
 const on=document.querySelector('.li.on');if(on)on.scrollIntoView({block:'nearest'});render(byId[id])}
function nav(d){const i=filtered.findIndex(r=>r.id===current),n=filtered[i+d];if(n)select(n.id)}

function descHtml(r,j){let out='',pos=0;const t=r.desc;
 j.cands.forEach(c=>{const [role,p]=roleTop(c);out+=esc(t.slice(pos,c.s));
  out+=`<span class="num" style="border-color:var(--r-${role})" data-tip="<b>${c.id} · ${esc(c.text)}</b><br>role: ${ROLE_LABEL[role]} (${p2(p)})<br><span class=m>category:</span> ${esc(c.cat[0][0])} (${p2(c.cat[0][1])})">${esc(t.slice(c.s,c.e))}<sup>${c.id}</sup></span>`;pos=c.e});
 return out+esc(t.slice(pos))||'<i class="k">(blank description)</i>'}

function dist(labels,ps,topIdx,tipf){return `<div class="dist">`+ps.map((p,i)=>`<div class="c${i===topIdx?' top':''}" data-tip="${esc(tipf(i,p))}">
 <span class="v">${p>=0.005?p2(p):''}</span><div class="b" style="height:${Math.max(p*100,0.5)}%"></div><span class="l">${esc(labels[i])}</span></div>`).join('')+'</div>'}

function tree(r,j){
 const itemsBySpan={};r.items.forEach(it=>{if(it.span)itemsBySpan[it.span]=it});
 const cnt=j.count,topN=cnt.p.indexOf(Math.max(...cnt.p)),rng=j.range;
 const catsOn=D.cats.map((c,i)=>[c,j.nouls[i]]).filter(x=>x[1]>=0.5).sort((a,b)=>b[1]-a[1]);
 const L=(node,kids,open=true)=>`<li class="${open?'':'collapsed'}">${kids?`<span class="tog">${open?'▾':'▸'}</span>`:'<span class="tog"></span>'}${node}${kids?`<ul>${kids}</ul>`:''}</li>`;
 const numKids=j.cands.map(c=>{const [role,p]=roleTop(c),span=`${c.s}:${c.e}`,it=itemsBySpan[span];
  const stated=r.items.find(x=>x.src==='stated_not_in_delta'&&x.text===c.text);
  const catNode=`<span class="node"><span class="k">category (Choice)</span> ${esc(c.cat[0][0])} <span class="sc">${p2(c.cat[0][1])}</span>
   <span class="k" data-tip="${esc(c.cat.map(x=>`${x[0]}: ${p2(x[1])}`).join('<br>'))}">conf ${p2(c.cat_conf)}</span></span>`;
  let res;
  if(it)res=`<span class="node item">✓ item <span class="mono">${it.id}</span> ${esc(it.cat)} <b>$${fmt(it.amount)}</b> <span class="k">${it.src==='rate'?'rate × qty':'counted as charge'}</span></span>`;
  else if(stated)res=`<span class="node noamt">item <span class="mono">${stated.id}</span> ${esc(stated.cat)} $${fmt(stated.amount)} <span class="k">stated, but left out of Delta</span></span>`;
  else res=`<span class="node excl">✕ not an item <span class="k">(${role==='rate'?'rate already covered by a charge':ROLE_LABEL[role]}${r.recon==='reconciled_to_delta'?', after Delta reconciliation':''})</span></span>`;
  return L(`<span class="node"><span class="mono">${c.id}</span> <b>${esc(c.text)}</b> <span class="k">role (Choice)</span> <span style="color:var(--text)">${ROLE_LABEL[role]}</span> <span class="sc">${p2(p)}</span> ${stack(c)}</span>`,
   L(catNode,L(res)))}).join('');
 const unpriced=r.items.filter(it=>it.src==='no_separate_amount');
 const deltaOk=r.delta!=null&&Math.abs(Math.abs(r.delta)-r.sum)<=Math.max(0.02,0.005*Math.abs(r.delta));
 return `<ul class="tree">`+L(`<span class="node root">Row <span class="mono">${r.id}</span> → ${r.n_items} item(s) ${st(r.status)}</span>`,
  L(`<span class="node"><span class="k">expense count (Score)</span> <span class="sc">${topN===5?'5+':topN}</span> <span class="k">score ${p2(cnt.score)} · conf ${p2(cnt.conf)}</span> ${r.count_ok?'<span class="pill">✓ matches items</span>':`<span class="pill">✕ items give ${r.n_items}</span>`}</span>`)
  +L(`<span class="node"><span class="k">largest expense (Choice)</span> <span class="sc">$${RANGE_LABEL(rng.choice)}</span> <span class="k">conf ${p2(rng.conf)}</span> ${r.range_ok?'<span class="pill">✓ matches items</span>':`<span class="pill">✕ items give $${RANGE_LABEL(r.code_range)}</span>`}</span>`)
  +L(`<span class="node"><span class="k">categories present (Noul ≥ 0.5)</span> <span class="sc">${catsOn.length}</span></span>`,
     catsOn.map(([c,p])=>L(`<span class="node" data-tip="${esc(D.cat_desc[c])}">${esc(c)} <span class="sc">${p2(p)}</span></span>`)).join(''),true)
  +L(`<span class="node"><span class="k">numbers found in the text</span> <span class="sc">${j.cands.length}</span>${j.qty.length?` <span class="k">quantities: ${j.qty.join(', ')}</span>`:''}</span>`,numKids||null)
  +(unpriced.length?L(`<span class="node"><span class="k">expenses named without their own amount</span> <span class="sc">${unpriced.length}</span></span>`,
     unpriced.map(it=>L(`<span class="node noamt">item <span class="mono">${it.id}</span> ${esc(it.cat)} <span class="k">Noul ${p2(it.noul)} · no amount</span></span>`)).join('')):'')
  +L(`<span class="node"><span class="k">check against Delta</span> items $${fmt(r.sum)} ${deltaOk?'=':'≠'} Delta $${fmt(r.delta)} <span class="pill">${esc(r.recon)}</span> <span class="k">joint p ${p2(r.joint)}</span></span>`)
 )+'</ul>'}

function render(r){const j=D.descs[r.did],i=filtered.findIndex(x=>x.id===r.id);
 const cnt=j.count,topN=cnt.p.indexOf(Math.max(...cnt.p)),rng=j.range,topR=D.ranges.indexOf(rng.choice);
 document.getElementById('main').innerHTML=`
 <div class="bar-top"><h2 class="mono">${r.id}</h2>${st(r.status)}<span class="pill">${esc(r.recon)}</span><span style="flex:1"></span>
  <button id="prev" ${i<=0?'disabled':''}>← Prev</button><button id="next" ${i<0||i>=filtered.length-1?'disabled':''}>Next →</button></div>
 <div class="card"><div class="legend">${D.roles.map(k=>`<span data-tip="${esc(D.role_desc[k])}"><i style="background:var(--r-${k})"></i>${ROLE_LABEL[k]}</span>`).join('')}</div>
  <div class="desc">${descHtml(r,j)}</div>
  <div class="meta">
   <div>Reason code<b>${esc(r.reason)}</b></div><div>Delta<b>$${fmt(r.delta)}</b></div><div>Items sum<b>$${fmt(r.sum)}</b></div>
   <div>Invoice amount<b>$${fmt(r.invoice_amount)}</b></div><div>Shipment amount<b>$${fmt(r.shipment_amount)}</b></div>
   <div>Invoice / bill<b class="mono">${esc(r.invoice||'—')}</b></div><div>Carrier<b>${esc((r.carrier||'—').replace('PPGTM.',''))}</b></div>
   <div>Lane<b>${esc(r.src||'—')} → ${esc(r.dst||'—')}</b></div><div>Event date<b>${esc((r.event_date||'—').slice(0,10))}</b></div>
   <div>Description id<b class="mono">${r.did}</b></div></div></div>
 <div class="cols">
  <div class="card"><h3>Expense count</h3><p class="note">Score over levels 0 … 5+. Score ${p2(cnt.score)} · confidence ${p2(cnt.conf)}</p>
   ${dist(['0','1','2','3','4','5+'],cnt.p,topN,(k,p)=>`<b>${D.count_levels[k]}</b><br>probability ${p2(p)}`)}</div>
  <div class="card"><h3>Largest single expense</h3><p class="note">Choice over dollar ranges. Confidence ${p2(rng.conf)}</p>
   ${dist(D.ranges.map(RANGE_LABEL),rng.p,topR,(k,p)=>`<b>$${RANGE_LABEL(D.ranges[k])}</b><br>probability ${p2(p)}`)}</div>
 </div>
 <div class="cols wide">
  <div class="card"><h3>Itemization tree</h3><p class="note">Click ▾ to collapse. Hover the role bars and scores for full distributions.</p><div id="tree">${tree(r,j)}</div></div>
  <div class="card"><h3>Category Nouls</h3><p class="note">Probability the row claims each category. Dashed line = 0.5.</p>
   ${D.cats.map((c,k)=>[c,j.nouls[k]]).sort((a,b)=>b[1]-a[1]).map(([c,p])=>`<div class="hb${p>=0.5?' yes':''}" data-tip="${esc(D.cat_desc[c])}">
   <span class="lab">${esc(c)}</span><span class="tr"><span class="fi" style="width:${p*100}%"></span><span class="th"></span></span><span class="n">${p2(p)}</span></div>`).join('')}</div>
 </div>
 <div class="card"><h3>Items (${r.items.length})</h3>${r.items.length?`<table><thead><tr><th>Item id</th><th>Category</th><th>Source text</th><th>Amount source</th><th class="r">Amount</th></tr></thead><tbody>
  ${r.items.map(it=>`<tr><td class="mono">${it.id}</td><td>${esc(it.cat)}</td><td class="mono">${esc(it.text||'—')}</td><td>${esc(it.src)}</td><td class="r">${it.amount==null?'—':'$'+fmt(it.amount)}</td></tr>`).join('')}
  </tbody></table>`:'<p class="note">No items: nothing is claimed in this row.</p>'}</div>`;
 document.getElementById('prev').onclick=()=>nav(-1);document.getElementById('next').onclick=()=>nav(1);
 document.getElementById('tree').addEventListener('click',e=>{const t=e.target.closest('.tog');if(!t||!t.textContent)return;
  const li=t.parentElement;li.classList.toggle('collapsed');t.textContent=li.classList.contains('collapsed')?'▸':'▾'});
 document.getElementById('main').scrollTop=0}

renderList();
const start=location.hash.slice(1);select(byId[start]?start:(D.rows.find(r=>r.n>=3&&r.status==='high')||D.rows[0]).id);
</script></body></html>"""

if __name__ == "__main__":
    main()
