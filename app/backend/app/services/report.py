"""Self-contained HTML and CSV reports of an analysis."""

import csv
import io
import json
from collections import Counter, defaultdict
from datetime import datetime
from html import escape

from app import models
from app.db import utcnow
from app.schemas import SEVERITIES
from app.services.presenters import SEVERITY_ORDER, duration_ms

KIND_LABELS = {"regex": "Regex", "llm": "LLM", "builtin": "Yerleşik"}

SEVERITY_LABELS = {
    "critical": "Kritik",
    "high": "Yüksek",
    "medium": "Orta",
    "low": "Düşük",
    "info": "Bilgi",
}
SEVERITY_COLORS = {
    "critical": "#991B1B",
    "high": "#DC2626",
    "medium": "#D97706",
    "low": "#2563EB",
    "info": "#64748B",
}
STATUS_LABELS = {
    "queued": "Kuyrukta",
    "running": "Çalışıyor",
    "completed": "Tamamlandı",
    "failed": "Başarısız",
    "cancelled": "İptal edildi",
    "pending": "Bekliyor",
    "done": "Tamamlandı",
    "error": "Hata",
}
TYPE_LABELS = {
    "PROCEDURE": "Prosedür",
    "VIEW": "View",
    "FUNCTION_SCALAR": "Skaler fonksiyon",
    "FUNCTION_INLINE": "Inline TVF",
    "FUNCTION_TABLE": "Tablo fonksiyonu",
}
FILTER_LABELS = {
    "databases": "Veritabanları",
    "schemas": "Şemalar",
    "types": "Nesne tipleri",
    "created_from": "Oluşturma (başlangıç)",
    "created_to": "Oluşturma (bitiş)",
    "modified_from": "Değiştirme (başlangıç)",
    "modified_to": "Değiştirme (bitiş)",
    "search": "Ad araması",
    "schedule": "Zamanlanmış analiz",
    "incremental": "Artımlı tarama",
    "changed_since": "Değişiklik başlangıcı (UTC)",
}


def _e(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _dt(value: datetime | None) -> str:
    return value.strftime("%d.%m.%Y %H:%M:%S") + " UTC" if value else "-"


def _duration(ms: int | None) -> str:
    if ms is None:
        return "-"
    seconds = ms // 1000
    if seconds < 60:
        return f"{ms / 1000:.1f} sn"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} dk {seconds} sn"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} sa {minutes} dk"


def _badge(severity: str) -> str:
    color = SEVERITY_COLORS.get(severity, "#64748B")
    label = SEVERITY_LABELS.get(severity, severity)
    return f'<span class="badge" style="background:{color}">{_e(label)}</span>'


def _filter_value(value: object) -> str:
    if isinstance(value, bool):
        return "Evet" if value else "Hayır"
    if isinstance(value, list):
        if not value:
            return "Tümü"
        return ", ".join(TYPE_LABELS.get(str(v), str(v)) for v in value)
    if value is None or value == "":
        return "-"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


