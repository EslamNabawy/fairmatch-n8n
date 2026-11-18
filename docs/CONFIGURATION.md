# Configuration

The public workflow is a template. Configure private deployment details only in
your n8n instance or a private configuration layer.

## Data flow

```text
Google Form → Excel / Google Sheet → n8n → FairMatch → output sheet
```

The form may collect scores using different scales across questions or
submissions. The normalize node detects the observed numeric range and maps
ratings to a common 1–5 scale before the solver compares participants.

## Roster

In `n8n/node1_clean_normalize.js`, set `ROSTER` only when the input sheet can
contain non-submitters that must still be assigned:

```js
const ROSTER = [
  { name: 'Participant 01', gender: 'M' },
  { name: 'Participant 02', gender: 'F' },
];
```

Leave it empty for dynamic discovery from rows that include `gender`. Explicit
rosters are recommended for production because they prevent unknown names from
becoming participants and make missing-submitter imputation deterministic.

## n8n credentials and sheets

Create credentials in n8n; never place OAuth tokens, sheet IDs, webhook tokens,
or private URLs in a committed export. The deployment needs input rows from the
form-response sheet with `display_name`, `gender`, and either structured
`self`/`skill`/`fit` objects or a JSON payload in `email`, `Email`, or `payload`.

The solver expects four teams by default. Change `K` in the solver only when
the roster size and gender constraints support the new team count.
