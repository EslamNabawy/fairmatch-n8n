// n8n Code node: FairMatch PUBLIC team-announcement page.
// Privacy rule: team-level aggregates only. Never renders pair scores,
// weakest pairs, veto/low participants, grades, run IDs, or debug notes.
// Input: merged sheet rows - detail (have "Member Name") + summary (have "Team Size").
// Output: ONE item { html }. Missing/invalid values hide their metric — never NaN.
const rows = items.map(i => i.json);

// Latest run only (append-mode sheets accumulate history).
const runIds = [...new Set(rows.map(r => r["Run ID"]).filter(Boolean))].sort();
const latest = runIds.length ? runIds[runIds.length - 1] : null;
const cur = latest ? rows.filter(r => !r["Run ID"] || r["Run ID"] === latest) : rows;
const teamRows = cur.filter(r => r["Member Name"]);
// Summary rows carry no Run ID: last row per team wins (append-only order).
const seenTeams = new Set();
const summaryAll = cur.filter(r => r["Team Size"] && !r["Member Name"]).reverse()
  .filter(s => !seenTeams.has(s.Team) && (seenTeams.add(s.Team), true)).reverse();

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
// Safe 2-decimal number or null when missing/invalid — never renders NaN.
const num2 = v => {
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(2) : null;
};
// "3 Males / 3 Females" -> "3 Male · 3 Female"; null when unparseable.
const longGender = g => {
  const m = String(g || '').match(/(\d+)\s*Males?\s*\/\s*(\d+)\s*Females?/i);
  return m ? `${m[1]} Male · ${m[2]} Female` : null;
};

const byTeam = {};
for (const r of teamRows) { (byTeam[r.Team] = byTeam[r.Team] || []).push(r); }
// Render only teams that actually contain members, in numeric order.
const teamOrder = summaryAll
  .filter(s => (byTeam[s.Team] || []).length > 0)
  .sort((a, b) => (parseInt(String(a.Team).replace(/\D/g, ''), 10) || 0) -
                   (parseInt(String(b.Team).replace(/\D/g, ''), 10) || 0));
const totalMembers = teamOrder.reduce((n, s) => n + (byTeam[s.Team] || []).length, 0);
const sizes = teamOrder.map(s => (byTeam[s.Team] || []).length);
const evenSizes = sizes.length > 0 && sizes.every(n => n === sizes[0]);

// Generated date from latest run id ("run-2026-09-24T...") -> "September 24, 2026".
let dateLine = '';
{
  const m = String(latest || '').match(/(\d{4})-(\d{2})-(\d{2})/);
  if (m) {
    const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
    if (!isNaN(d)) dateLine = `<p class="stamp"><strong>✓ Finalized · ${d.toLocaleDateString('en-US', { timeZone: 'UTC', month: 'long', day: 'numeric', year: 'numeric' })}</strong></p>`;
  }
}

// Search index for Find-Your-Team (partial, case-insensitive, names only).
const searchIndex = [];
for (const s of teamOrder) {
  for (const m of (byTeam[s.Team] || [])) searchIndex.push({ name: m["Member Name"], team: s.Team });
}

