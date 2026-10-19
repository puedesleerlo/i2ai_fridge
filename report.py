"""Build output/report.html: an exploration view of the Jev itemization (reads output/*.csv)."""
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "output"


def main():
    rows = pd.read_csv(OUT / "row_summary.csv", keep_default_na=False, na_values=[""])
    items = pd.read_csv(OUT / "items.csv")
    meta = json.loads((OUT / "meta.json").read_text())
    cats = list(meta["categories"])

    count = []
    for k in range(6):
        sub = rows[rows.jev_n_expenses == k]
        count.append({"label": "5+" if k == 5 else str(k), "rows": len(sub),
                      "conf": round(sub.jev_n_expenses_conf.mean(), 3) if len(sub) else None,
                      "agree": round(sub.count_agrees.mean(), 3) if len(sub) else None})
    conf_bands = [
        {"label": "≥ 0.9", "rows": int((rows.jev_n_expenses_conf >= 0.9).sum())},
        {"label": "0.6 – 0.9", "rows": int(((rows.jev_n_expenses_conf >= 0.6) & (rows.jev_n_expenses_conf < 0.9)).sum())},
        {"label": "< 0.6", "rows": int((rows.jev_n_expenses_conf < 0.6).sum())},
    ]
    cat_prev = sorted(({"label": c, "rows": int((rows[f"p_{c}"] >= 0.5).sum()),
                        "items": int((items.category == c).sum()),
                        "amount": round(float(items.loc[items.category == c, "amount"].fillna(0).sum()), 2),
                        "desc": meta["categories"][c]} for c in cats), key=lambda d: -d["rows"])
    ranges = [{"label": r, "rows": int((rows.jev_max_range == r).sum()),
               "conf": round(rows.loc[rows.jev_max_range == r, "jev_max_range_conf"].mean(), 3)
               if (rows.jev_max_range == r).any() else None} for r in meta["ranges"]]
    status = rows.status.value_counts().to_dict()
    recon = rows.reconciliation.value_counts().to_dict()

    by_row = items.groupby("row_id").apply(
        lambda g: [{"c": r.category, "a": None if pd.isna(r.amount) else r.amount, "s": r.amount_source}
                   for r in g.itertuples()], include_groups=False).to_dict()
    table = [{
        "row_id": r.row_id, "desc": r.description if isinstance(r.description, str) else "",
        "delta": r.delta, "sum": r.items_sum, "n": int(r.jev_n_expenses), "nconf": r.jev_n_expenses_conf,
        "items": by_row.get(r.row_id, []), "range": r.jev_max_range, "status": r.status, "recon": r.reconciliation,
    } for r in rows.itertuples()]

    data = {"count": count, "conf_bands": conf_bands, "cats": cat_prev, "ranges": ranges, "status": status,
            "recon": recon, "rows": table, "n_rows": len(rows), "n_items": len(items),
            "n_unique": int(rows.desc_id.nunique()),
            "count_agree": round(rows.count_agrees.mean(), 3), "range_agree": round(rows.range_agrees.mean(), 3)}
    html = TEMPLATE.replace("__DATA__", json.dumps(data, default=float).replace("</", "<\\/"))
    (OUT / "report.html").write_text(html)
    print("wrote", OUT / "report.html")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dispute Expense Itemization</title>
