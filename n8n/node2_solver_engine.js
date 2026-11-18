// n8n Code node: FairMatch v4 solver engine — exact port of Python fairmatch.py v4 main path
// (penalty draft_v4 + steepest refinement_v4 + MT19937 seeds + raw tuple selection).
// Fairness scores/grades (0-100) are an n8n-only presentation extra.
const input = items[0].json;
const { roster, profiles, pairMin, vetoPairs } = input;

const K = 4; // Target 4 teams
const N = roster.length;
const VETO_THRESHOLD = 1.5;
const WILL_LOW_PAIR = 2.5;
const MIN_WILL_FLOOR = 2.5;
const MIN_DIMENSION_COVERAGE = 3.0;
const TEAM_AVG_GAP_THRESHOLD = 0.6;
const SPREAD_GAP_THRESHOLD = 0.75;
const LEVEL_ORDER = ['L1', 'L2V', 'L2', 'L2C', 'L5', 'L3', 'L6', 'L4'];
const MAX_PASSES = 6;
const NUM_STARTS = 20;
const RANDOM_SEED = 42;

const rosterNames = roster.map(p => p.display_name);
const genderOf = {};
for (const p of roster) genderOf[p.display_name] = p.gender;
const totalM = roster.filter(p => p.gender === 'M').length;
const totalF = N - totalM;

// ---- CPython-compatible Mersenne Twister (validated bit-identical) ----
function MT19937(seed) {
  const NN = 624, MM = 397, AA = 0x9908b0df;
  const mt = new Array(NN);
  const key = [];
  let x = Math.floor(seed);
  if (!(x > 0)) key.push(0);
  while (x > 0) { key.push(x % 0x100000000); x = Math.floor(x / 0x100000000); }
  mt[0] = 19650218 >>> 0;
  for (let i = 1; i < NN; i++) {
    mt[i] = (Math.imul(1812433253, mt[i - 1] ^ (mt[i - 1] >>> 30)) + i) >>> 0;
  }
  let ii = 1, jj = 0;
  const kk = Math.max(NN, key.length);
  for (let c = 0; c < kk; c++) {
    mt[ii] = (mt[ii] ^ Math.imul(mt[ii - 1] ^ (mt[ii - 1] >>> 30), 1664525)) >>> 0;
    mt[ii] = (mt[ii] + key[jj] + jj) >>> 0;
    ii++; jj++;
    if (ii >= NN) { mt[0] = mt[NN - 1]; ii = 1; }
    if (jj >= key.length) jj = 0;
  }
  for (let c = 0; c < NN - 1; c++) {
    mt[ii] = (mt[ii] ^ Math.imul(mt[ii - 1] ^ (mt[ii - 1] >>> 30), 1566083941)) >>> 0;
    mt[ii] = (mt[ii] - ii) >>> 0;
    ii++;
    if (ii >= NN) { mt[0] = mt[NN - 1]; ii = 1; }
  }
  mt[0] = 0x80000000;
  let mti = NN;
  const twist = () => {
    for (let i = 0; i < NN; i++) {
      const y = (mt[i] & 0x80000000) + (mt[(i + 1) % NN] & 0x7fffffff);
      mt[i] = (mt[(i + MM) % NN] ^ (y >>> 1) ^ ((y & 1) ? AA : 0)) >>> 0;
    }
    mti = 0;
  };
  const int32 = () => {
    if (mti >= NN) twist();
    let y = mt[mti++];
    y ^= y >>> 11;
    y ^= (y << 7) & 0x9d2c5680;
    y ^= (y << 15) & 0xefc60000;
    y ^= y >>> 18;
    return y >>> 0;
  };
  const random = () => ((int32() >>> 5) * 67108864.0 + (int32() >>> 6)) / 9007199254740992.0;
  const getrandbits = k => {
    let r = 0, rem = k;
    while (rem > 0) {
      const take = Math.min(32, rem);
      r = r * Math.pow(2, take) + (int32() >>> (32 - take));
      rem -= take;
    }
    return r;
  };
  const randbelow = n => {
    if (!(n > 0)) throw new Error('randbelow: empty range');
    const k = n.toString(2).length;
    let r = getrandbits(k);
    while (r >= n) r = getrandbits(k);
    return r;
  };
  const shuffle = arr => {
    for (let i = arr.length - 1; i > 0; i--) {
      const j = randbelow(i + 1);
      const t = arr[i]; arr[i] = arr[j]; arr[j] = t;
    }
    return arr;
  };
  return { random, shuffle };
}

