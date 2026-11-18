// n8n Code node: Clean, Deduplicate, Normalize, and Impute Survey Responses
// Input: Raw rows from Google Sheets / Excel
// Output: Cleaned profiles, matrices, diagnostics, and metadata

const rawItems = items.map(item => item.json);

if (!rawItems.length) {
  throw new Error('No responses received from Google Sheets / Excel.');
}

const text = val => String(val ?? '').trim();
// Identity = first 2 tokens to keep sheet output compact.
// Uniqueness is enforced below: any collision throws instead of merging people.
const shortName = val => text(val).split(/\s+/).filter(Boolean).slice(0, 2).join(' ');

// Optional roster configuration. Keep this empty to discover the roster from
// input rows, or provide [{ name: 'Participant 01', gender: 'M' }, ...] when
// non-submitters must be included. Do not hard-code production identities in
// the workflow export; configure them in the private n8n instance instead.
const ROSTER = [];
const KNOWN_GENDER_MAP = Object.fromEntries(
  ROSTER.map(person => [text(person.name), String(person.gender || '').toUpperCase()])
);

// Short-name gender index (first 2 tokens) so shortened roster still resolves gender
const KNOWN_GENDER_SHORT = {};
for (const [k, v] of Object.entries(KNOWN_GENDER_MAP)) {
  const s = shortName(k);
  if (s in KNOWN_GENDER_SHORT) {
    throw new Error(`Name collision: "${k}" shortens to "${s}", already used. Refine shortName.`);
  }
  KNOWN_GENDER_SHORT[s] = v;
}

const parseDate = val => {
  const t = Date.parse(text(val));
  return Number.isNaN(t) ? 0 : t;
};

// 1. Parse each row safely
const parsedRows = [];
const parseErrors = [];

for (let i = 0; i < rawItems.length; i++) {
  const row = rawItems[i];
  const displayName = shortName(row.display_name || row['Display Name'] || row.name || row.Name);
  
  if (!displayName) {
    parseErrors.push(`Row ${i + 1} skipped: missing display_name`);
    continue;
  }

  let survey = {};
  const rawEmail = row.email || row.Email || row.payload;
  
  if (row.self || row.skill || row.fit || row.selfName) {
    survey = {
      selfName: row.selfName,
      submittedAt: row.submittedAt,
      self: row.self || {},
      skill: row.skill || {},
      fit: row.fit || {},
    };
  } else if (rawEmail) {
    if (typeof rawEmail === 'object') {
      survey = rawEmail;
    } else {
      try {
        survey = JSON.parse(text(rawEmail));
      } catch (e1) {
        try {
          survey = JSON.parse(text(rawEmail).replace(/""/g, '"'));
        } catch (e2) {
          parseErrors.push(`Row ${i + 1} (${displayName}): Malformed JSON payload - ${e2.message}`);
          survey = {};
        }
      }
    }
  }

  const selfName = shortName(survey.selfName) || displayName;
  const submittedAt = text(survey.submittedAt) || text(row.person_id) || text(row.Timestamp);
  const submittedTimestamp = parseDate(submittedAt) || (i + 1);

  const cleanObject = obj => {
    if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return {};
    const res = {};
    for (const [k, v] of Object.entries(obj)) {
      const cleanKey = shortName(k);
      const num = Number(v);
      if (cleanKey && !Number.isNaN(num)) {
        res[cleanKey] = num;
      }
    }
    return res;
  };

  const self = cleanObject(survey.self);
  const skill = cleanObject(survey.skill);
  const fit = cleanObject(survey.fit);

  const sheetGender = text(row.gender || row.Gender).toUpperCase();
  const gender = sheetGender === 'M' || sheetGender === 'F' ? sheetGender : (KNOWN_GENDER_SHORT[selfName] || KNOWN_GENDER_SHORT[displayName] || '');

  parsedRows.push({
    row_number: row.row_number ?? (i + 1),
    display_name: displayName,
    self_name: selfName,
    submitted_at: submittedAt,
    submitted_timestamp: submittedTimestamp,
    gender,
    self,
    skill,
    fit,
  });
}

// 2. Deduplicate: keep latest submission per person
const latestByPerson = new Map();
const deduplicationAudit = [];