<style>
:root{color-scheme:light;--bg:#f6f6f4;--surface:#fcfcfb;--border:#e4e3df;--text:#0b0b0b;--text2:#52514e;--muted:#7a7974;
--series:#2a78d6;--series-soft:#cde2fb;--grid:#ecebe7;--good:#0ca30c;--warn:#fab219;--crit:#d03b3b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#111110;--surface:#1a1a19;--border:#2e2e2c;
--text:#fff;--text2:#c3c2b7;--muted:#8e8d86;--series:#3987e5;--series-soft:#184f95;--grid:#262624}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#111110;--surface:#1a1a19;--border:#2e2e2c;--text:#fff;--text2:#c3c2b7;--muted:#8e8d86;
--series:#3987e5;--series-soft:#184f95;--grid:#262624}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 16px 60px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;margin:0 0 2px}.sub{color:var(--text2);margin:0 0 20px}
.note{color:var(--muted);font-size:12.5px;margin:2px 0 12px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
.tile,.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.tile .v{font-size:26px;font-weight:650;font-variant-numeric:tabular-nums}.tile .l{color:var(--text2);font-size:12.5px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px;margin-bottom:16px}
svg{display:block;width:100%;height:auto;overflow:visible}svg text{fill:var(--text2);font-size:11.5px}
svg .val{fill:var(--text);font-size:11.5px;font-variant-numeric:tabular-nums}
.bar{fill:var(--series)}.bar:hover,.bar.hl{opacity:.8}.hit{fill:transparent;cursor:default}
.tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:8px;
padding:8px 10px;font-size:12.5px;box-shadow:0 4px 16px rgba(0,0,0,.12);max-width:300px;display:none;z-index:9}
.tip b{font-weight:600}.tip .m{color:var(--text2)}
.status{display:inline-flex;align-items:center;gap:5px;font-size:12px;white-space:nowrap}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0 10px}
input,select{font:inherit;color:var(--text);background:var(--surface);border:1px solid var(--border);border-radius:7px;padding:6px 9px}
input{flex:1;min-width:180px}
.tw{overflow-x:auto;border:1px solid var(--border);border-radius:10px;background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:12.5px}th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--border);vertical-align:top}
th{color:var(--text2);font-weight:600;position:sticky;top:0;background:var(--surface)}td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.chip{display:inline-block;border:1px solid var(--border);border-radius:6px;padding:1px 6px;margin:1px 3px 1px 0;white-space:nowrap}
.chip.na{border-style:dashed;color:var(--muted)}.mono{font-family:ui-monospace,Menlo,monospace;font-size:12px}
details summary{cursor:pointer;color:var(--text2);font-size:12.5px}
</style></head><body><main>
<h1>Dispute expense itemization</h1>
<p class="sub">AutoPay Dispute Data 20220815: the freeform <span class="mono">Descritipion</span> column split into one row per expense with Jev (TypeSafe System One). Code proposes candidate numbers, Jev judges each number's role and category, and each row is reconciled against its <span class="mono">Delta</span>.</p>
<div class="tiles" id="tiles"></div>
<div class="grid">
 <div class="card"><h2>Expenses per row (Jev count)</h2><p class="note">Most probable level of the count Score. Hover a bar to see the mean confidence and how often the itemization agrees.</p><div id="c-count"></div></div>
 <div class="card"><h2>Confidence of the count</h2><p class="note">Rows grouped by the count Score's confidence.</p><div id="c-conf"></div></div>
</div>
<div class="grid">
 <div class="card"><h2>Rows containing each category</h2><p class="note">Rows where the category Noul is ≥ 0.5. A row can contain several categories.</p><div id="c-cat"></div></div>
 <div class="card"><h2>Largest single expense in the row</h2><p class="note">Jev Choice over log-spaced dollar buckets.</p><div id="c-range"></div></div>