class InfeasibleError extends Error {
  constructor(reason, relax, partial) {
    super(reason);
    this.reason = reason;
    this.tier_relaxations = relax;
    this.partial = partial;
  }
}

// ---- Gender slots (Python gender_slots verbatim) ----
function genderSlots(totalM_, totalF_, k) {
  const n = totalM_ + totalF_;
  const sizes = Array.from({ length: k }, (_, i) => Math.floor(n / k) + (i < (n % k) ? 1 : 0));
  const distribute = total => Array.from({ length: k }, (_, i) => Math.floor(total / k) + (i < (total % k) ? 1 : 0));
  const mDist = distribute(totalM_);
  const fDist = distribute(totalF_);
  if (mDist.every((m, i) => m + fDist[i] === sizes[i])) return [mDist, fDist];
  const even = s => Math.max(...s) - Math.min(...s);
  const fA = sizes.map((s, i) => s - mDist[i]);
  const mB = sizes.map((s, i) => s - fDist[i]);
  const validA = fA.every(x => x >= 0) && even(fA) <= 1;
  const validB = mB.every(x => x >= 0) && even(mB) <= 1;
  if (validA && validB) return [mDist, fA];
  if (validA) return [mDist, fA];
  if (validB) return [mB, fDist];
  return [mDist, fDist];
}
const [mSlots, fSlots] = genderSlots(totalM, totalF, K);
const teamSizes = mSlots.map((m, i) => m + fSlots[i]);
if (mSlots.reduce((a, b) => a + b, 0) !== totalM || fSlots.reduce((a, b) => a + b, 0) !== totalF) {
  throw new Error(`Preflight: slots sum != pool (M ${mSlots} vs ${totalM}, F ${fSlots} vs ${totalF})`);
}

// ---- Tiers (Python build_tiers verbatim, + display labels) ----
function buildTiers(mSlots_, fSlots_) {
  const out = {};
  for (const gender of ['M', 'F']) {
    const slots = gender === 'M' ? mSlots_ : fSlots_;
    const pool = rosterNames.filter(n => genderOf[n] === gender);
    const sorted = pool.slice().sort((a, b) => profiles[b].overall_skill - profiles[a].overall_skill);
    const maxSlots = Math.max(...slots);
    const demands = [];
    for (let i = 1; i <= maxSlots; i++) demands.push(slots.filter(s => s >= i).length);
    if (demands.reduce((a, b) => a + b, 0) !== sorted.length) {
      throw new Error(`Tier build mismatch gender ${gender}`);
    }
    const tiers = [];
    let idx = 0;
    demands.forEach((dem, ti) => {
      const members = sorted.slice(idx, idx + dem);
      for (const name of members) {
        profiles[name].tier = ti + 1;
        profiles[name].tier_demand = dem;
        profiles[name].tierLabel = (ti + 1) === 1 ? 'Tier 1 (Top Talent)' : `Tier ${ti + 1}`;
      }
      tiers.push(members);
      idx += dem;
    });
    out[gender] = { tiers, demands, count: maxSlots };
  }
  return out;
}