for (const row of parsedRows) {
  const key = row.self_name;
  const existing = latestByPerson.get(key);
  if (!existing || row.submitted_timestamp >= existing.submitted_timestamp) {
    if (existing) {
      deduplicationAudit.push({
        person: key,
        dropped_timestamp: existing.submitted_at,
        kept_timestamp: row.submitted_at,
      });
    }
    latestByPerson.set(key, row);
  }
}

const latestResponses = Array.from(latestByPerson.values());

// 3. Fixed roster (Python parity: roster file pins 24 members; unknown rated
// names are ignored + warned, never become ghost participants)
const hasExplicitRoster = ROSTER.length > 0;
const rosterNamesSet = new Set(Object.keys(KNOWN_GENDER_SHORT));
const unknownNames = new Set();
const noteUnknown = (name, resp) => {
  if (hasExplicitRoster && name && !rosterNamesSet.has(name)) {
    if (!unknownNames.has(name)) {
      unknownNames.add(name);
      parseErrors.push(`Unknown name ignored (not in fixed roster): "${name}" (rater ${resp})`);
    }
    return true;
  }
  return false;
};
for (const resp of latestResponses) {
  if (!noteUnknown(resp.self_name, resp.self_name)) rosterNamesSet.add(resp.self_name);
  for (const name of Object.keys(resp.skill)) {
    if (!noteUnknown(name, resp.self_name)) rosterNamesSet.add(name);
  }
  for (const name of Object.keys(resp.fit)) {
    if (!noteUnknown(name, resp.self_name)) rosterNamesSet.add(name);
  }
}

const rosterNames = Array.from(rosterNamesSet).filter(Boolean);

// Detect gender for every roster member
const roster = rosterNames.map((name, index) => {
  const resp = latestByPerson.get(name);
  let g = resp?.gender || KNOWN_GENDER_SHORT[name];
  if (!g) {
    g = 'F';
  }
  return {
    person_id: `p${String(index + 1).padStart(2, '0')}`,
    display_name: name,
    gender: g,
    active: true,
    has_submitted: latestByPerson.has(name),
  };
});

const rosterByName = new Map(roster.map(p => [p.display_name, p]));

// 4. Auto-detect rating scale & normalize (1-10 -> 1-5)
const allVals = [];
for (const resp of latestResponses) {
  for (const v of Object.values(resp.self)) allVals.push(v);
  for (const v of Object.values(resp.skill)) allVals.push(v);
  for (const v of Object.values(resp.fit)) allVals.push(v);
}

const maxRaw = allVals.length ? Math.max(...allVals) : 10;
const scale = v => {
  if (v === undefined || v === null || Number.isNaN(Number(v))) return 3.0;
  const num = Number(v);
  if (maxRaw <= 5) return num;
  return Number((1.0 + (num - 1.0) * 4.0 / (maxRaw - 1.0)).toFixed(3));
};

// 5. Flatten responses & build peer ratings
const flatResponses = [];
for (const resp of latestResponses) {
  const rater = resp.self_name;
  const s = resp.self;
  
  flatResponses.push({
    rater,
    target: rater,
    devops: scale(s.devops ?? 3),
    ai_ml: scale(s.aiml ?? s.ai_ml ?? 3),
    technical: scale(s.general ?? s.technical ?? 3),
    involvement: scale(s.involvement ?? 3),
    willing: 3.0,
    is_imputed: false,
  });

  const allTargets = new Set([...Object.keys(resp.skill), ...Object.keys(resp.fit)]);
  for (const target of allTargets) {
    if (!rosterByName.has(target)) continue;
    const sVal = resp.skill[target];
    const fVal = resp.fit[target];
    const svv = sVal !== undefined ? scale(sVal) : 3.0;
    const fvv = fVal !== undefined ? scale(fVal) : 3.0;
    
    flatResponses.push({
      rater,
      target,
      devops: svv,
      ai_ml: svv,
      technical: svv,
      involvement: svv,
      willing: fvv,
      is_imputed: false,
    });
  }
}

// 6. Missing participant imputation (peer consensus mean)
const peerSkillRecv = new Map();
const peerWillRecv = new Map();
for (const name of rosterNames) {
  peerSkillRecv.set(name, []);
  peerWillRecv.set(name, []);
}