CSS = """
:root{--bg:#F6F7F9;--panel:#FFFFFF;--panel2:#F8FAFC;--line:#E2E8F0;--line2:#CBD5E1;--fg:#0F172A;--fg2:#475569;--fg3:#64748B;--accent:#4F46E5;--accent-soft:#EEF2FF;--code-bg:#0F172A;--code-fg:#E2E8F0}
@media (prefers-color-scheme:dark){:root{--bg:#0B0D12;--panel:#12151C;--panel2:#171B24;--line:#262C38;--line2:#363E4E;--fg:#E7EAF0;--fg2:#AAB2C0;--fg3:#8790A0;--accent:#8B93FF;--accent-soft:#1E2140;--code-bg:#0A0C10;--code-fg:#D7DCE5}}
*{box-sizing:border-box}
body{font-family:"Segoe UI",Inter,Roboto,Helvetica,Arial,sans-serif;color:var(--fg);background:var(--bg);margin:0;font-size:13px;line-height:1.45}
.page{max-width:1180px;margin:0 auto;padding:28px 28px 40px}
h1{font-size:22px;margin:2px 0 4px;letter-spacing:-.01em}
h2{font-size:14px;margin:0 0 10px}
.muted{color:var(--fg3)}
.mono,.code{font-family:Consolas,"Cascadia Mono","Courier New",monospace}
.code{font-weight:600}
.header{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:16px}
.brand{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--accent)}
.status{display:inline-block;padding:3px 10px;border-radius:999px;background:var(--accent-soft);color:var(--accent);font-weight:600;font-size:12px;white-space:nowrap}
.btn{border:1px solid var(--line2);background:var(--panel);color:var(--fg);border-radius:8px;padding:5px 10px;font:inherit;font-size:12px;cursor:pointer}
.btn:hover{border-color:var(--accent)}
.kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin-bottom:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.kpi .v{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums}
.kpi .k{font-size:11px;color:var(--fg3);text-transform:uppercase;letter-spacing:.04em}
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin:6px 0 14px;position:sticky;top:0;background:var(--bg);z-index:5;padding-top:6px}
.tab{border:0;background:none;color:var(--fg2);font:inherit;font-weight:600;padding:8px 12px;border-bottom:2px solid transparent;cursor:pointer}
.tab[aria-selected=true]{color:var(--fg);border-bottom-color:var(--accent)}
.tab .n{font-weight:500;color:var(--fg3);margin-left:4px}
.panel[hidden]{display:none}
.two{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:var(--fg3);font-weight:600}
td.num,th.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.kv td:first-child{width:42%;color:var(--fg2);font-weight:600}
.badge{display:inline-block;color:#fff;border-radius:4px;padding:1px 6px;font-size:11px;font-weight:600;white-space:nowrap}
.stack{display:flex;height:12px;border-radius:6px;overflow:hidden;background:var(--panel2);margin:6px 0 10px}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:0}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px}
.toolbar input[type=search]{flex:1;min-width:220px;border:1px solid var(--line2);background:var(--panel);color:var(--fg);border-radius:8px;padding:6px 10px;font:inherit}
.chip{border:1px solid var(--line2);background:var(--panel);color:var(--fg2);border-radius:999px;padding:3px 10px;font:inherit;font-size:12px;cursor:pointer}
.chip[aria-pressed=true]{border-color:var(--accent);background:var(--accent-soft);color:var(--fg)}
select{border:1px solid var(--line2);background:var(--panel);color:var(--fg);border-radius:8px;padding:5px 8px;font:inherit;font-size:12px}
details.grp{background:var(--panel);border:1px solid var(--line);border-radius:10px;margin-bottom:6px;overflow:hidden}
details.grp>summary{display:flex;align-items:center;gap:10px;padding:9px 12px;cursor:pointer;list-style:none}
details.grp>summary::-webkit-details-marker{display:none}
details.grp>summary:hover{background:var(--panel2)}
details.grp[open]>summary{border-bottom:1px solid var(--line);background:var(--panel2)}
.chev{transition:transform .15s;color:var(--fg3);font-size:11px;width:10px}
details[open]>summary .chev{transform:rotate(90deg)}
.gtitle{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}
.counts{display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end}
.cnt{font-size:11px;border-radius:4px;padding:1px 6px;font-weight:600;color:#fff;font-variant-numeric:tabular-nums}
.total{min-width:46px;text-align:right;font-weight:700;font-variant-numeric:tabular-nums}
details.f{border-top:1px solid var(--line)}
details.f:first-child{border-top:0}
details.f>summary{display:grid;grid-template-columns:auto 118px 64px minmax(0,1fr);gap:10px;align-items:center;padding:6px 12px 6px 30px;cursor:pointer;list-style:none}
details.f>summary::-webkit-details-marker{display:none}
details.f>summary:hover{background:var(--panel2)}
.fmsg{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--fg2)}
.fbody{padding:4px 14px 12px 30px}
pre{font-family:Consolas,"Cascadia Mono","Courier New",monospace;font-size:12px;background:var(--code-bg);color:var(--code-fg);padding:8px 10px;border-radius:8px;white-space:pre-wrap;word-break:break-word;margin:6px 0}
.rec{color:#065F46;background:#ECFDF5;border-left:3px solid #10B981;padding:6px 10px;border-radius:6px;margin-top:6px}
@media (prefers-color-scheme:dark){.rec{color:#A7F3D0;background:#0B2A22}}
.err{color:#991B1B;background:#FEF2F2;border-left:3px solid #DC2626;padding:6px 10px;border-radius:6px;margin:6px 12px}
@media (prefers-color-scheme:dark){.err{color:#FECACA;background:#2A1013}}
.more{padding:8px 12px 8px 30px;color:var(--fg3);font-size:12px}
.empty{padding:24px;text-align:center;color:var(--fg3)}
.footer{margin-top:26px;font-size:11px;color:var(--fg3);text-align:center}
@media (max-width:1100px){.kpis{grid-template-columns:repeat(3,1fr)}}
@media (max-width:900px){.two{grid-template-columns:1fr}}
@page{size:A4;margin:12mm}
@media print{:root{--bg:#fff;--panel:#fff;--panel2:#F8FAFC}.tabs,.toolbar,.btn{display:none}.panel[hidden]{display:block}.page{padding:0;max-width:none}details.grp{break-inside:auto}details.f{break-inside:avoid}.kpis{grid-template-columns:repeat(6,1fr)}}
"""