// ---- Evaluation helpers ----
const DIMS = ['devops', 'ai_ml', 'technical', 'involvement'];
const TECH_DIMS = ['devops', 'ai_ml', 'technical'];
const teamSkillAvg = team => {
  if (!team.length) return 0;
  return Number((team.reduce((s, n) => s + profiles[n].overall_skill, 0) / team.length).toFixed(3));
};
const teamWorstWilling = team => {
  if (team.length < 2) return 5.0;
  let worst = 5.0;
  for (let i = 0; i < team.length; i++) {
    for (let j = i + 1; j < team.length; j++) {
      const w = pairMin[team[i]][team[j]] ?? 3.0;
      if (w < worst) worst = w;
    }
  }
  return Number(worst.toFixed(3));
};
const teamAvgWilling = team => {
  if (team.length < 2) return 5.0;
  let sum = 0, count = 0;
  for (let i = 0; i < team.length; i++) {
    for (let j = i + 1; j < team.length; j++) {
      sum += (pairMin[team[i]][team[j]] ?? 3.0);
      count++;
    }
  }
  return count ? Number((sum / count).toFixed(3)) : 5.0;
};
const teamWeakestPair = team => {
  if (team.length < 2) return { p1: '', p2: '', score: 5.0 };
  let minScore = 5.0, p1 = team[0], p2 = team[1];
  for (let i = 0; i < team.length; i++) {
    for (let j = i + 1; j < team.length; j++) {
      const w = pairMin[team[i]][team[j]] ?? 3.0;
      if (w < minScore) { minScore = w; p1 = team[i]; p2 = team[j]; }
    }
  }
  return { p1, p2, score: Number(minScore.toFixed(3)) };
};
const teamVetoCount = team => {
  let count = 0;
  for (let i = 0; i < team.length; i++) {
    for (let j = i + 1; j < team.length; j++) {
      if ((pairMin[team[i]][team[j]] ?? 3.0) <= VETO_THRESHOLD) count++;
    }
  }
  return count;
};
const teamLowStats = team => {
  let veto = 0, low = 0, sum = 0, n = 0;
  for (let i = 0; i < team.length; i++) {
    for (let j = i + 1; j < team.length; j++) {
      const m = pairMin[team[i]][team[j]] ?? 3.0;
      sum += m; n++;
      if (m <= VETO_THRESHOLD) veto++;
      if (m < WILL_LOW_PAIR) low++;
    }
  }
  return { veto, low };
};
const teamSpread = team => {
  if (team.length < 2) return 0.0;
  const vals = team.map(n => profiles[n].overall_skill);
  const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
  const variance = vals.reduce((s, v) => s + (v - avg) ** 2, 0) / vals.length;
  return Number(Math.sqrt(variance).toFixed(3));
};
const teamDimMax = (team, dim) => {
  if (!team.length) return 0;
  return Math.max(...team.map(n => profiles[n].final[dim]));
};

const globalAvgSkill = Number((rosterNames.reduce((s, n) => s + profiles[n].overall_skill, 0) / N).toFixed(3));
// Python parity: floor = 10th-percentile overall skill minus 0.3
const sortedSkills = rosterNames.map(n => profiles[n].overall_skill).sort((a, b) => a - b);
const MIN_SKILL_FLOOR = Number((sortedSkills[Math.max(0, Math.floor(sortedSkills.length * 0.1))] - 0.3).toFixed(3));

function teamAvgMetrics(teams) {
  const avgs = teams.map(t => teamSkillAvg(t));
  if (!avgs.length) return { avgs, max: 0, min: 0, gap: 0, std: 0, mean: 0 };
  const gap = Number((Math.max(...avgs) - Math.min(...avgs)).toFixed(3));
  const mean = Number((avgs.reduce((a, b) => a + b, 0) / avgs.length).toFixed(3));
  const variance = avgs.reduce((s, v) => s + (v - mean) ** 2, 0) / avgs.length;
  const std = avgs.length > 1 ? Number(Math.sqrt(variance).toFixed(3)) : 0.0;
  return { avgs, max: Number(Math.max(...avgs).toFixed(3)), min: Number(Math.min(...avgs).toFixed(3)), gap, std, mean };
}

function computeLevelsV3Base(teams, relax) {
  let L1 = 0;
  for (const t of teams) {
    const avg = teamSkillAvg(t);
    if (avg < MIN_SKILL_FLOOR) L1 += Number((MIN_SKILL_FLOOR - avg).toFixed(3));
  }
  L1 = Number(L1.toFixed(3));
  let L2 = 0;
  for (const t of teams) {
    const w = teamWorstWilling(t);
    if (w < MIN_WILL_FLOOR) L2 += Number((MIN_WILL_FLOOR - w).toFixed(3));
  }
  L2 = Number(L2.toFixed(3));
  let L3 = 0;
  for (const t of teams) {
    for (const d of TECH_DIMS) {
      if (teamDimMax(t, d) < MIN_DIMENSION_COVERAGE) L3++;
    }
  }
  const L4 = relax.length;
  const avgMetrics = teamAvgMetrics(teams);
  const spreads = teams.map(t => teamSpread(t));
  const L6 = spreads.length ? Number((Math.max(...spreads) - Math.min(...spreads)).toFixed(3)) : 0.0;
  return { L1, L2, L3, L4, L5: avgMetrics.gap, L6, spreads, avg_metrics: avgMetrics };
}

