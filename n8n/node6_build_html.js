// n8n Code node: Build self-contained HTML dashboard (no external assets).
// Input items: [0] = Format Results ({teamRows, teamSummaryRows, auditRows}).
// Output: ONE item { html }.
const d = items[0].json;
const rows = d.teamRows || [];
const summary = d.teamSummaryRows || [];
const audit = (d.auditRows || [])[0] || {};

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const gradeColor = g => (g || '').includes('A') ? '#16a34a' : (g || '').includes('B') ? '#ca8a04' : '#dc2626';
const gradeBg = g => (g || '').includes('A') ? '#dcfce7' : (g || '').includes('B') ? '#fef9c3' : '#fee2e2';

const byTeam = {};
for (const r of rows) { (byTeam[r.Team] = byTeam[r.Team] || []).push(r); }

const cards = summary.map(s => {
  const members = (byTeam[s.Team] || []).map(m =>
    `<span class="chip">${esc(m["Member Name"])} <em>${esc(m.Gender === 'Male (M)' ? 'M' : 'F')} · ${esc(m["Skill Tier"])} · ${m["Overall Skill"]}</em></span>`
  ).join('');
  return `<section class="card">
    <header style="border-color:${gradeColor(s["Fairness Grade"])}">
      <h2>${esc(s.Team)}</h2>
      <span class="grade" style="color:${gradeColor(s["Fairness Grade"])};background:${gradeBg(s["Fairness Grade"])}">${esc(s["Fairness Grade"])}</span>
    </header>
    <p class="meta">${esc(s["Gender Breakdown"])} · Avg ${s["Average Skill"]} · Total ${s["Total Skill"]} · Spread ${s["Skill Spread (StdDev)"]}</p>
    <p class="meta">Willingness avg ${s["Avg Teammate Willingness"]} · min ${s["Min Compatibility"]} · vetoes ${s["Veto Count"]} · low ${s["Low Compatibility Count"]}</p>
    <p class="meta">Weakest pair: ${esc(s["Weakest Internal Pair"])} — ${esc(s.Status)}</p>
    <div class="members">${members}</div>
  </section>`;
}).join('');

const html = `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FairMatch Teams — ${esc(audit["Overall Fairness"] || '')}</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;background:#f1f5f9;margin:0;padding:24px;color:#0f172a}
.wrap{max-width:1000px;margin:0 auto}
.banner{background:#1e3a5f;color:#fff;border-radius:12px;padding:20px 24px;margin-bottom:20px}
.banner h1{margin:0 0 8px;font-size:24px}
.banner p{margin:4px 0;opacity:.92}
.card{background:#fff;border-radius:12px;padding:18px 20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
.card header{display:flex;justify-content:space-between;align-items:center;border-left:6px solid #16a34a;padding-left:12px}
.card h2{margin:0}
.grade{font-weight:700;padding:4px 12px;border-radius:999px}
.meta{margin:6px 0;color:#334155}
.members{margin-top:10px}
.chip{display:inline-block;background:#eef2ff;border:1px solid #c7d2fe;border-radius:999px;padding:4px 10px;margin:3px;font-size:13px}
.chip em{font-style:normal;color:#475569}
footer{color:#64748b;font-size:12px;text-align:center;margin-top:16px}
</style></head><body><div class="wrap">
<div class="banner"><h1>FairMatch — Final Teams</h1>
<p>${esc(audit["Overall Fairness"] || '')} · ${esc(audit["Gender Balance"] || '')} · Skill gap ${esc(audit["Team Skill Gap (Max - Min)"] ?? '')}</p>
<p>Solver ${esc(audit["Solver Status"] || '')} · Veto violations ${esc(audit["Intra-Team Veto Violations"] ?? '')} · Generated ${esc(audit["Generated At"] || '')}</p></div>
${cards}
<footer>FairMatch v4 · run ${esc(audit["Run ID"] || '')}</footer>
</div></body></html>`;

return [{ json: { html, bytes: html.length } }];