const teamCard = s => {
  const members = byTeam[s.Team] || [];
  const gender = longGender(s["Gender Breakdown"]);
  const avgSkill = num2(s["Average Skill"]);
  const compat = num2(s["Avg Teammate Willingness"]);
  const spreadRaw = Number(s["Skill Spread (StdDev)"]);
  const spread = num2(s["Skill Spread (StdDev)"]);
  const chips = members.map(m =>
    `<span class="chip" data-name="${esc(String(m["Member Name"]).toLowerCase())}">${esc(m["Member Name"])}</span>`
  ).join('');
  const teamNum = esc(String(s.Team).replace(/\D/g, '') || s.Team);
  const spreadPos = Number.isFinite(spreadRaw)
    ? Math.max(0, Math.min(100, (spreadRaw / 0.6) * 100)).toFixed(0) : null;
  return `<section class="card" id="team-${teamNum}" data-team="${esc(s.Team)}" aria-label="${esc(s.Team)}">
    <h2 class="team-anchor">TEAM ${teamNum}</h2>
    <p class="team-count"><span aria-hidden="true">👥</span> ${members.length} Members</p>
    <div class="metrics">
      ${gender ? `<div class="metric"><span class="metric-val"><span class="metric-ico" aria-hidden="true">🧑‍🤝‍🧑</span> ${esc(gender)}</span><span class="metric-label">Team Composition</span></div>` : ''}
      ${avgSkill !== null ? `<div class="metric"><span class="metric-val"><span class="metric-ico" aria-hidden="true">⭐</span> ${avgSkill} / 5</span><span class="metric-label">Average Skill</span></div>` : ''}
      ${compat !== null ? `<div class="metric"><span class="metric-val"><span class="metric-ico" aria-hidden="true">🤝</span> ${compat} / 5</span><span class="metric-label">Team Compatibility</span></div>` : ''}
      ${spread !== null ? `<div class="metric"><span class="metric-val"><span class="metric-ico" aria-hidden="true">📏</span> ${spread}</span><span class="metric-label">Skill Spread</span></div>` : ''}
    </div>
    ${spreadPos !== null ? `<div class="spreadbar" role="img" aria-label="Skill spread ${spread}: lower means more even levels"><span>↔ More even</span><div class="track"><div class="dot" style="left:${spreadPos}%"></div></div><span>More variation ↕</span></div>
    <p class="spread-note">Lower spread means team skill levels are closer together.</p>` : ''}
    <h3>👋 Meet Your Teammates</h3>
    <div class="members">${chips}</div>
  </section>`;
};

const cards = teamOrder.map(teamCard).join('');
const subtitle = evenSizes
  ? `${totalMembers} members · ${teamOrder.length} teams · ${sizes[0]} members per team`
  : `${totalMembers} members · ${teamOrder.length} teams`;
const distBlocks = teamOrder.map(s => {
  const n = (byTeam[s.Team] || []).length;
  return `<div class="dist-block"><strong>${esc(s.Team)}</strong><span>👥 ${n} members</span></div>`;
}).join('');
const ogDesc = esc(subtitle);