function computeLevels(teams, relax) {
  const base = computeLevelsV3Base(teams, relax);
  let L2V = 0, L2C = 0;
  for (const t of teams) {
    const st = teamLowStats(t);
    L2V += st.veto;
    L2C += st.low;
  }
  let L4 = 0;
  for (const t of teams) {
    const c1 = t.filter(n => profiles[n].tier === 1).length;
    if (c1 > 1) L4 += (c1 - 1);
  }
  return { ...base, L2V, L2C, L4 };
}

// Exact lexicographic compare (Python tuple compare; no epsilon)
const levelTup = lv => LEVEL_ORDER.map(o => lv[o]);
const tupLess = (a, b) => {
  for (let i = 0; i < a.length; i++) {
    if (a[i] < b[i]) return true;
    if (a[i] > b[i]) return false;
  }
  return false;
};

const vetoHolds = (a, b) => (pairMin[a]?.[b] ?? 3.0) <= VETO_THRESHOLD;

// ---- Draft: greedy fallback (Python draft_greedy_simple verbatim) ----
function draftGreedySimple(seed) {
  const rnd = MT19937(seed);
  void rnd;
  const teams = Array.from({ length: K }, () => []);
  const bySkillDesc = list => list.slice().sort((a, b) => profiles[b].overall_skill - profiles[a].overall_skill);
  const men = bySkillDesc(rosterNames.filter(n => genderOf[n] === 'M'));
  const women = bySkillDesc(rosterNames.filter(n => genderOf[n] === 'F'));
  const snakeDraft = (pool, slots) => {
    const t = Array.from({ length: K }, () => []);
    const p = pool.slice();
    const maxSlots = slots.length ? Math.max(...slots) : 0;
    for (let r = 0; r < maxSlots; r++) {
      const order = r % 2 === 0
        ? Array.from({ length: K }, (_, i) => i)
        : Array.from({ length: K }, (_, i) => K - 1 - i);
      for (const ti of order) {
        if (t[ti].length >= slots[ti]) continue;
        if (!p.length) break;
        let placed = false;
        for (let ci = 0; ci < p.length; ci++) {
          const cand = p[ci];
          let veto = false;
          for (const existing of [...teams[ti], ...t[ti]]) {
            if (vetoHolds(cand, existing)) { veto = true; break; }
          }
          if (!veto) { t[ti].push(p.splice(ci, 1)[0]); placed = true; break; }
        }
        if (!placed && p.length) t[ti].push(p.shift());
      }
    }
    return t;
  };
  const menTeams = snakeDraft(men, mSlots);
  const womenTeams = snakeDraft(women, fSlots);
  for (let i = 0; i < K; i++) teams[i] = [...menTeams[i], ...womenTeams[i]];
  return [teams, []];
}

// ---- Draft: toxicity-first penalty draft (Python draft_v4 verbatim) ----
function draftV4(seed) {
  buildTiers(mSlots, fSlots);
  const teams = Array.from({ length: K }, () => []);
  const gmean = rosterNames.reduce((s, n) => s + profiles[n].overall_skill, 0) / rosterNames.length;
  const degree = {};
  for (const a of rosterNames) {
    degree[a] = rosterNames.filter(b => a !== b && (pairMin[a]?.[b] ?? 3.0) <= VETO_THRESHOLD).length;
  }
  const rnd = MT19937(seed);
  const keyed = rosterNames.map((n, i) => [n, rnd.random(), i]);
  keyed.sort((a, b) => {
    const dd = degree[b[0]] - degree[a[0]];
    if (dd !== 0) return dd;
    const sd = profiles[b[0]].overall_skill - profiles[a[0]].overall_skill;
    if (sd !== 0) return sd;
    if (a[1] < b[1]) return -1;
    if (a[1] > b[1]) return 1;
    return a[2] - b[2];
  });
  const order = keyed.map(e => e[0]);
  for (const name of order) {
    const g = genderOf[name];
    const cands = [];
    for (let ti = 0; ti < K; ti++) {
      const curM = teams[ti].filter(n => genderOf[n] === 'M').length;
      const curF = teams[ti].length - curM;
      if (g === 'M' && curM >= mSlots[ti]) continue;
      if (g === 'F' && curF >= fSlots[ti]) continue;
      if (teams[ti].length >= mSlots[ti] + fSlots[ti]) continue;
      let addVeto = 0, addLow = 0, willSum = 0;
      for (const e of teams[ti]) {
        const w = pairMin[name]?.[e] ?? 3.0;
        if (vetoHolds(name, e)) addVeto++;
        if (w < WILL_LOW_PAIR) addLow++;
        willSum += w;
      }
      const nteam = teams[ti].length;
      const tavg = nteam
        ? teams[ti].reduce((s, n) => s + profiles[n].overall_skill, 0) / nteam
        : gmean;
      const newAvg = (tavg * nteam + profiles[name].overall_skill) / (nteam + 1);
      const skillDev = Math.abs(newAvg - gmean);
      const wavg = nteam ? willSum / nteam : 5.0;
      cands.push([[addVeto * 100.0 + addLow * 10.0 + skillDev * 2.0 - wavg * 0.5, rnd.random()], ti]);
    }
    if (!cands.length) {
      for (let ti = 0; ti < K; ti++) {
        if (teams[ti].length < mSlots[ti] + fSlots[ti]) {
          let addVeto = 0;
          for (const e of teams[ti]) if (vetoHolds(name, e)) addVeto++;
          cands.push([[addVeto, rnd.random()], ti]);
        }
      }
    }
    cands.sort((a, b) =>
      (a[0][0] - b[0][0]) ||
      (a[0][1] < b[0][1] ? -1 : a[0][1] > b[0][1] ? 1 : 0) ||
      (a[1] - b[1]));
    teams[cands[0][1]].push(name);
  }
  return [teams, []];
}