for (const r of flatResponses) {
  if (r.rater !== r.target && rosterByName.has(r.target)) {
    peerSkillRecv.get(r.target)?.push(r.devops);
    peerWillRecv.get(r.target)?.push(r.willing);
  }
}

const skillMean = {};
const willMean = {};
for (const name of rosterNames) {
  const sArr = peerSkillRecv.get(name) || [];
  const wArr = peerWillRecv.get(name) || [];
  skillMean[name] = sArr.length ? Number((sArr.reduce((a, b) => a + b, 0) / sArr.length).toFixed(3)) : 3.0;
  willMean[name] = wArr.length ? Number((wArr.reduce((a, b) => a + b, 0) / wArr.length).toFixed(3)) : 3.0;
}

const missingSubmitters = rosterNames.filter(name => !latestByPerson.has(name));
for (const m of missingSubmitters) {
  const selfVal = skillMean[m];
  flatResponses.push({
    rater: m,
    target: m,
    devops: selfVal,
    ai_ml: selfVal,
    technical: selfVal,
    involvement: selfVal,
    willing: 3.0,
    is_imputed: true,
  });
  for (const t of rosterNames) {
    if (t === m) continue;
    flatResponses.push({
      rater: m,
      target: t,
      devops: skillMean[t],
      ai_ml: skillMean[t],
      technical: skillMean[t],
      involvement: skillMean[t],
      willing: willMean[t],
      is_imputed: true,
    });
  }
}

// 7. Compute Skill Profiles & Self-Disagreement Flags
const DIMS = ['devops', 'ai_ml', 'technical', 'involvement'];
const TECH_DIMS = ['devops', 'ai_ml', 'technical'];
const DISAGREEMENT_THRESHOLD = 1.5;

const peerVals = {};
const selfVals = {};
for (const name of rosterNames) {
  peerVals[name] = { devops: [], ai_ml: [], technical: [], involvement: [] };
  selfVals[name] = {};
}

for (const r of flatResponses) {
  if (r.rater === r.target) {
    for (const d of DIMS) selfVals[r.target][d] = r[d];
  } else {
    for (const d of DIMS) peerVals[r.target][d].push(r[d]);
  }
}

const profiles = {};
const diagnostics = {
  disagreements: [],
  rater_consistency: [],
  low_flags: [],
  low_confidence: [],
  deduplications: deduplicationAudit,
  parse_errors: parseErrors,
  missing_submitters: missingSubmitters,
};

for (const person of roster) {
  const name = person.display_name;
  const prof = {
    name,
    gender: person.gender,
    peer: {},
    self: {},
    final: {},
    gap: {},
    flag: {},
    peer_count: {},
  };

  for (const d of DIMS) {
    const pList = peerVals[name][d];
    const peerScore = pList.length ? Number((pList.reduce((a, b) => a + b, 0) / pList.length).toFixed(3)) : 3.0;
    const selfScore = selfVals[name][d] ?? peerScore;
    const gap = Number((selfScore - peerScore).toFixed(3));
    let flag = null;

    if (gap > DISAGREEMENT_THRESHOLD) {
      flag = 'OVER_SELF_RATED';
      diagnostics.disagreements.push({ person: name, dim: d, self: selfScore, peer: peerScore, gap, flag });
    } else if (gap < -DISAGREEMENT_THRESHOLD) {
      flag = 'UNDER_SELF_RATED';
      diagnostics.disagreements.push({ person: name, dim: d, self: selfScore, peer: peerScore, gap, flag });
    }

    let finalScore;
    if (flag !== null) {
      finalScore = peerScore;
    } else {
      if (TECH_DIMS.includes(d)) {
        finalScore = Number((0.8 * peerScore + 0.2 * selfScore).toFixed(3));
      } else {
        finalScore = Number((0.5 * peerScore + 0.5 * selfScore).toFixed(3));
      }
    }

    prof.peer[d] = peerScore;
    prof.self[d] = selfScore;
    prof.gap[d] = gap;
    prof.flag[d] = flag;
    prof.final[d] = finalScore;
    prof.peer_count[d] = pList.length;
  }

  prof.overall_skill = Number((DIMS.reduce((sum, d) => sum + prof.final[d], 0) / DIMS.length).toFixed(3));
  profiles[name] = prof;
}

