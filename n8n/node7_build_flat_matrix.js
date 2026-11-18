// n8n Code node: Build gap-filled flat responses matrix (auditable clean dataset).
// Input: Clean output ({flatResponses}). Output: ONE item { values }.
// Columns: Rater | Target | Type | DevOps | AI/ML | Technical | Involvement |
// Willingness | Imputed | Run ID. Imputed rows cover the 2 non-submitters.
const flat = items[0].json.flatResponses || [];
const runId = items[0].json.runId || '';
const header = [
  "Rater", "Target", "Type", "DevOps", "AI / ML", "Technical",
  "Involvement", "Willingness", "Imputed", "Run ID"
];
const values = [header, ...flat.map(r => [
  r.rater, r.target, r.rater === r.target ? "self" : "peer",
  r.devops, r.ai_ml, r.technical, r.involvement, r.willing,
  r.is_imputed ? "YES" : "NO", runId
])];
return [{ json: { values, rowCount: flat.length } }];