// ---- Refinement: steepest descent, first improving 2x2 per pair (Python refinement_v4 verbatim) ----
function refinement(teamsIn, relaxIn) {
  let teams = teamsIn.map(t => [...t]);
  const relax = relaxIn.slice();
  const swapLog = [];
  let cur = computeLevels(teams, relax);
  const pyPair = (a, b) => `('${a}', '${b}')`;
  for (let p = 1; p <= MAX_PASSES; p++) {
    let best = null, bestLv = null, bestNt = null;
    for (let a = 0; a < teams.length; a++) {
      for (let b = a + 1; b < teams.length; b++) {
        for (const ma of teams[a].slice()) {
          for (const mb of teams[b].slice()) {
            if (genderOf[ma] !== genderOf[mb]) continue;
            const nt = teams.map(t => [...t]);
            nt[a] = nt[a].filter(n => n !== ma); nt[a].push(mb);
            nt[b] = nt[b].filter(n => n !== mb); nt[b].push(ma);
            const lv = computeLevels(nt, relax);
            if (tupLess(levelTup(lv), levelTup(cur))) {
              if (bestLv === null || tupLess(levelTup(lv), levelTup(bestLv))) {
                best = [a, b, ma, mb, 'swap']; bestLv = lv; bestNt = nt;
              }
            }
          }
        }
        const maM = teams[a].filter(n => genderOf[n] === 'M');
        const maF = teams[a].filter(n => genderOf[n] === 'F');
        const mbM = teams[b].filter(n => genderOf[n] === 'M');
        const mbF = teams[b].filter(n => genderOf[n] === 'F');
        for (const xa of maM) {
          for (const xb of mbM) {
            for (const ya of maF) {
              for (const yb of mbF) {
                const nt = teams.map(t => [...t]);
                nt[a] = nt[a].filter(n => n !== xa && n !== ya); nt[a].push(xb, yb);
                nt[b] = nt[b].filter(n => n !== xb && n !== yb); nt[b].push(xa, ya);
                const lv = computeLevels(nt, relax);
                if (tupLess(levelTup(lv), levelTup(cur))) {
                  if (bestLv === null || tupLess(levelTup(lv), levelTup(bestLv))) {
                    best = [a, b, [xa, ya], [xb, yb], 'swap2x2']; bestLv = lv; bestNt = nt;
                    break;
                  }
                }
              }
            }
          }
        }
      }
    }
    if (best === null) break;
    const [a, b, ma, mb, kind] = best;
    teams = bestNt;
    cur = bestLv;
    swapLog.push({
      pass: p, teams: [a + 1, b + 1],
      swapped: [Array.isArray(ma) ? pyPair(ma[0], ma[1]) : ma,
                Array.isArray(mb) ? pyPair(mb[0], mb[1]) : mb],
      level: kind, before: '', after: '(' + levelTup(bestLv).join(', ') + ')',
    });
  }
  return { teams, swapLog, relax };
}

