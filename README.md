<div align="center">

# ⚖️ FairMatch

### Constraint-aware team formation, built natively for n8n.

Turn messy survey responses into balanced, explainable teams — with hard veto
avoidance, skill coverage, fairness scoring, and an audit trail built in.

[![n8n](https://img.shields.io/badge/n8n-native-EA4B71?style=for-the-badge&logo=n8n&logoColor=white)](https://n8n.io/)
[![JavaScript](https://img.shields.io/badge/JavaScript-Code_Nodes-F7DF1E?style=for-the-badge&logo=javascript&logoColor=111827)](https://developer.mozilla.org/en-US/docs/Web/JavaScript)
[![License](https://img.shields.io/badge/license-MIT-22C55E?style=for-the-badge)](LICENSE)

</div>

---

## ✨ What it does

FairMatch is an n8n workflow for building teams from peer-review and
self-assessment data. It is designed for real-world input: duplicate
submissions, malformed JSON, mixed rating scales, missing respondents, and
incomplete peer ratings are treated as normal operating conditions.

The result is more than a roster. Every run produces team assignments,
metrics, diagnostics, and fairness/audit data that can be reviewed before the
results are written back to a spreadsheet.

## 🧭 The pipeline

```mermaid
flowchart LR
    A[📥 Raw survey rows] --> B[🧹 Clean & normalize]
    B --> C[🧠 FairMatch solver]
    C --> D[📊 Format results]
    D --> E[📝 Build matrices]
    E --> F[📗 Google Sheets / downstream]

    B -. diagnostics .-> G[🔍 Audit trail]
    C -. constraint levels .-> G

    style A fill:#172554,stroke:#60a5fa,color:#fff
    style B fill:#312e81,stroke:#a78bfa,color:#fff
    style C fill:#064e3b,stroke:#34d399,color:#fff
    style D fill:#164e63,stroke:#22d3ee,color:#fff
    style E fill:#713f12,stroke:#fbbf24,color:#fff
    style F fill:#3f1d4f,stroke:#e879f9,color:#fff
    style G fill:#374151,stroke:#9ca3af,color:#fff
```

## 🎯 What the solver optimizes

The solver evaluates candidates lexicographically, so the most important
constraints are considered first:

| Priority | Constraint | Purpose |
| ---: | --- | --- |
| `L1` | Skill floor | Prevent materially weak teams |
| `L2V` | Hard vetoes | Keep incompatible pairs apart |
| `L2` | Willingness floor | Reduce low-confidence pairings |
| `L2C` | Compatibility | Limit soft low-willingness pairs |
| `L5` | Skill balance | Minimize the gap between team averages |
| `L3` | Dimension coverage | Spread technical strengths across teams |
| `L6` | Internal spread | Avoid uneven skill distributions |
| `L4` | Specialist coverage | Preserve tier/role diversity |

The engine combines multi-start drafting with local-search refinement and uses
a fixed seed for repeatable results under the same input and configuration.

## 🛡️ Built for imperfect data

- **Deduplicates submissions** and keeps the latest response per person.
- **Parses resiliently** across structured objects and escaped JSON payloads.
- **Normalizes rating scales** when inputs mix 1–5 and 1–10 responses.
- **Imputes missing respondents** from peer consensus when an explicit roster is configured.
- **Detects self/peer disagreement** and records the decision in diagnostics.
- **Builds mutual willingness** from the lower of the two directed ratings.
- **Rejects roster collisions** instead of silently merging people.
- **Emits audit metrics** including veto counts, skill gaps, confidence flags, and grades.

## 🚀 Quick start

### 1. Import the sanitized template

Import [`n8n/fairmatch_template.json`](n8n/fairmatch_template.json) into n8n.
It contains no production credentials, participant data, or live spreadsheet
identifiers.

### 2. Configure private deployment details

Set the roster and connect Google Sheets inside your private n8n instance.
Read [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) before wiring inputs or
outputs.

### 3. Run and inspect

Run the workflow with representative input, review the audit output, then
enable downstream writes. Keep production data and credentials out of Git;
see [`docs/SECURITY.md`](docs/SECURITY.md).

## 📦 Repository map

```text
.
├── n8n/
│   ├── fairmatch_template.json       # Sanitized importable workflow
│   ├── node1_clean_normalize.js      # Input cleaning + diagnostics
│   ├── node2_solver_engine.js        # Team formation engine
│   ├── node3_format_output.js        # Team + audit row formatting
│   └── node4–node7_*.js              # Optional output matrix helpers
├── docs/
│   ├── CONFIGURATION.md               # Roster and deployment setup
│   └── SECURITY.md                    # Privacy and export guidance
├── LICENSE
└── README.md
```

## 📥 Expected input shape

Each n8n item should provide a display name and gender, plus either structured
survey fields or a JSON payload:

```json
{
  "display_name": "Participant 01",
  "gender": "F",
  "self": {
    "devops": 4,
    "aiml": 5,
    "general": 4,
    "involvement": 5
  },
  "skill": {},
  "fit": {}
}
```

The normalizer also accepts `email`, `Email`, or `payload` when the survey is
stored as a JSON string.

## 📤 Output highlights

Each run can expose:

- team assignments and member-level skill scores;
- team averages, totals, gender counts, and weakest pair;
- veto and low-willingness counts;
- solver status and lexicographic constraint levels;
- deduplication, parsing, disagreement, and low-confidence diagnostics;
- fairness scores and letter grades for review workflows.

## ✅ Verification

The repository has no runtime dependency installation step. Syntax-check the
Code nodes locally with:

```powershell
Get-ChildItem n8n -Filter *.js | ForEach-Object { node --check $_.FullName }
```

The n8n runtime supplies `items`; Code nodes are intended to run inside n8n or
through a dedicated harness, not as standalone Node.js programs.

## 🔐 Public-repository boundary

This repository intentionally excludes production spreadsheet IDs, credentials,
participant data, generated results, screenshots, and local deployment notes.
Treat survey responses and workflow exports as private data.

## 📄 License

MIT — see [`LICENSE`](LICENSE).

<div align="center">

Built for teams that want the outcome to be fair — and the reasoning to be visible.

</div>