</div>
<div class="card" style="margin-bottom:16px"><h2>Rows and their items</h2>
<p class="note">One line per original row. Chips are the extracted items; a dashed chip is an expense named without its own amount, or one whose stated amount is not included in Delta.</p>
<div class="filters"><input id="q" placeholder="Search descriptions or row id"><select id="fs"><option value="">All statuses</option><option>high</option><option>medium</option><option>low</option></select>
<select id="fn"><option value="">Any count</option><option>0</option><option>1</option><option>2</option><option>3</option><option>4</option><option value="5">5+</option></select>
<select id="fr"><option value="">Any reconciliation</option></select><span class="note" id="shown"></span></div>
<div class="tw" style="max-height:620px"><table><thead><tr><th>Row</th><th>Description</th><th>Items</th><th>Count</th><th>Items sum</th><th>Delta</th><th>Status</th></tr></thead><tbody id="tb"></tbody></table></div>
</div>
<details><summary>How statuses are assigned</summary><p class="note"><b>high</b>: Jev's most likely role for each number gives items that sum to Delta, the item count equals Jev's count, and the count confidence is ≥ 0.6.
<b>medium</b>: the items match Delta only after searching the other role assignments Jev found plausible (or Delta is a whole multiple of the items), and the count is off by one at most.
<b>low</b>: everything else, e.g. Delta cannot be explained by the numbers in the text.</p></details>
</main><div class="tip" id="tip"></div>
<script>
const D=__DATA__;
const tip=document.getElementById('tip');
const fmt=v=>v==null?'—':Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const pct=v=>v==null?'—':(v*100).toFixed(1)+'%';
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function showTip(e,h){tip.innerHTML=h;tip.style.display='block';const x=Math.min(e.clientX+14,innerWidth-tip.offsetWidth-8);tip.style.left=x+'px';tip.style.top=(e.clientY+14)+'px'}
function hideTip(){tip.style.display='none'}
const statusColor={high:'var(--good)',medium:'var(--warn)',low:'var(--crit)'};
const statusIcon={high:'✓',medium:'!',low:'✕'};
function statusHtml(s){return `<span class="status"><span class="dot" style="background:${statusColor[s]}"></span>${statusIcon[s]} ${s}</span>`}