// ---- Outcome classification (Python classify_outcome verbatim) ----
function classifyOutcome(teams, relax) {
  const lv = computeLevels(teams, relax);
  const avgV = lv.L5 > TEAM_AVG_GAP_THRESHOLD;
  const spreadV = lv.L6 > SPREAD_GAP_THRESHOLD;
  const remaining = [];
  if (lv.L1 !== 0) remaining.push({ level: 'L1_skill_floor', magnitude: lv.L1 });
  if (lv.L2V !== 0) remaining.push({ level: 'L2V_veto_count', magnitude: lv.L2V });
  if (lv.L2 !== 0) remaining.push({ level: 'L2_will_floor', magnitude: lv.L2 });
  if (lv.L2C !== 0) remaining.push({ level: 'L2C_low_pairs', magnitude: lv.L2C });
  if (lv.L3 !== 0) remaining.push({ level: 'L3_specialization', magnitude: lv.L3 });
  if (avgV) remaining.push({ level: 'L5_team_avg_gap', magnitude: lv.L5 });
  if (spreadV) remaining.push({ level: 'L6_spread_gap', magnitude: lv.L6 });
  if (lv.L4 !== 0) remaining.push({ level: 'L4_tier_stacking', magnitude: lv.L4 });
  let status;
  if (!remaining.length && !relax.length) status = 'FEASIBLE';
  else if (!remaining.length) status = 'FEASIBLE_WITH_RELAXATION';
  else if (remaining.length) status = 'FEASIBLE_WITH_REMAINING_SOFT_VIOLATIONS';
  else status = 'FEASIBLE';
  return { status, levels: lv, remaining };
}

// ---- Main multi-start loop (Python v4 main verbatim; raw tuple selection) ----
let bestTup = null, bestLevels = null, bestPack = null;
for (let s = 0; s < NUM_STARTS; s++) {
  const seed = RANDOM_SEED + s * 997;
  let teamsTry, relaxTry;
  try {
    [teamsTry, relaxTry] = draftV4(seed);
  } catch (e) {
    if (!(e instanceof InfeasibleError)) throw e;
    [teamsTry, relaxTry] = draftGreedySimple(seed);
    relaxTry.push({
      team: 0, tier_substituted: 0, adjacent_tier_used: 0, person_placed: 'fallback',
      reason: `Tier draft infeasible (${e.reason}) -> greedy fallback used`,
    });
  }
  const refined = refinement(teamsTry, relaxTry);
  const lv = computeLevels(refined.teams, refined.relax);
  const tup = levelTup(lv);
  if (bestTup === null || tupLess(tup, bestTup)) {
    bestTup = tup;
    bestLevels = lv;
    bestPack = { teams: refined.teams, swapLog: refined.swapLog, relax: refined.relax, lv };
  }
}
const currentTeams = bestPack.teams;
const currentLevels = bestPack.lv;
const swapLog = bestPack.swapLog;
const tierRelaxations = bestPack.relax;
const totalSwaps = swapLog.length;
const classified = classifyOutcome(currentTeams, tierRelaxations);

// 6. Calculate Team Fairness Scores & Grades (0-100 scale, n8n-only extra)
const assignments = [];
const teamMetrics = [];