// 7b. Low-confidence flags + rater consistency (Python parity: compute_profiles 1.4/1.6)
const expectedRaters = roster.length - 1;
for (const person of roster) {
  for (const d of DIMS) {
    const pc = profiles[person.display_name].peer_count[d];
    if (pc < Math.max(3, expectedRaters * 0.3)) {
      diagnostics.low_flags.push(`${person.display_name} ${d}: ${pc}/${expectedRaters} peer ratings LOW_CONFIDENCE`);
    }
  }
}
const pearson = (x, y) => {
  const n = x.length;
  if (n !== y.length || n < 2) return null;
  const mx = x.reduce((a, b) => a + b, 0) / n;
  const my = y.reduce((a, b) => a + b, 0) / n;
  let num = 0, dx = 0, dy = 0;
  for (let i = 0; i < n; i++) {
    num += (x[i] - mx) * (y[i] - my);
    dx += (x[i] - mx) ** 2;
    dy += (y[i] - my) ** 2;
  }
  const denx = Math.sqrt(dx), deny = Math.sqrt(dy);
  if (denx === 0 || deny === 0) return 0.0;
  return num / (denx * deny);
};
const skillByRater = {};
const willByRater = {};
for (const r of flatResponses) {
  if (r.rater === r.target) continue;
  const tech = TECH_DIMS.map(d => r[d]).filter(v => v !== undefined && v !== null);
  if (!tech.length) continue;
  (skillByRater[r.rater] = skillByRater[r.rater] || []).push(tech.reduce((a, b) => a + b, 0) / tech.length);
  (willByRater[r.rater] = willByRater[r.rater] || []).push(r.willing);
}
for (const rater of Object.keys(skillByRater)) {
  const sv = skillByRater[rater];
  if (sv.length >= 10) {
    const corr = pearson(sv, willByRater[rater]);
    if (corr !== null && corr > 0.75) {
      diagnostics.rater_consistency.push({ rater, correlation: Number(corr.toFixed(3)), n: sv.length });
    }
  }
}

// 8. Build Directed & Pairwise Willingness / Veto Matrices
const directedWilling = {};
for (const name of rosterNames) directedWilling[name] = {};

for (const r of flatResponses) {
  if (r.rater !== r.target) {
    directedWilling[r.rater][r.target] = r.willing;
  }
}

const pairMin = {};
const pairAvg = {};
const vetoPairs = [];
const lowPairs = [];

for (const a of rosterNames) {
  pairMin[a] = {};
  pairAvg[a] = {};
}

for (let i = 0; i < rosterNames.length; i++) {
  const a = rosterNames[i];
  for (let j = i + 1; j < rosterNames.length; j++) {
    const b = rosterNames[j];
    const ab = directedWilling[a]?.[b] ?? 3.0;
    const ba = directedWilling[b]?.[a] ?? 3.0;
    const minW = Number(Math.min(ab, ba).toFixed(3));
    const avgW = Number(((ab + ba) / 2.0).toFixed(3));

    pairMin[a][b] = minW;
    pairMin[b][a] = minW;
    pairAvg[a][b] = avgW;
    pairAvg[b][a] = avgW;

    if (minW <= 1.5) {
      vetoPairs.push({ p1: a, p2: b, min_willing: minW, rater_a_to_b: ab, rater_b_to_a: ba });
    } else if (minW < 2.5) {
      lowPairs.push({ p1: a, p2: b, min_willing: minW });
    }
  }
}

return [{
  json: {
    runId: `run-${new Date().toISOString()}`,
    roster,
    profiles,
    pairMin,
    pairAvg,
    vetoPairs,
    lowPairs,
    flatResponses,
    flatRowCount: flatResponses.length,
    diagnostics,
    metadata: {
      raw_rows: rawItems.length,
      unique_respondents: latestResponses.length,
      missing_submitters: missingSubmitters.length,
      roster_size: roster.length,
      veto_pair_count: vetoPairs.length,
      scale_max_detected: maxRaw,
      generated_at: new Date().toISOString(),
    }
  }
}];