# Rendered in the browser from the embedded JSON: one accordion group per object (or rule),
# rows created only when a group is opened so very large reports stay fast.
SCRIPT = r"""
(function(){
const D=JSON.parse(document.getElementById('report-data').textContent);
const SEV=['critical','high','medium','low','info'];
const SL={critical:'Kritik',high:'Yüksek',medium:'Orta',low:'Düşük',info:'Bilgi'};
const SC=D.colors, PAGE=200;
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const rules={}; D.rules.forEach(r=>rules[r.code]=r);
const state={q:'',sev:new Set(),by:'object'};
// tabs
document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('.tab').forEach(x=>x.setAttribute('aria-selected',x===t));
  document.querySelectorAll('.panel').forEach(p=>p.hidden=p.id!==t.dataset.panel);
}));
const box=document.getElementById('groups'), info=document.getElementById('fcount');
function filtered(){
  const q=state.q.toLocaleLowerCase('tr');
  return D.findings.filter(f=>(!state.sev.size||state.sev.has(f.s)) &&
    (!q||(D.objects[f.o].label+' '+f.r+' '+(rules[f.r]?rules[f.r].name:'')+' '+f.m+' '+f.sn).toLocaleLowerCase('tr').includes(q)));
}
function counts(list){const c={};list.forEach(f=>c[f.s]=(c[f.s]||0)+1);
  return SEV.filter(s=>c[s]).map(s=>`<span class="cnt" style="background:${SC[s]}" title="${SL[s]}">${c[s]}</span>`).join('');}
function row(f){
  const r=rules[f.r]||{name:f.r};
  const line=f.l?`Satır ${f.l}`:'Nesne geneli';
  const second=state.by==='object'?esc(f.r):esc(D.objects[f.o].label);
  return `<details class="f"><summary><span class="badge" style="background:${SC[f.s]}">${SL[f.s]}</span>`+
    `<span class="code" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${second}</span>`+
    `<span class="muted">${line}</span><span class="fmsg">${esc(f.m||r.name)}</span></summary>`+
    `<div class="fbody"><div><b>${esc(f.r)}</b> · ${esc(r.name)}${state.by==='rule'?'':''} · <span class="muted">${esc(D.objects[f.o].label)}</span></div>`+
    (f.sn?`<pre>${esc(f.sn)}</pre>`:'')+(f.m?`<div>${esc(f.m)}</div>`:'')+
    (r.recommendation?`<div class="rec"><b>Öneri:</b> ${esc(r.recommendation)}</div>`:'')+`</div></details>`;
}
function fill(det,items){
  const body=det.querySelector('.rows'); if(body.dataset.done) return;
  let shown=0; const add=()=>{body.querySelector('.more')?.remove();
    body.insertAdjacentHTML('beforeend',items.slice(shown,shown+PAGE).map(row).join('')); shown+=PAGE;
    if(shown<items.length){const m=document.createElement('div');m.className='more';
      m.innerHTML=`${items.length-shown} bulgu daha · <button class="btn">Göster</button>`;
      m.querySelector('button').onclick=add; body.appendChild(m);} };
  add(); body.dataset.done='1';
}
function render(){
  const list=filtered(); const groups=new Map();
  list.forEach(f=>{const k=state.by==='object'?f.o:f.r; if(!groups.has(k)) groups.set(k,[]); groups.get(k).push(f);});
  const keys=[...groups.keys()].sort((a,b)=>groups.get(b).length-groups.get(a).length);
  info.textContent=`${list.length.toLocaleString('tr-TR')} / ${D.findings.length.toLocaleString('tr-TR')} bulgu · ${keys.length} grup`;
  if(!keys.length){box.innerHTML='<div class="empty">Filtreye uyan bulgu yok.</div>';return;}
  box.innerHTML=keys.map((k,i)=>{const items=groups.get(k);
    const title=state.by==='object'?`<span class="code">${esc(D.objects[k].label)}</span> <span class="muted">${esc(D.objects[k].type)}</span>`
      :`<span class="code">${esc(k)}</span> <span class="muted">${esc(rules[k]?rules[k].name:'')}</span>`;
    return `<details class="grp" data-i="${i}"><summary><span class="chev">▶</span><span class="gtitle">${title}</span>`+
      `<span class="counts">${counts(items)}</span><span class="total">${items.length}</span></summary><div class="rows"></div></details>`;}).join('');
  box.querySelectorAll('details.grp').forEach((d,i)=>{const items=groups.get(keys[i]);
    items.sort((a,b)=>SEV.indexOf(a.s)-SEV.indexOf(b.s)||(a.l||0)-(b.l||0));
    d.addEventListener('toggle',()=>{if(d.open) fill(d,items);});});
}
document.getElementById('q').addEventListener('input',e=>{state.q=e.target.value;render();});
document.querySelectorAll('[data-sev]').forEach(b=>b.addEventListener('click',()=>{
  const s=b.dataset.sev; state.sev.has(s)?state.sev.delete(s):state.sev.add(s); b.setAttribute('aria-pressed',state.sev.has(s)); render();}));
document.getElementById('by').addEventListener('change',e=>{state.by=e.target.value;render();});
document.getElementById('expand').addEventListener('click',()=>box.querySelectorAll('details.grp').forEach(d=>d.open=true));
document.getElementById('collapse').addEventListener('click',()=>box.querySelectorAll('details').forEach(d=>d.open=false));
document.getElementById('print').addEventListener('click',()=>window.print());
window.addEventListener('beforeprint',()=>{box.querySelectorAll('details.grp').forEach(d=>{d.open=true;});
  document.querySelectorAll('.panel details').forEach(d=>d.open=true);
  box.querySelectorAll('.more button').forEach(b=>{while(b.isConnected) b.click();});});
render();
})();
"""


