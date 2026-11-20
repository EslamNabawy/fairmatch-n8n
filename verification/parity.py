"""Compare the pinned n8n Code nodes with the local EquiTeam v4 reference."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERIFY_DIR = Path(__file__).resolve().parent
ROOT_DIR = VERIFY_DIR.parent
REFERENCE_PATH = VERIFY_DIR / "reference" / "fairmatch_v4_reference.py"
LOCK_PATH = VERIFY_DIR / "source-lock.json"
NODE_RUNNER = VERIFY_DIR / "run_nodes.mjs"
LEVEL_KEYS = ("L1", "L2V", "L2", "L2C", "L5", "L3", "L6", "L4")
BASE_TIMESTAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_reference():
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    actual_hash = _sha256(REFERENCE_PATH)
    expected_hash = lock["python_reference"]["sha256"]
    if actual_hash != expected_hash:
        raise RuntimeError("Vendored Python reference differs from its source lock.")

    spec = importlib.util.spec_from_file_location("fairmatch_v4_reference", REFERENCE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the pinned Python reference implementation.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, lock


def _participant(index: int) -> str:
    return f"Participant {index + 1:02d}"


def _timestamp(seconds: int) -> str:
    return BASE_TIMESTAMP.replace(second=seconds).isoformat().replace("+00:00", "Z")


def _score(index: int, target: int, scenario: int, dimension: int, old: bool = False) -> int:
    offset = scenario + (3 if old else 0)
    return 1 + ((index * 7 + target * 3 + dimension * 5 + offset) % 10)


def _fit_score(index: int, target: int, scenario: int, old: bool = False) -> int:
    veto_pairs = {(0, 10), (1, 11), (2, 12), (3, 13)}
    pair = (min(index, target), max(index, target))
    if pair in veto_pairs:
        return 1
    offset = scenario + (2 if old else 0)
    return 6 + ((index * 3 + target * 5 + offset) % 5)


def _survey_row(index: int, scenario: int, submitted_at: str, old: bool = False) -> dict[str, Any]:
    name = _participant(index)
    dimensions = {
        "devops": 1 + ((index * 5 + scenario * 2 + (3 if old else 0)) % 10),
        "aiml": 1 + ((index * 3 + scenario * 4 + (2 if old else 0)) % 10),
        "general": 1 + ((index * 9 + scenario + (4 if old else 0)) % 10),
        "involvement": 1 + ((index * 2 + scenario * 3 + (1 if old else 0)) % 10),
    }
    skills = {
        _participant(target): _score(index, target, scenario, dimension=0, old=old)
        for target in range(24)
        if target != index
    }
    fit = {
        _participant(target): _fit_score(index, target, scenario, old=old)
        for target in range(24)
        if target != index
    }
    if old:
        dimensions["devops"] = 2

    payload = {
        "selfName": name,
        "submittedAt": submitted_at,
        "self": dimensions,
        "skill": skills,
        "fit": fit,
    }
    return {
        "display_name": name,
        "gender": "M" if index < 10 else "F",
        "email": json.dumps(payload, separators=(",", ":")),
    }


def make_synthetic_rows(scenario: int) -> list[dict[str, Any]]:
    """Create 24 fake participants, 25 submissions, and one superseded reply."""
    rows = [_survey_row(0, scenario, _timestamp(0), old=True)]
    rows.extend(
        _survey_row(index, scenario, _timestamp(index))
        for index in range(1, 24)
    )
    rows.append(_survey_row(0, scenario, _timestamp(24)))
    return rows


def _run_javascript(raw_rows: list[dict[str, Any]]) -> dict[str, Any]:
    node_command = os.environ.get("NODE", "node")
    process = subprocess.run(
        [node_command, str(NODE_RUNNER)],
        input=json.dumps({"raw_rows": raw_rows}, separators=(",", ":")),
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT_DIR,
        timeout=60,
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"Pinned n8n Code nodes failed ({process.returncode}): {process.stderr.strip()}"
        )
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Node runner returned invalid JSON.") from exc


def _run_python_reference(cleaned: dict[str, Any], reference) -> dict[str, Any]:
    roster_rows = cleaned["roster"]
    roster = {person["display_name"]: person["gender"] for person in roster_rows}
    responses = [
        {
            "rater": row["rater"],
            "target": row["target"],
            "devops": float(row["devops"]),
            "ai_ml": float(row["ai_ml"]),
            "technical": float(row["technical"]),
            "involvement": float(row["involvement"]),
            "willing": float(row["willing"]),
        }
        for row in cleaned["flatResponses"]
    ]

    cfg = dict(reference.CONFIG_DEFAULTS)
    cfg["RANDOM_SEED"] = 42
    cfg["NUM_STARTS"] = 20
    cfg["MIN_WILL_FLOOR"] = 2.5
    profiles, _ = reference.compute_profiles(responses, roster, cfg)
    _, pair_min, _ = reference.build_willing_matrices(responses, roster)
    total_m = sum(gender == "M" for gender in roster.values())
    total_f = len(roster) - total_m
    m_slots, f_slots = reference.gender_slots(total_m, total_f, 4)

    skill_values = sorted(profile["overall_skill"] for profile in profiles.values())
    cfg["MIN_SKILL_FLOOR"] = round(skill_values[max(0, int(len(skill_values) * 0.1))] - 0.3, 3)
    if reference.preflight_check(roster, 4, m_slots, f_slots, cfg):
        raise AssertionError("Synthetic fixture violates Python solver preflight constraints.")

    best_tuple = None
    best_pack = None
    for start in range(cfg["NUM_STARTS"]):
        start_cfg = dict(cfg)
        start_cfg["RANDOM_SEED"] = cfg["RANDOM_SEED"] + start * 997
        start_cfg["seed"] = 42 + start * 997
        teams, relax = reference.draft_v4(
            profiles, roster, m_slots, f_slots, pair_min, start_cfg
        )
        teams, _, relax = reference.refinement_v4(
            teams, profiles, roster, m_slots, f_slots, pair_min, start_cfg, relax
        )
        levels = reference.compute_levels(teams, profiles, pair_min, relax, start_cfg)
        candidate = tuple(levels[key] for key in start_cfg["LEVEL_ORDER"])
        if best_tuple is None or candidate < best_tuple:
            best_tuple = candidate
            best_pack = (teams, relax, levels)

    teams, relax, levels = best_pack
    status, _, _ = reference.classify_outcome(teams, relax, profiles, pair_min, cfg)
    return {
        "teams": [sorted(team) for team in teams],
        "status": status,
        "levels": {key: levels[key] for key in LEVEL_KEYS},
        "roster": roster,
        "pair_min": pair_min,
    }


def _js_teams(solved: dict[str, Any]) -> list[list[str]]:
    grouped: dict[str, list[str]] = {}
    for row in solved["assignments"]:
        grouped.setdefault(row["team_id"], []).append(row["member_display_name"])
    return [sorted(members) for members in grouped.values()]


def compare_scenario(scenario: int) -> dict[str, Any]:
    reference, lock = _load_reference()
    raw_rows = make_synthetic_rows(scenario)
    result = _run_javascript(raw_rows)
    cleaned = result["cleaned"]
    solved = result["solved"]
    python = _run_python_reference(cleaned, reference)

    deduplications = cleaned["diagnostics"]["deduplications"]
    if len(deduplications) != 1:
        raise AssertionError(f"Expected one deduplication, got {len(deduplications)}.")
    if deduplications[0]["kept_timestamp"] != _timestamp(24):
        raise AssertionError("Cleaner did not retain the latest synthetic submission.")
    if cleaned["metadata"]["unique_respondents"] != 24 or cleaned["metadata"]["roster_size"] != 24:
        raise AssertionError("Cleaner did not produce the expected 24-person cohort.")
    if cleaned["flatRowCount"] != 24 * 24:
        raise AssertionError("Cleaner did not produce the expected normalized response rows.")

    js_teams = sorted(_js_teams(solved))
    python_teams = sorted(python["teams"])
    if js_teams != python_teams:
        raise AssertionError("JavaScript and Python produced different team memberships.")
    if solved["audit"]["solver_status"] != python["status"]:
        raise AssertionError("JavaScript and Python solver statuses differ.")

    js_levels = solved["audit"]["levels"]
    level_deltas = {}
    for key in LEVEL_KEYS:
        delta = abs(float(js_levels[key]) - float(python["levels"][key]))
        level_deltas[key] = delta
        if not math.isfinite(delta) or delta > 0.001:
            raise AssertionError(f"Constraint level {key} differs by {delta} (> 0.001).")

    assigned = [person for team in js_teams for person in team]
    if len(assigned) != 24 or len(set(assigned)) != 24:
        raise AssertionError("JavaScript result does not assign each participant exactly once.")
    if sorted(len(team) for team in js_teams) != [6, 6, 6, 6]:
        raise AssertionError("JavaScript result does not form four teams of six.")
    if not all(solved["audit"]["hard_constraints_passed"].values()):
        raise AssertionError("JavaScript solver reports a failed hard constraint.")

    genders = python["roster"]
    for team in js_teams:
        if any(python["pair_min"][a][b] <= 1.5 for i, a in enumerate(team) for b in team[i + 1:]):
            raise AssertionError("A veto pair was placed on the same team.")
    if sum(gender == "M" for gender in genders.values()) != 10:
        raise AssertionError("Synthetic roster gender distribution drifted from the fixture.")

    return {
        "scenario": scenario,
        "parity": True,
        "raw_submissions": len(raw_rows),
        "unique_participants": cleaned["metadata"]["unique_respondents"],
        "deduplications": len(deduplications),
        "status": solved["audit"]["solver_status"],
        "team_sizes": sorted(len(team) for team in js_teams),
        "veto_pairs": solved["audit"]["veto_pairs_total"],
        "in_team_veto_pairs": int(js_levels["L2V"]),
        "max_level_delta": max(level_deltas.values()),
        "workflow_commit": lock["workflow_commit"],
    }


def run_suite() -> list[dict[str, Any]]:
    return [compare_scenario(scenario) for scenario in range(3)]


def render_report(results: list[dict[str, Any]]) -> str:
    reference, lock = _load_reference()
    del reference
    lines = [
        "FairMatch JavaScript/Python parity verification",
        "================================================",
        f"Generated at (UTC): {datetime.now(timezone.utc).isoformat()}",
        f"Workflow source commit: {lock['workflow_commit']}",
        f"Workflow SHA-256: {lock['workflow_sha256']}",
        f"Python reference SHA-256: {lock['python_reference']['sha256']}",
        f"Node.js: {subprocess.run([os.environ.get('NODE', 'node'), '--version'], capture_output=True, text=True, check=True).stdout.strip()}",
        f"Python: {sys.version.split()[0]}",
        "Fixture: synthetic 24-person cohort; 25 submissions including one superseded response.",
        "Comparison: canonicalized team memberships and solver status must match; each constraint level may differ by at most 0.001.",
        "Scope: verifies current pinned workflow Code nodes against the included Python v4 reference. It does not recreate or prove any earlier comparison run.",
        "",
        "Scenario results:",
    ]
    for result in results:
        lines.append(
            f"- Scenario {result['scenario']}: PASS; {result['raw_submissions']} submissions, "
            f"{result['unique_participants']} unique participants, {result['deduplications']} deduplication; "
            f"status={result['status']}; team sizes={result['team_sizes']}; "
            f"veto pairs={result['veto_pairs']}, in-team veto pairs={result['in_team_veto_pairs']}; "
            f"max constraint-level delta={result['max_level_delta']:.6f}."
        )
    lines.extend([
        "",
        "Privacy: all fixture identities are synthetic. No cohort roster or response data is included.",
    ])
    return "\n".join(lines) + "\n"