const html = `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FairMatch — Final Team Assignments</title>
<meta property="og:title" content="FairMatch 🎯 Final Teams Are Ready">
<meta property="og:description" content="${ogDesc}">
<meta property="og:type" content="website">
<style>
*{box-sizing:border-box}
body{font-family:Segoe UI,Arial,sans-serif;background:#f4f6fb;margin:0;padding:20px;color:#0f172a;line-height:1.5}
.wrap{max-width:1000px;margin:0 auto}
.hero{background:#1e3a5f;color:#fff;border-radius:16px;padding:28px 24px;margin-bottom:20px;text-align:center}
.hero h1{margin:0 0 8px;font-size:28px}
.hero .sub{font-size:17px;margin:6px 0}
.hero .lede{max-width:640px;margin:12px auto 0;opacity:.94;font-size:15px}
.stamp{font-size:13px;opacity:.8;margin:10px 0 0}
.find{position:sticky;top:0;z-index:5;background:#fff;border-radius:12px;padding:14px 16px;margin-bottom:16px;box-shadow:0 2px 8px rgba(0,0,0,.08)}
.find input{width:100%;font-size:17px;padding:12px 14px;border-radius:10px;border:1px solid #cbd5e1}
.find-result{margin:10px 0 0;font-size:17px;display:none}
.overview{background:#fff;border-radius:12px;padding:16px 20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.overview h2{margin:0 0 8px}
.dist-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:10px}
@media(min-width:760px){.dist-grid{grid-template-columns:repeat(4,1fr)}}
.dist-block{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px;text-align:center}
.dist-block strong{display:block;font-size:16px}
.dist-block span{color:#475569;font-size:14px}
.grid{display:grid;gap:16px}
@media(min-width:760px){.grid{grid-template-columns:1fr 1fr}}
.card{background:#fff;border-radius:16px;padding:22px;box-shadow:0 2px 10px rgba(0,0,0,.07);border-top:6px solid #1e3a5f;scroll-margin-top:90px}
.card.flash{outline:3px solid #1e3a5f}
.team-anchor{margin:0;font-weight:800;letter-spacing:2px;color:#1e3a5f;font-size:30px}
.team-count{margin:2px 0 4px;color:#475569;font-size:16px}
.card h3{margin:14px 0 8px;font-size:17px}
.spreadbar{display:flex;align-items:center;gap:8px;font-size:12px;color:#64748b;margin:4px 0 0}
.spreadbar .track{flex:1;position:relative;height:6px;background:#e2e8f0;border-radius:999px}
.spreadbar .dot{position:absolute;top:50%;width:12px;height:12px;background:#1e3a5f;border-radius:50%;transform:translate(-50%,-50%)}
.spread-note{font-size:13px;color:#475569;margin:4px 0 0}
.share-row{display:flex;gap:10px;margin-top:12px;flex-wrap:wrap}
.share-row button{font-size:15px;padding:10px 16px;border-radius:10px;border:1px solid #cbd5e1;background:#fff;color:#1e3a5f;font-weight:700;cursor:pointer}
.share-row button:active{background:#eef2ff}
a:focus-visible,button:focus-visible,input:focus-visible{outline:3px solid #1e3a5f;outline-offset:2px}
.fairness-note{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:10px 14px;margin:12px auto 0;max-width:640px;font-size:14px;color:#14532d}
.metrics{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0}
.metric{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px;text-align:center}
.metric-val{display:block;font-size:19px;font-weight:700}
.metric-ico{font-size:15px}
.metric-label{display:block;font-size:12px;color:#64748b;margin-top:2px}
.members{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
.chip{background:#eef2ff;border:1px solid #c7d2fe;border-radius:999px;padding:8px 14px;font-size:15px}
.chip.hit{background:#dbeafe;border-color:#1e3a5f;font-weight:700}
.flat{background:#fff;border-radius:16px;padding:22px;box-shadow:0 2px 10px rgba(0,0,0,.07);margin-top:4px}
.flat h2{margin:0 0 8px;font-size:20px}
.flat h3{margin:14px 0 4px;font-size:16px}
.flat p{color:#334155;font-size:14px;margin:6px 0}
.closing{text-align:center;margin:26px 10px 10px;font-size:16px}
</style></head><body><div class="wrap">
<div class="hero"><h1>🎯 Your FairMatch Teams Are Ready</h1>
<p class="sub"><strong>👥 ${esc(String(totalMembers))} members · 🧩 ${teamOrder.length} teams · ${evenSizes ? esc(String(sizes[0])) + ' members per team' : 'mixed team sizes'}</strong></p>
<p class="lede">Teams were formed by balancing skills, teammate willingness, team composition, and compatibility constraints.</p>
<p class="fairness-note"><strong>⚖️ Same rules · Same constraints · Balanced across the cohort</strong></p>
<div class="share-row"><button type="button" id="shareBtn" aria-label="Share this page">↗️ Share</button><button type="button" id="copyBtn" aria-label="Copy link to this page">📋 Copy Link</button></div>
${dateLine}</div>
<div class="find"><label for="findInput"><strong>🔎 Find Your Team</strong></label>
<input id="findInput" type="search" placeholder="Enter your name..." autocomplete="off" aria-label="Search your name to find your team">
<p class="find-result" id="findResult" aria-live="polite"></p></div>
<div class="overview"><h2>🗂️ Team Overview</h2>
<p><strong>${teamOrder.length} Teams</strong> · <strong>${totalMembers} Members</strong>${evenSizes ? ` · <strong>${sizes[0]} Members / Team</strong>` : ''}</p>
<div class="dist-grid">${distBlocks}</div></div>
<div class="grid">${cards}</div>
<div class="flat">
<h2>⚙️ How FairMatch Works</h2>
<h3>🤝 Willingness</h3><p>Each participant's willingness to work with others is considered when building teams. The displayed <strong>Team Compatibility</strong> is a team-level average, not an evaluation of any individual.</p>
<h3>🚫 Veto Constraint</h3><p>A veto is a strong incompatibility signal. FairMatch treats these as a hard constraint and avoids placing vetoed participants on the same team.</p>
<h3>⚖️ Skill Balance</h3><p>Skills are distributed so that the teams remain as close as possible to the overall cohort skill level. The <strong>Average Skill</strong> shown on each team represents the team's overall average. It does not indicate that one team is "better."</p>
<h3>📏 Skill Spread</h3><p><strong>Skill Spread</strong> measures how different the skill levels are within a team.</p><p>Lower spread = skill levels are closer together. Higher spread = there is more variation in skill levels. It describes the team as a whole.</p>
<h3>👥 Team Size &amp; Composition</h3><p>Teams are kept at the required size and follow the predefined composition constraints.</p>
<h2>Understanding the Team Numbers</h2>
<h3>Average Skill</h3><p>The average skill level of the team on a <strong>1–5 scale</strong>.</p>
<h3>Team Compatibility</h3><p>The team's overall average willingness/compatibility score on a <strong>1–5 scale</strong>.</p><p>Team Compatibility represents the overall willingness/compatibility level across the team.</p>
<h3>Skill Spread</h3><p>A measure of how evenly skill levels are distributed inside the team.</p>
<h3>Gender Distribution</h3><p>The team's gender composition according to the predefined team constraints.</p>
<p><strong>ℹ️ These numbers describe team balance. They are not a ranking of people or teams.</strong></p>
</div>
<div class="closing"><p><strong>🎯 Teams Are Final</strong></p>
<p>The teams were created using the same balancing rules across the full cohort, taking skills, willingness, compatibility constraints, team size, and composition into account.</p>
<p>The goal is simple: give everyone a fair starting point to collaborate, learn, and build together.</p>
<p><strong>✓ All teams finalized successfully</strong></p>
<p><strong>FairMatch · Final Team Assignments</strong></p></div>
</div>
<script>
(function(){
var shareBtn = document.getElementById('shareBtn');
var copyBtn = document.getElementById('copyBtn');
function copyLink(done) {
  var url = window.location.href;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(url).then(done, done);
  } else {
    var ta = document.createElement('textarea');
    ta.value = url;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(ta);
    done();
  }
}
if (shareBtn) shareBtn.addEventListener('click', function(){
  var data = { title: document.title, text: 'FairMatch — Final Team Assignments', url: window.location.href };
  if (navigator.share) { navigator.share(data).catch(function(){}); }
  else { copyLink(function(){ shareBtn.textContent = '✓ Link copied'; }); }
});
if (copyBtn) copyBtn.addEventListener('click', function(){
  copyLink(function(){ copyBtn.textContent = '✓ Link copied'; });
});
var index = ${JSON.stringify(searchIndex.map(e => ({ n: String(e.name || '').toLowerCase(), t: e.team })))};
var input = document.getElementById('findInput');
var result = document.getElementById('findResult');
input.addEventListener('input', function(){
  var q = input.value.trim().toLowerCase();
  document.querySelectorAll('.chip.hit').forEach(function(c){c.classList.remove('hit');});
  document.querySelectorAll('.card.flash').forEach(function(c){c.classList.remove('flash');});
  if (!q) { result.style.display = 'none'; return; }
  var hits = index.filter(function(e){ return e.n.indexOf(q) !== -1; });
  var teams = {};
  hits.forEach(function(h){ teams[h.t] = true; });
  var names = Object.keys(teams);
  if (!names.length) {
    result.style.display = 'block';
    result.textContent = 'No match found — try part of your first or last name.';
    return;
  }
  names.forEach(function(t){
    document.querySelectorAll('.chip').forEach(function(c){
      var card = c.closest('.card');
      if (card && card.getAttribute('data-team') === t) {
        if (c.getAttribute('data-name').indexOf(q) !== -1) c.classList.add('hit');
      }
    });
  });
  var first = document.querySelector('[data-team="' + names[0].replace(/"/g, '') + '"]');
  result.style.display = 'block';
  if (names.length === 1) {
    result.innerHTML = "🎉 You're on <strong>" + names[0].replace(/</g, '&lt;') + "</strong>";
  } else {
    result.innerHTML = "Matches in <strong>" + names.map(function(t){ return t.replace(/</g, '&lt;'); }).join(', ') + "</strong>";
  }
  if (first) {
    first.classList.add('flash');
    first.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
});
})();
</script>
</body></html>`;

return [{ json: { html, bytes: html.length } }];