def _describe_query(query: dict) -> str:
    """One readable line for a wizard pool query (filters are AND-combined)."""
    bits: list[str] = []
    if query.get("databases"):
        bits.append("Veritabanı: " + ", ".join(map(str, query["databases"])))
    if query.get("schemas"):
        bits.append("Şema: " + ", ".join(map(str, query["schemas"])))
    if query.get("types"):
        bits.append("Tip: " + ", ".join(TYPE_LABELS.get(str(t), str(t)) for t in query["types"]))
    for label, start, end in (("Oluşturma", "created_from", "created_to"), ("Değiştirme", "modified_from", "modified_to")):
        if query.get(start) or query.get(end):
            bits.append(f"{label}: {query.get(start) or '…'} – {query.get(end) or '…'}")
    if query.get("search"):
        bits.append(f"Ad: “{query['search']}”")
    text = " · ".join(bits) or "Filtresiz (tüm nesneler)"
    if "matched" in query or "added" in query:
        text += f"  ({query.get('matched', '?')} eşleşti, {query.get('added', '?')} eklendi)"
    return text


def _filter_rows(filters: dict) -> list[tuple[str, str]]:
    """Readable key/value rows for both the wizard's filter record and plain object queries."""
    rows: list[tuple[str, str]] = []
    for key, value in filters.items():
        if key in ("group_ids", "rule_ids"):
            continue  # the rule set is listed in the Kurallar tab
        if key == "connection":
            rows.append(("Bağlantı", str(value)))
        elif key == "queries" and isinstance(value, list):
            for i, query in enumerate(value, 1):
                rows.append((f"Havuz sorgusu {i}" if len(value) > 1 else "Havuz sorgusu",
                             _describe_query(query) if isinstance(query, dict) else str(query)))
        else:
            rows.append((FILTER_LABELS.get(key, key), _filter_value(value)))
    return rows


