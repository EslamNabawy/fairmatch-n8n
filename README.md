# FairMatch for n8n

FairMatch is a self-contained n8n pipeline for forming balanced teams from
survey responses. It cleans and deduplicates submissions, normalizes rating
scales, imputes missing respondents, builds pairwise willingness/veto matrices,
and assigns people with a deterministic lexicographic solver.

## Pipeline

```text
raw sheet rows
  -> clean + normalize
  -> solver
  -> output formatter
  -> Google Sheets / downstream nodes
```

The solver prioritizes hard veto avoidance, team-size and gender constraints,
skill-floor violations, low-willingness pairs, skill spread, and dimension
coverage. It also emits audit metrics, diagnostics, and fairness scores.

## Repository layout

- `n8n/node1_clean_normalize.js` — parsing, deduplication, scale normalization,
  imputation, profiles, and pairwise matrices.
- `n8n/node2_solver_engine.js` — multi-start drafting and local-search solver.
- `n8n/node3_format_output.js` — sheet-friendly team and audit rows.
- `n8n/node4_build_matrix.js` through `node7_build_flat_matrix.js` — optional
  output shaping helpers.
- `n8n/fairmatch_template.json` — sanitized import starting point.
- `docs/CONFIGURATION.md` — roster and deployment configuration.
- `docs/SECURITY.md` — privacy and export-handling requirements.

## Usage

1. Import `n8n/fairmatch_template.json` into n8n, or copy the Code node files
   into an existing workflow.
2. Configure the private roster and Google Sheets credentials in n8n.
3. Provide input rows using the fields documented in
   [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).
4. Verify the audit output before publishing or writing results.

This repository intentionally contains no production spreadsheet IDs,
credentials, participant data, generated results, or screenshots.

## Verification

The JavaScript source can be syntax-checked with:

```powershell
node --check n8n/node1_clean_normalize.js
node --check n8n/node2_solver_engine.js
node --check n8n/node3_format_output.js
```

The n8n runtime supplies `items`; execute Code nodes inside n8n or a dedicated
harness rather than running them directly with Node.js.

## License

MIT.