for (let k = 0; k < K; k++) {
  const teamId = `Team ${k + 1}`;
  const members = currentTeams[k];
  const avg = teamSkillAvg(members);
  const total = Number(members.reduce((sum, n) => sum + profiles[n].overall_skill, 0).toFixed(3));
  const worstW = teamWorstWilling(members);
  const avgW = teamAvgWilling(members);
  const weakest = teamWeakestPair(members);
  const vetoes = teamVetoCount(members);
  const lows = teamLowStats(members).low;
  const spread = teamSpread(members);
  const mCount = members.filter(n => genderOf[n] === 'M').length;
  const fCount = members.length - mCount;

  // Fairness Scoring Formula (from gen_fairness_audit.py)
  const dev = Math.abs(avg - globalAvgSkill);
  const penalty = (vetoes * 22) + (worstW < 2.5 ? 12 : 0) + (lows * 4) + (dev * 28) + (Math.max(0, spread - 0.35) * 30) + (Math.max(0, 2.8 - avgW) * 6);
  const fairnessScore = Math.round(Math.max(0, Math.min(100, 100 - penalty)));
  const fairnessGrade = fairnessScore >= 85 ? 'A' : fairnessScore >= 70 ? 'B' : fairnessScore >= 50 ? 'C' : fairnessScore >= 35 ? 'D' : 'F';

  const flags = [];
  if (vetoes > 0) flags.push(`VETO x${vetoes}`);
  if (worstW < 2.5) flags.push(`LOW_WILLING (${worstW})`);
  if (lows > 0) flags.push(`LOW_PAIRS x${lows}`);
  if (dev > 0.25) flags.push(avg > globalAvgSkill ? 'STACKED' : 'WEAK');
  if (spread > 0.40) flags.push('SPREAD_HIGH');
  if (!flags.length) flags.push('OPTIMAL');

  teamMetrics.push({
    team_id: teamId,
    team_size: members.length,
    team_male_count: mCount,
    team_female_count: fCount,
    team_average_skill: avg,
    team_total_skill: total,
    team_worst_willingness: worstW,
    team_avg_willingness: avgW,
    weakest_pair: `${weakest.p1} & ${weakest.p2} (${weakest.score})`,
    team_veto_count: vetoes,
    team_low_pair_count: teamLowStats(members).low,
    team_spread: spread,
    fairness_score: fairnessScore,
    fairness_grade: fairnessGrade,
    status_flags: flags.join(', '),
  });

  for (const name of members) {
    const prof = profiles[name];
    assignments.push({
      run_id: input.runId,
      team_id: teamId,
      member_display_name: name,
      gender: prof.gender,
      tier: prof.tier ?? 2,
      tier_label: prof.tierLabel ?? 'Tier 2',
      overall_skill: prof.overall_skill,
      devops_skill: prof.final.devops,
      ai_ml_skill: prof.final.ai_ml,
      technical_skill: prof.final.technical,
      involvement_skill: prof.final.involvement,
      team_average_skill: avg,
      team_total_skill: total,
      team_size: members.length,
      team_male_count: mCount,
      team_female_count: fCount,
      team_worst_willingness: worstW,
      team_avg_willingness: avgW,
      weakest_pair: `${weakest.p1} & ${weakest.p2} (${weakest.score})`,
      fairness_score: fairnessScore,
      fairness_grade: fairnessGrade,
      status_flags: flags.join(', '),
    });
  }
}

const allAssigned = assignments.map(a => a.member_display_name);
const uniqueAssigned = new Set(allAssigned);
if (uniqueAssigned.size !== N) {
  throw new Error(`Assignment validation failed: ${uniqueAssigned.size} unique members vs ${N} total`);
}

// Overall Class Fairness Score (0-100)
const overallGap = currentLevels.L5;
const overallFairnessPenalty = (currentLevels.L2V * 15) + (currentLevels.L2 * 10) + (currentLevels.L2C * 5) + (overallGap * 30) + (currentLevels.L6 * 18);
const overallFairnessScore = Math.round(Math.max(0, Math.min(100, 100 - overallFairnessPenalty)));
const overallFairnessGrade = overallFairnessScore >= 85 ? 'A' : overallFairnessScore >= 70 ? 'B' : overallFairnessScore >= 50 ? 'C' : overallFairnessScore >= 35 ? 'D' : 'F';

const audit = {
  run_id: input.runId,
  solver_status: classified.status,
  solver_version: 'FairMatch-v4-Lexicographic-JS',
  overall_fairness_score: overallFairnessScore,
  overall_fairness_grade: overallFairnessGrade,
  team_count: K,
  total_members: N,
  total_males: totalM,
  total_females: totalF,
  refinement_swaps: totalSwaps,
  swap_log: swapLog,
  tier_relaxations: tierRelaxations,
  remaining: classified.remaining,
  levels: currentLevels,
  team_avg_gap: currentLevels.L5,
  global_avg_skill: globalAvgSkill,
  veto_pairs_total: vetoPairs.length,
  veto_pairs_in_teams: currentLevels.L2V,
  hard_constraints_passed: {
    assigned_once: uniqueAssigned.size === N,
    team_sizes: teamMetrics.every((m, i) => m.team_size === teamSizes[i]),
    gender_balanced: teamMetrics.every((m, i) => m.team_male_count === mSlots[i] && m.team_female_count === fSlots[i]),
    no_intra_team_veto: currentLevels.L2V === 0,
  }
};

return [{
  json: {
    run_id: input.runId,
    assignments,
    team_metrics: teamMetrics,
    audit,
    diagnostics: input.diagnostics,
    metadata: input.metadata,
  }
}];