def _json_for_script(data: object) -> str:
    """JSON that is safe inside <script type=application/json> (no closing tag / comment opener)."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return text.replace("</", "<\\/").replace("<!--", "<\\!--")


def render_html(analysis: models.Analysis, findings: list[models.Finding]) -> str:
    objects = list(analysis.objects)
    rules = list(analysis.rules)
    severity_counts = Counter(f.severity for f in findings)
    total = len(findings)
    by_rule = Counter(f.rule_code for f in findings)
    objects_by_rule: dict[str, Counter[int]] = defaultdict(Counter)
    by_object: dict[int, Counter[str]] = defaultdict(Counter)
    for f in findings:
        objects_by_rule[f.rule_code][f.object_id] += 1
        by_object[f.object_id][f.severity] += 1
    object_by_id = {o.id: o for o in objects}
    done_objects = sum(1 for o in objects if o.status == "done")
    error_objects = sum(1 for o in objects if o.status == "error")
    objects_with_findings = sum(1 for o in objects if by_object.get(o.id))

    parts: list[str] = [
        "<!doctype html><html lang='tr'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{_e(analysis.name)} - DWH Code Review Raporu</title>",
        f"<style>{CSS}</style></head><body><div class='page'>",
        "<div class='header'><div>",
        "<div class='brand'>DWH Code Review · Analiz Raporu</div>",
        f"<h1>{_e(analysis.name)}</h1>",
        f"<div class='muted'>Analiz #{analysis.id} · {_e(analysis.connection_name or '-')} · "
        f"Rapor tarihi {_e(_dt(utcnow()))}</div>",
        "<div class='muted'>İstisna nedeniyle gizlenen bulgu: "
        f"{_e(analysis.suppressed_count or 0)}</div>",
        "</div><div style='display:flex;gap:8px;align-items:center'>",
        f"<span class='status'>{_e(STATUS_LABELS.get(analysis.status, analysis.status))}</span>",
        "<button class='btn' id='print'>Yazdır / PDF</button></div>",
        "</div>",
    ]

    # KPI cards
    cards = [
        ("Nesne", len(objects)),
        ("Kural", len(rules)),
        ("Kontrol", f"{analysis.completed_checks} / {analysis.total_checks}"),
        ("Bulgu", total),
        ("Bulgulu nesne", objects_with_findings),
        ("Süre", _duration(duration_ms(analysis))),
    ]
    parts.append("<div class='kpis'>")
    for key, value in cards:
        parts.append(f"<div class='card kpi'><div class='v'>{_e(value)}</div><div class='k'>{_e(key)}</div></div>")
    parts.append("</div>")

    parts.append(
        "<nav class='tabs' role='tablist'>"
        "<button class='tab' role='tab' aria-selected='true' data-panel='p-summary'>Özet</button>"
        f"<button class='tab' role='tab' aria-selected='false' data-panel='p-findings'>Bulgular<span class='n'>{total}</span></button>"
        f"<button class='tab' role='tab' aria-selected='false' data-panel='p-rules'>Kurallar<span class='n'>{len(rules)}</span></button>"
        f"<button class='tab' role='tab' aria-selected='false' data-panel='p-objects'>Nesneler<span class='n'>{len(objects)}</span></button>"
        "</nav>"
    )

    # ---- Özet -------------------------------------------------------------------------------
    parts.append("<section class='panel' id='p-summary'>")
    parts.append("<div class='card' style='margin-bottom:12px'><h2>Önem Dağılımı</h2><div class='stack'>")
    for severity in SEVERITIES:
        count = severity_counts.get(severity, 0)
        if count:
            parts.append(f"<span title='{_e(SEVERITY_LABELS[severity])}: {count}' "
                         f"style='width:{count * 100 / max(total, 1):.3f}%;background:{SEVERITY_COLORS[severity]}'></span>")
    parts.append("</div><div class='legend'>")
    for severity in SEVERITIES:
        parts.append(f"<span><span class='dot' style='background:{SEVERITY_COLORS[severity]}'></span>"
                     f"{_e(SEVERITY_LABELS[severity])} <b>{severity_counts.get(severity, 0)}</b></span>")
    parts.append("</div></div>")

    parts.append("<div class='two'><div class='card'><h2>Genel Bilgiler</h2><table class='kv'>")
    info = [
        ("Bağlantı", analysis.connection_name or "-"),
        ("Oluşturulma", _dt(analysis.created_at)),
        ("Başlangıç", _dt(analysis.started_at)),
        ("Bitiş", _dt(analysis.finished_at)),
        ("Süre", _duration(duration_ms(analysis))),
        ("Durum", STATUS_LABELS.get(analysis.status, analysis.status)),
        ("Başarılı / hatalı nesne", f"{done_objects} / {error_objects}"),
    ]
    if analysis.error:
        info.append(("Hata", analysis.error))
    for key, value in info:
        parts.append(f"<tr><td>{_e(key)}</td><td>{_e(value)}</td></tr>")
    parts.append("</table></div>")

    filters = _filter_rows(analysis.filters or {})
    parts.append("<div class='card'><h2>Filtreler</h2>")
    if filters:
        parts.append("<table class='kv'>")
        for key, value in filters:
            parts.append(f"<tr><td>{_e(key)}</td><td>{_e(value)}</td></tr>")
        parts.append("</table>")
    else:
        parts.append("<p class='muted'>Filtre bilgisi yok.</p>")
    parts.append("</div></div>")

    # Top rules / top objects (the full lists live in their own tabs)
    top_rules = [r for r in sorted(rules, key=lambda r: -by_rule.get(r.code, 0)) if by_rule.get(r.code)][:8]
    top_objects = sorted((o for o in objects if by_object.get(o.id)),
                         key=lambda o: -sum(by_object[o.id].values()))[:8]
    parts.append("<div class='two'><div class='card'><h2>En çok bulgu üreten kurallar</h2><table>")
    for rule in top_rules:
        parts.append(f"<tr><td>{_badge(rule.severity)}</td><td class='code'>{_e(rule.code)}</td>"
                     f"<td>{_e(rule.name)}</td><td class='num'><b>{by_rule[rule.code]}</b></td></tr>")
    if not top_rules:
        parts.append("<tr><td class='muted'>Bulgu yok.</td></tr>")
    parts.append("</table></div><div class='card'><h2>En çok bulgu içeren nesneler</h2><table>")
    for obj in top_objects:
        parts.append(f"<tr><td class='code'>{_e(obj.label)}</td><td class='muted'>"
                     f"{_e(TYPE_LABELS.get(obj.type, obj.type))}</td>"
                     f"<td class='num'><b>{sum(by_object[obj.id].values())}</b></td></tr>")
    if not top_objects:
        parts.append("<tr><td class='muted'>Bulgu yok.</td></tr>")
    parts.append("</table></div></div></section>")

    # ---- Bulgular (rendered client-side from JSON) ------------------------------------------
    parts.append(
        "<section class='panel' id='p-findings' hidden><div class='toolbar'>"
        "<input type='search' id='q' placeholder='Nesne, kural, mesaj veya kod parçası ara…'>"
        + "".join(f"<button class='chip' data-sev='{s}' aria-pressed='false'>"
                  f"<span class='dot' style='background:{SEVERITY_COLORS[s]}'></span>{_e(SEVERITY_LABELS[s])}</button>"
                  for s in SEVERITIES)
        + "<select id='by'><option value='object'>Nesneye göre</option><option value='rule'>Kurala göre</option></select>"
        "<button class='btn' id='expand'>Tümünü aç</button><button class='btn' id='collapse'>Tümünü kapat</button>"
        "</div><div class='muted' id='fcount' style='margin-bottom:8px'></div><div id='groups'></div>"
    )
    errored = [o for o in objects if o.error]
    if errored:
        parts.append(f"<details class='grp' style='margin-top:12px'><summary><span class='chev'>▶</span>"
                     f"<span class='gtitle'>Hata / not içeren nesneler</span><span class='total'>{len(errored)}</span>"
                     "</summary>")
        for obj in errored:
            parts.append(f"<div class='err'><b class='mono'>{_e(obj.label)}</b> — {_e(obj.error)}</div>")
        parts.append("</details>")
    parts.append("</section>")

    # ---- Kurallar ---------------------------------------------------------------------------
    parts.append("<section class='panel' id='p-rules' hidden>")
    for rule in sorted(rules, key=lambda r: (-by_rule.get(r.code, 0), SEVERITY_ORDER.get(r.severity, 9), r.code)):
        affected = objects_by_rule.get(rule.code, Counter())
        parts.append(
            "<details class='grp'><summary><span class='chev'>▶</span>"
            f"{_badge(rule.severity)}<span class='gtitle'><span class='code'>{_e(rule.code)}</span> {_e(rule.name)}</span>"
            f"<span class='muted'>{KIND_LABELS.get(rule.kind, rule.kind)}</span>"
            f"<span class='muted' style='min-width:70px;text-align:right'>{len(affected)} nesne</span>"
            f"<span class='total'>{by_rule.get(rule.code, 0)}</span></summary><div class='fbody' style='padding-left:14px'>"
        )
        if rule.description:
            parts.append(f"<p>{_e(rule.description)}</p>")
        if rule.recommendation:
            parts.append(f"<div class='rec'><b>Öneri:</b> {_e(rule.recommendation)}</div>")
        if affected:
            parts.append("<table style='margin-top:8px'><tr><th>Etkilenen nesne</th><th class='num'>Bulgu</th></tr>")
            for object_id, count in affected.most_common(100):
                obj = object_by_id.get(object_id)
                parts.append(f"<tr><td class='code'>{_e(obj.label if obj else object_id)}</td>"
                             f"<td class='num'>{count}</td></tr>")
            if len(affected) > 100:
                parts.append(f"<tr><td class='muted' colspan='2'>… ve {len(affected) - 100} nesne daha</td></tr>")
            parts.append("</table>")
        else:
            parts.append("<p class='muted'>Bu kural bulgu üretmedi.</p>")
        parts.append("</div></details>")
    parts.append("</section>")

    # ---- Nesneler ---------------------------------------------------------------------------
    parts.append(
        "<section class='panel' id='p-objects' hidden><div class='card' style='padding:6px 8px'><table>"
        "<tr><th>Nesne</th><th>Tip</th><th>Durum</th><th class='num'>Satır</th>"
        + "".join(f"<th class='num'>{_e(SEVERITY_LABELS[s])}</th>" for s in SEVERITIES)
        + "<th class='num'>Toplam</th></tr>"
    )
    for obj in sorted(objects, key=lambda o: (-sum(by_object[o.id].values()), o.label.lower())):
        counts = by_object[obj.id]
        parts.append(
            f"<tr><td class='code'>{_e(obj.label)}</td><td>{_e(TYPE_LABELS.get(obj.type, obj.type))}</td>"
            f"<td>{_e(STATUS_LABELS.get(obj.status, obj.status))}</td><td class='num'>{obj.line_count}</td>"
            + "".join(f"<td class='num'>{counts.get(s, 0) or ''}</td>" for s in SEVERITIES)
            + f"<td class='num'><b>{sum(counts.values())}</b></td></tr>"
        )
    parts.append("</table></div></section>")

    # ---- Data + script ----------------------------------------------------------------------
    object_index = {o.id: i for i, o in enumerate(objects)}
    data = {
        "colors": SEVERITY_COLORS,
        "objects": [{"label": o.label, "type": TYPE_LABELS.get(o.type, o.type)} for o in objects],
        "rules": [{"code": r.code, "name": r.name, "recommendation": r.recommendation or ""} for r in rules],
        "findings": [
            {"o": object_index[f.object_id], "r": f.rule_code, "s": f.severity, "l": f.line,
             "sn": f.snippet or "", "m": f.message or ""}
            for f in findings if f.object_id in object_index
        ],
    }
    parts.append(f"<script type='application/json' id='report-data'>{_json_for_script(data)}</script>")
    parts.append(f"<script>{SCRIPT}</script>")
    parts.append("<div class='footer'>DWH Code Review tarafından oluşturuldu.</div>")
    parts.append("</div></body></html>")
    return "".join(parts)


def render_csv(findings: list[models.Finding], objects: dict[int, models.AnalysisObject]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(
        ["Veritabanı", "Şema", "Nesne", "Tip", "Satır", "Kural kodu", "Kural", "Önem",
         "Tür", "Kod parçası", "Açıklama", "Öneri"]
    )
    for f in findings:
        obj = objects.get(f.object_id)
        writer.writerow(
            [
                obj.database if obj else "",
                obj.schema if obj else "",
                obj.name if obj else f.object_label,
                obj.type if obj else "",
                f.line if f.line is not None else "",
                f.rule_code,
                f.rule_name,
                SEVERITY_LABELS.get(f.severity, f.severity),
                f.kind,
                f.snippet,
                f.message,
                f.recommendation,
            ]
        )
    return ("﻿" + buffer.getvalue()).encode("utf-8")