// tiles
const T=[[D.n_rows.toLocaleString(),'original rows'],[D.n_unique.toLocaleString(),'unique descriptions sent to Jev'],[D.n_items.toLocaleString(),'items extracted'],
[pct((D.status.high||0)/D.n_rows),'rows high status'],[pct(D.count_agree),'count agrees with items'],[pct(D.range_agree),'range agrees with items']];
document.getElementById('tiles').innerHTML=T.map(([v,l])=>`<div class="tile"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');

// vertical bars
function vbars(el,data,tipf){const W=520,H=220,m={t:18,r:8,b:28,l:8},iw=W-m.l-m.r,ih=H-m.t-m.b,max=Math.max(...data.map(d=>d.rows))||1;
 const bw=iw/data.length,g=Math.min(10,bw*.25);let s=`<svg viewBox="0 0 ${W} ${H}" role="img">`;
 s+=`<line x1="${m.l}" x2="${W-m.r}" y1="${m.t+ih}" y2="${m.t+ih}" stroke="var(--border)"/>`;
 data.forEach((d,i)=>{const h=d.rows/max*ih,x=m.l+i*bw+g/2,w=bw-g,y=m.t+ih-h,r=Math.min(4,w/2,h);
  s+=`<path class="bar" d="M${x},${m.t+ih}V${y+r}Q${x},${y} ${x+r},${y}H${x+w-r}Q${x+w},${y} ${x+w},${y+r}V${m.t+ih}Z"/>`;
  s+=`<text class="val" x="${x+w/2}" y="${y-5}" text-anchor="middle">${d.rows}</text><text x="${x+w/2}" y="${H-8}" text-anchor="middle">${esc(d.label)}</text>`;
  s+=`<rect class="hit" data-i="${i}" x="${m.l+i*bw}" y="${m.t}" width="${bw}" height="${ih+m.b}"/>`});
 el.innerHTML=s+'</svg>';bindTips(el,data,tipf)}
// horizontal bars
function hbars(el,data,tipf){const W=520,rh=26,lw=170,m={t:4,r:44},H=m.t+data.length*rh,max=Math.max(...data.map(d=>d.rows))||1,iw=W-lw-m.r;
 let s=`<svg viewBox="0 0 ${W} ${H}" role="img">`;
 data.forEach((d,i)=>{const y=m.t+i*rh+4,h=rh-8,w=Math.max(1,d.rows/max*iw),r=Math.min(4,h/2,w);
  s+=`<text x="${lw-8}" y="${y+h/2+4}" text-anchor="end">${esc(d.label)}</text>`;
  s+=`<path class="bar" d="M${lw},${y}H${lw+w-r}Q${lw+w},${y} ${lw+w},${y+r}V${y+h-r}Q${lw+w},${y+h} ${lw+w-r},${y+h}H${lw}Z"/>`;
  s+=`<text class="val" x="${lw+w+6}" y="${y+h/2+4}">${d.rows}</text><rect class="hit" data-i="${i}" x="0" y="${y-4}" width="${W}" height="${rh}"/>`});
 el.innerHTML=s+'</svg>';bindTips(el,data,tipf)}
function bindTips(el,data,f){el.querySelectorAll('.hit').forEach(h=>{const i=+h.dataset.i,bar=el.querySelectorAll('.bar')[i];
 h.addEventListener('mousemove',e=>{bar.classList.add('hl');showTip(e,f(data[i]))});h.addEventListener('mouseleave',()=>{bar.classList.remove('hl');hideTip()})})}

vbars(document.getElementById('c-count'),D.count,d=>`<b>${d.label} expense(s)</b><br>${d.rows} rows (${pct(d.rows/D.n_rows)})<br><span class="m">mean confidence</span> ${d.conf??'—'}<br><span class="m">itemization agrees</span> ${pct(d.agree)}`);
vbars(document.getElementById('c-conf'),D.conf_bands,d=>`<b>confidence ${d.label}</b><br>${d.rows} rows (${pct(d.rows/D.n_rows)})`);
hbars(document.getElementById('c-cat'),D.cats,d=>`<b>${d.label}</b><br><span class="m">${esc(d.desc)}</span><br>${d.rows} rows · ${d.items} items · $${fmt(d.amount)}`);
vbars(document.getElementById('c-range'),D.ranges.map(r=>({...r,label:({no_amount:'none','500-1000':'500–1k','1000-2500':'1k–2.5k','2500+':'2.5k+'})[r.label]||r.label.replace('-','–')})),d=>`<b>$${d.label}</b><br>${d.rows} rows<br><span class="m">mean confidence</span> ${d.conf??'—'}`);

// table
const fr=document.getElementById('fr');Object.keys(D.recon).forEach(k=>fr.insertAdjacentHTML('beforeend',`<option>${k}</option>`));
function chips(it){return it.map(x=>`<span class="chip${x.a==null||x.s==='stated_not_in_delta'?' na':''}" title="${x.s}">${esc(x.c)}${x.a!=null?' $'+fmt(x.a):''}</span>`).join('')}
function render(){const q=document.getElementById('q').value.toLowerCase(),fs=document.getElementById('fs').value,fn=document.getElementById('fn').value,frv=fr.value;
 const rs=D.rows.filter(r=>(!q||r.desc.toLowerCase().includes(q)||r.row_id.toLowerCase().includes(q))&&(!fs||r.status===fs)&&(!fn||String(r.n)===fn)&&(!frv||r.recon===frv));
 document.getElementById('shown').textContent=`${rs.length} rows`+(rs.length>400?' (first 400 shown)':'');
 document.getElementById('tb').innerHTML=rs.slice(0,400).map(r=>`<tr><td class="mono">${r.row_id}</td><td>${esc(r.desc)}</td><td>${chips(r.items)}</td>
 <td class="n">${r.n===5?'5+':r.n} <span style="color:var(--muted)">(${Number(r.nconf).toFixed(2)})</span></td><td class="n">${fmt(r.sum)}</td><td class="n">${fmt(r.delta)}</td><td title="${r.recon}">${statusHtml(r.status)}</td></tr>`).join('')}
['q','fs','fn','fr'].forEach(id=>document.getElementById(id).addEventListener('input',render));
document.getElementById('fs').value='';render();
</script></body></html>"""

if __name__ == "__main__":
    main()
