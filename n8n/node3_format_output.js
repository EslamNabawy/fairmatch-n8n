// n8n Code node: Format Beautiful, High-Impact Output Rows for Google Sheets & Excel
const input = items[0].json;
const generatedAt = new Date().toISOString();

// Sort assignments: First by Team Number (1, 2, 3, 4), then by Overall Skill descending
const sortedAssignments = [...input.assignments].sort((a, b) => {
  const teamA = parseInt(a.team_id.replace(/\D/g, ''), 10) || 0;
  const teamB = parseInt(b.team_id.replace(/\D/g, ''), 10) || 0;
  if (teamA !== teamB) return teamA - teamB;
  return (b.overall_skill || 0) - (a.overall_skill || 0);
});

const teamRows = sortedAssignments.map(a => {
  const mCount = a.team_male_count ?? 0;
  const fCount = a.team_female_count ?? 0;
  
  return {
    "Team": a.team_id,
    "Fairness Grade": `Grade ${a.fairness_grade} (${a.fairness_score}/100)`,
    "Member Name": a.member_display_name,
    "Gender": a.gender === 'M' ? 'Male (M)' : 'Female (F)',
    "Skill Tier": a.tier_label || `Tier ${a.tier}`,
    "Overall Skill": Number((a.overall_skill || 0).toFixed(2)),
    "DevOps Skill": Number((a.devops_skill || 0).toFixed(2)),
    "AI / ML Skill": Number((a.ai_ml_skill || 0).toFixed(2)),
    "Technical Skill": Number((a.technical_skill || 0).toFixed(2)),
    "Involvement": Number((a.involvement_skill || 0).toFixed(2)),
    "Team Average Skill": Number((a.team_average_skill || 0).toFixed(2)),
    "Team Total Skill": Number((a.team_total_skill || 0).toFixed(2)),
    "Team Gender Ratio": `${mCount}M / ${fCount}F`,
    "Avg Team Willingness": Number((a.team_avg_willingness ?? 3.0).toFixed(2)),
    "Min Team Compatibility": Number((a.team_worst_willingness ?? 3.0).toFixed(2)),
    "Weakest Team Pair": a.weakest_pair || 'N/A',
    "Intra-Team Vetoes": (a.team_veto_count ?? 0) === 0 ? "0 (Veto-Free)" : `${a.team_veto_count} (NEEDS REVIEW)`,
    "Status Flags": a.status_flags || 'OPTIMAL',
    "Run ID": a.run_id,
    "Generated At": generatedAt,
  };
});

// Summary rows for a clean overview / dashboard
const teamSummaryRows = (input.team_metrics || []).map(m => ({
  "Team": m.team_id,
  "Fairness Grade": `Grade ${m.fairness_grade} (${m.fairness_score}/100)`,
  "Team Size": m.team_size,
  "Gender Breakdown": `${m.team_male_count} Males / ${m.team_female_count} Females`,
  "Average Skill": Number(m.team_average_skill.toFixed(2)),
  "Total Skill": Number(m.team_total_skill.toFixed(2)),
  "Skill Spread (StdDev)": Number(m.team_spread.toFixed(2)),
  "Avg Teammate Willingness": Number(m.team_avg_willingness.toFixed(2)),
  "Min Compatibility": Number(m.team_worst_willingness.toFixed(2)),
  "Weakest Internal Pair": m.weakest_pair,
  "Veto Count": m.team_veto_count,
  "Low Compatibility Count": m.team_low_pair_count,
  "Status": (m.status_flags || 'OPTIMAL').split(', ').join(' • ')
}));

// Python float repr parity: ints print as "5.0", others as-is
const pyFloat = v => (typeof v === 'number' && Number.isInteger(v)) ? `${v}.0` : String(v);
const fmtMag = (level, v) => (['L1', 'L2', 'L5', 'L6'].includes(level) ? pyFloat(v) : String(v));

const reviewRows = [];
for (const s of (input.audit.swap_log || [])) {
  reviewRows.push({
    Type: 'swap_made',
    Detail: `Pass ${s.pass} Teams ${s.teams[0]}<->${s.teams[1]} ${s.swapped[0]}<->${s.swapped[1]} level ${s.level} ${s.before}->${s.after}`,
  });
}
for (const tr of (input.audit.tier_relaxations || [])) {
  reviewRows.push({
    Type: 'tier_relaxation',
    Detail: `Team ${tr.team} tier ${tr.tier_substituted}->adj ${tr.adjacent_tier_used} ${tr.person_placed} : ${tr.reason}`,
  });
}
for (const rv of (input.audit.remaining || [])) {
  reviewRows.push({
    Type: 'remaining_soft_violation',
    Detail: `${rv.level} magnitude ${fmtMag(rv.level.split('_')[0], rv.magnitude)}`,
  });
}
for (const d of (input.diagnostics.disagreements || [])) {
  reviewRows.push({
    Type: 'disagreement_flag',
    Detail: `${d.person} ${d.dim} self ${pyFloat(d.self)} peer ${pyFloat(d.peer)} gap ${pyFloat(d.gap)} ${d.flag}`,
  });
}
for (const rc of (input.diagnostics.rater_consistency || [])) {
  reviewRows.push({
    Type: 'rater_consistency_flag',
    Detail: `${rc.rater} corr ${rc.correlation} n ${rc.n}`,
  });
}
for (const lf of (input.diagnostics.low_flags || [])) {
  reviewRows.push({ Type: 'low_confidence', Detail: lf });
}
reviewRows.push({ Type: 'levels', Detail: JSON.stringify(input.audit.levels) });
reviewRows.push({ Type: 'status', Detail: input.audit.solver_status });

const auditRows = [{
  "Run ID": input.run_id,
  "Overall Fairness": `Score ${input.audit.overall_fairness_score}/100 (Grade ${input.audit.overall_fairness_grade})`,
  "Solver Status": input.audit.solver_status,
  "Solver Version": input.audit.solver_version,
  "Total Teams Formed": input.audit.team_count,
  "Total Participants": input.audit.total_members,
  "Gender Balance": `${input.audit.total_males} Males / ${input.audit.total_females} Females`,
  "Team Skill Gap (Max - Min)": Number((input.audit.levels.L5 || 0).toFixed(2)),
  "Global Average Skill": Number((input.audit.global_avg_skill || 0).toFixed(2)),
  "Intra-Team Veto Violations": input.audit.levels.L2V,
  "Intra-Team Low Pairs": input.audit.levels.L2C,
  "Self-Disagreements Corrected": (input.diagnostics.disagreements || []).length,
  "Non-Submitters Imputed": (input.diagnostics.missing_submitters || []).length,
  "Generated At": generatedAt,
}];

return [{
  json: {
    teamRows,
    teamSummaryRows,
    auditRows,
    reviewRows,
    teamMetrics: input.team_metrics,
    auditSummary: input.audit,
    diagnostics: input.diagnostics,
  }
}];
