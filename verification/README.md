# FairMatch parity verification

This verification runs the **Code nodes embedded in the pinned n8n workflow export** and compares the solver result with the EquiTeam v4 Python reference. It uses only generated synthetic data and makes no n8n, Google Sheets, or network calls.

## Run

Requirements: Python 3.11+ and Node.js 24.x. No third-party packages are required.

```powershell
python -m unittest discover -s verification -p 'test_*.py'
python verification/run_parity.py
```

Set `NODE` to a Node.js executable path if `node` is not on `PATH`.

## What is checked

- Three deterministic synthetic 24-person scenarios, each with 25 submissions and one older response superseded by a later response.
- The cleaner retains the newer submission, records one deduplication, and emits 576 normalized response rows.
- The embedded JavaScript solver and Python v4 reference produce the same teams after team-label canonicalization and the same solver status.
- All solver constraint levels agree within `0.001`; assignments, team sizes, gender constraints, and veto avoidance pass.

`source-lock.json` pins the workflow export and both embedded JavaScript Code nodes to commit `62c1fd4e1c3fc90a1d97f5714296824017d322a4`. The harness extracts code from the workflow export because the standalone `node1_clean_normalize.js` in this repository does not match the cleaner node embedded in that export. The separate `reference/fairmatch_v4_reference.py` file is a test-only copy of the local Python v4 implementation, pinned by SHA-256.

## Evidence boundary

This is a **new synthetic verification** of current source behavior. It cannot prove that a JavaScript/Python comparison was run in the past. Existing local notes about byte-identical output compare Python implementations; they are not used as parity evidence here.

Do not add real roster, response, or named result files to this directory. Do not describe this report as production recovery, transactional webhook idempotency, or proof of a historical run.
