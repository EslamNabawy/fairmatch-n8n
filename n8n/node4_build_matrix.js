// n8n Code node: Build single 2D values matrix for one-shot Sheets update/append
// Input: Format Results output (teamRows). Output: ONE item with full matrix.
const rows = items[0].json.teamRows || [];
const header = [
  "Team", "Fairness Grade", "Member Name", "Gender", "Skill Tier",
  "Overall Skill", "DevOps Skill", "AI / ML Skill", "Technical Skill", "Involvement",
  "Team Average Skill", "Team Total Skill", "Team Gender Ratio",
  "Avg Team Willingness", "Min Team Compatibility", "Weakest Team Pair",
  "Intra-Team Vetoes", "Status Flags", "Run ID", "Generated At"
];
const values = [header, ...rows.map(r => header.map(h => (r[h] ?? "")))];
return [{ json: { values, rowCount: rows.length } }];
