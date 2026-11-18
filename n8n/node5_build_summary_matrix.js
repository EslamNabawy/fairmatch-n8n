// n8n Code node: Build single 2D values matrix for team-level summary.
// Input: Format Results output (teamSummaryRows). Output: ONE item, no individual rows.
const rows = items[0].json.teamSummaryRows || [];
const members = items[0].json.teamRows || [];
const byTeam = {};
for (const m of members) {
  (byTeam[m.Team] = byTeam[m.Team] || []).push(m["Member Name"]);
}
const header = [
  "Team", "Fairness Grade", "Team Size", "Gender Breakdown", "Members",
  "Average Skill", "Total Skill", "Skill Spread (StdDev)",
  "Avg Teammate Willingness", "Min Compatibility", "Weakest Internal Pair",
  "Veto Count", "Low Compatibility Count", "Status"
];
const values = [header, ...rows.map(r => header.map(h => (
  h === "Members" ? (byTeam[r.Team] || []).join(", ") : (r[h] ?? "")
)))];
return [{ json: { values, rowCount: rows.length } }];
