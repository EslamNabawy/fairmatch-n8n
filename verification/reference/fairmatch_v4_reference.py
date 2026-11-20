"""FairMatch single-file algorithm - EquiTeam v4 willing-first.
Self-contained: scoring + willingness + toxicity-first draft + open refinement + Excel/CSV outputs.
Usage: python fairmatch.py --responses data/responses_final.csv --roster data/roster_final.csv --teams 4
"""
"""
EquiTeam v3 — Formal Algorithm Specification (v2 per uploaded spec)
Hard constraints vs lexicographic weighted violation score. No silent trade-offs.
Implements Sections 0-11 exactly: demand-based tiers, min-willing, lexicographic L1-L5.
"""
import argparse, csv, sys, copy, math, random
from collections import defaultdict, Counter, OrderedDict

ALGORITHM_VERSION = "3.0"

# ── Section 9 Configuration Reference (all tunables in one place)
CONFIG_DEFAULTS = {
    "DISAGREEMENT_THRESHOLD": 1.5,
    "w_peer_tech": 0.8, "w_self_tech": 0.2,          # DevOps/AI/ML/General
    "w_peer_involv": 0.5, "w_self_involv": 0.5,
    "CONSISTENCY_THRESHOLD": 0.75,
    "VETO_THRESHOLD": 1.5,                           # one-directional
    "SPREAD_GAP_THRESHOLD": 0.75,
    "MIN_DIMENSION_COVERAGE": 3.0,
    "MIN_SKILL_FLOOR": None,   # set from data if None
    "MIN_WILL_FLOOR": None,    # set from data if None
    "LEVEL_ORDER": ["L1","L2","L5","L3","L6","L4"],  # Fix: L5 team avg gap right after floors, before spec/tier/spread so skill balance not blocked by tier
    "MAX_PASSES": 3,
    "NUM_STARTS": 1,          # Phase 13 multi-start (1 = deterministic single)
    "RANDOM_SEED": 42,
    "TEAM_AVG_GAP_THRESHOLD": 0.6,  # Fix: between-team avg imbalance target
}

DIMENSIONS = ["devops","ai_ml","technical","involvement"]
TECH_DIMS = ["devops","ai_ml","technical"]

# ── Load ──
def load_roster(path):
    roster={}
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            name=row['name'].strip(); gender=row['gender'].strip().upper()
            if gender not in ('M','F'):
                print(f"WARNING bad gender {gender} for {name}", file=sys.stderr); continue
            roster[name]=gender
    return roster

def load_responses(path):
    rows=[]
    with open(path, newline='', encoding='utf-8') as f:
        reader=csv.DictReader(f)
        cols=[c.lower() for c in reader.fieldnames]
        has4 = any(d in cols for d in DIMENSIONS)
        for raw in reader:
            r={k.lower():v for k,v in raw.items()}
            try:
                rec={"rater":r["rater"].strip(),"target":r["target"].strip()}
                w=None
                for k in ["willing_rating","willing","willingness"]:
                    if k in r and r[k] not in (None,""):
                        w=float(r[k]); break
                rec["willing"]=w if w is not None else 3.0
                if has4:
                    for d in DIMENSIONS:
                        rec[d]= float(r[d]) if d in r and r[d] not in (None,"") else None
                else:
                    sr=None
                    for k in ["skill_rating","skill","overall"]:
                        if k in r and r[k] not in (None,""):
                            sr=float(r[k]); break
                    for d in DIMENSIONS: rec[d]=sr
                rows.append(rec)
            except Exception as e:
                print(f"WARNING skip {raw}: {e}", file=sys.stderr)
    return rows

def pearson(x,y):
    n=len(x)
    if n!=len(y) or n<2: return None
    mx=sum(x)/n; my=sum(y)/n
    num=sum((xi-mx)*(yi-my) for xi,yi in zip(x,y))
    denx=math.sqrt(sum((xi-mx)**2 for xi in x)); deny=math.sqrt(sum((yi-my)**2 for yi in y))
    if denx==0 or deny==0: return 0.0
    return num/(denx*deny)

# ── Section 1: Skill Scoring ──
def compute_profiles(responses, roster, cfg):
    people=set(roster.keys())
    peer_vals=defaultdict(lambda: defaultdict(list))
    self_vals=defaultdict(dict)
    skill_by_rater=defaultdict(list)
    will_by_rater=defaultdict(list)
    for r in responses:
        rater=r["rater"]; target=r["target"]
        if rater==target:
            for d in DIMENSIONS:
                if r[d] is not None: self_vals[target][d]=r[d]
        else:
            if target in people:
                for d in DIMENSIONS:
                    if r[d] is not None: peer_vals[target][d].append(r[d])
                tech=[r[d] for d in TECH_DIMS if r[d] is not None]
                if tech:
                    skill_by_rater[rater].append(sum(tech)/len(tech))
                    will_by_rater[rater].append(r["willing"])
    profiles={}
    diagnostics={"disagreements":[],"rater_consistency":[],"low_flags":[]}
    expected=len(roster)-1
    for name, gender in roster.items():
        prof={"name":name,"gender":gender,"peer":{},"self":{},"final":{},"peer_count":{},"gap":{},"flag":{}}
        for d in DIMENSIONS:
            plist=peer_vals[name][d]
            peer_score= round(sum(plist)/len(plist),3) if plist else None
            peer_count=len(plist)
            has_self=d in self_vals[name]
            self_score=self_vals[name].get(d, None)
            if peer_score is None:
                if has_self: peer_score=self_score; peer_count=0
                else: peer_score=3.0; peer_count=0
            if self_score is None: self_score=peer_score
            prof["peer"][d]=peer_score; prof["peer_count"][d]=peer_count; prof["self"][d]=self_score
            gap=round(self_score - peer_score,3); prof["gap"][d]=gap
            flag=None
            DT=cfg["DISAGREEMENT_THRESHOLD"]
            if gap < -DT:
                flag="UNDER_SELF_RATED"
                diagnostics["disagreements"].append({"person":name,"dim":d,"self":self_score,"peer":peer_score,"gap":gap,"flag":flag})
            elif gap > DT:
                flag="OVER_SELF_RATED"
                diagnostics["disagreements"].append({"person":name,"dim":d,"self":self_score,"peer":peer_score,"gap":gap,"flag":flag})
            prof["flag"][d]=flag
            # 1.4 final
            if flag is not None:
                final=peer_score
            else:
                if d in TECH_DIMS:
                    final=round(cfg["w_peer_tech"]*peer_score + cfg["w_self_tech"]*self_score,3)
                else:
                    final=round(cfg["w_peer_involv"]*peer_score + cfg["w_self_involv"]*self_score,3)
            prof["final"][d]=final
            # low confidence: peer_count < max(3, 30% expected)
            if peer_count < max(3, expected*0.3):
                diagnostics["low_flags"].append(f"{name} {d}: {peer_count}/{expected} peer ratings LOW_CONFIDENCE")
        prof["overall_skill"]=round(sum(prof["final"][d] for d in DIMENSIONS)/len(DIMENSIONS),3)
        profiles[name]=prof
    # 1.6 rater consistency
    for rater, sv in skill_by_rater.items():
        if len(sv) >= 10:
            corr=pearson(sv, will_by_rater[rater])
            if corr is not None and corr > cfg["CONSISTENCY_THRESHOLD"]:
                diagnostics["rater_consistency"].append({"rater":rater,"correlation":round(corr,3),"n":len(sv)})
    return profiles, diagnostics

def build_willing_matrices(responses, roster):
    directed=defaultdict(dict)
    for r in responses:
        if r["rater"] in roster and r["target"] in roster and r["rater"]!=r["target"]:
            directed[r["rater"]][r["target"]]=r["willing"]
    # pair_willing = min per spec 4.1 and 5 note; also keep avg for diagnostics
    pair_min=defaultdict(dict)
    pair_avg=defaultdict(dict)
    for a in roster:
        for b in roster:
            if a==b: continue
            ab=directed.get(a,{}).get(b, 3.0); ba=directed.get(b,{}).get(a, 3.0)
            pair_min[a][b]= min(ab,ba)
            pair_avg[a][b]= round((ab+ba)/2,3)
    return directed, pair_min, pair_avg

# ── Section 2: Gender Balance (size-aware) ──
def gender_slots(total_m, total_f, K):
    N=total_m+total_f
    sizes=[N//K + (1 if i < N%K else 0) for i in range(K)]  # Section 10 sizes
    def distribute(total):
        base=total//K; rem=total%K
        return [base+1 if i<rem else base for i in range(K)]
    m_dist=distribute(total_m)
    f_dist=distribute(total_f)
    # If independent distributions already match sizes, use them
    if all(m+f==s for m,f,s in zip(m_dist,f_dist,sizes)):
        return m_dist, f_dist
    # Otherwise, stagger remainders to meet size constraint: allocate one gender evenly, derive other from sizes
    # Try both orders and pick most even gender distribution (max-min <=1)
    def evenness(slots): return max(slots)-min(slots)
    # Option A: men distributed, women = sizes - men
    f_a=[s - m for s,m in zip(sizes, m_dist)]
    # Option B: women distributed, men = sizes - women
    m_b=[s - f for s,f in zip(sizes, f_dist)]
    # Check validity (non-negative) and evenness
    valid_a=all(x>=0 for x in f_a) and evenness(f_a)<=1
    valid_b=all(x>=0 for x in m_b) and evenness(m_b)<=1
    # For K=4, N=24 case: m_dist [3,3,2,2] f_dist [4,4,3,3] -> sizes [6,6,6,6] -> f_a [3,3,4,4] evenness 1 valid, m_b [2,2,3,3] evenness 1 valid
    # Prefer the option where both genders remain even; choose staggered that keeps both even
    if valid_a and valid_b:
        # Prefer staggering: choose where extra slots not on same teams (minimize variance of sizes, already 0)
        # Both valid, pick A (men first, women staggered) for deterministic
        return m_dist, f_a
    if valid_a:
        return m_dist, f_a
    if valid_b:
        return m_b, f_dist
    # Fallback: independent (will trigger size spread >1 but reported)
    return m_dist, f_dist

def team_sizes_from_slots(m_slots, f_slots):
    return [m+f for m,f in zip(m_slots,f_slots)]

# ── Section 6.0 Pre-flight ──
def preflight_check(roster, K, m_slots, f_slots, cfg):
    errors=[]
    if K > len(roster):
        errors.append(f"team_count {K} > total people {len(roster)} — impossible")
    max_m = max(m_slots) if m_slots else 0
    max_f = max(f_slots) if f_slots else 0
    # Check: any tier demand must be <= pool size (Section 3.1 degenerate case)
    total_m=sum(1 for g in roster.values() if g=='M')
    total_f=len(roster)-total_m
    if sum(m_slots)!=total_m:
        errors.append(f"pool_size != sum(gender_slots) for men: pool {total_m} vs slots {sum(m_slots)}")
    if sum(f_slots)!=total_f:
        errors.append(f"pool_size != sum(gender_slots) for women: pool {total_f} vs slots {sum(f_slots)}")
    return errors

# ── Section 3: Tier construction (demand-based) ──
def build_tiers(profiles, roster, m_slots, f_slots, cfg):
    # per gender, max_slots = max(gender_slots), demand(i)=count teams where slots>=i
    def tiers_for(gender, slots):
        pool=[profiles[n] for n,g in roster.items() if g==gender]
        pool_sorted=sorted(pool, key=lambda p: p["overall_skill"], reverse=True)
        max_slots=max(slots) if slots else 0
        tier_count=max_slots
        # demand per tier index 1..max_slots
        demands=[]
        for i in range(1, max_slots+1):
            demand=sum(1 for s in slots if s >= i)
            demands.append(demand)
        # sanity: sum demands must == pool size
        if sum(demands)!=len(pool_sorted):
            # This should not happen if Section 2 math correct; report
            raise ValueError(f"Tier build mismatch gender {gender}: sum demands {sum(demands)} != pool {len(pool_sorted)} slots {slots} demands {demands}")
        tiers=[]
        idx=0
        for i, dem in enumerate(demands, start=1):
            tier_members=pool_sorted[idx: idx+dem]
            for p in tier_members:
                p["tier"]=i  # 1-indexed per spec
                p["tier_demand"]=dem
            tiers.append(tier_members)
            idx+=dem
        return tiers, demands, tier_count
    m_tiers, m_demands, m_cnt = tiers_for('M', m_slots)
    f_tiers, f_demands, f_cnt = tiers_for('F', f_slots)
    return {"M":(m_tiers,m_demands,m_cnt), "F":(f_tiers,f_demands,f_cnt)}

# ── Helpers for evaluation ──
def team_willingness(team_names, pair_min):
    if len(team_names)<2: return 5.0
    worst=5.0
    for i in range(len(team_names)):
        for j in range(i+1,len(team_names)):
            worst=min(worst, pair_min[team_names[i]][team_names[j]])
    return round(worst,3)

def team_skill_avg(team_names, profiles):
    if not team_names: return 0
    return round(sum(profiles[n]["overall_skill"] for n in team_names)/len(team_names),3)

def team_spread(team_names, profiles):
    if len(team_names)<2: return 0.0
    vals=[profiles[n]["overall_skill"] for n in team_names]
    avg=sum(vals)/len(vals)
    return round(math.sqrt(sum((x-avg)**2 for x in vals)/len(vals)),3)

def team_dim_max(team_names, profiles, dim):
    if not team_names: return 0
    return max(profiles[n]["final"][dim] for n in team_names)

def team_dim_avg(team_names, profiles, dim):
    if not team_names: return 0
    return round(sum(profiles[n]["final"][dim] for n in team_names)/len(team_names),3)

# Fix Section 3-5: explicit between-team avg imbalance vs within-team spread
def team_avg_metrics(teams, profiles):
    avgs=[team_skill_avg(t, profiles) for t in teams]
    if not avgs:
        return {"avgs":avgs,"max":0,"min":0,"gap":0,"std":0,"mean":0}
    gap=round(max(avgs)-min(avgs),3)
    mean=round(sum(avgs)/len(avgs),3)
    std=round((sum((x-mean)**2 for x in avgs)/len(avgs))**0.5,3) if len(avgs)>1 else 0.0
    return {"avgs":avgs,"max":round(max(avgs),3),"min":round(min(avgs),3),"gap":gap,"std":std,"mean":mean}

# ── Section 5: Lexicographic levels ──
def compute_levels_v3base(teams, profiles, pair_min, tier_relaxations, cfg):
    # L1: skill floor violations sum(max(0, floor - avg))
    L1=0
    for t in teams:
        avg=team_skill_avg(t, profiles)
        floor=cfg["MIN_SKILL_FLOOR"]
        if floor is not None and avg < floor:
            L1+= round(floor - avg,3)
    L1=round(L1,3)
    # L2: willingness floor
    L2=0
    for t in teams:
        w=team_willingness(t, pair_min)
        floor=cfg["MIN_WILL_FLOOR"]
        if floor is not None and w < floor:
            L2+= round(floor - w,3)
    L2=round(L2,3)
    # L3: specialization gaps count
    L3=0
    for t in teams:
        for d in TECH_DIMS:  # per 3.5: DevOps, AI/ML, General
            if team_dim_max(t, profiles, d) < cfg["MIN_DIMENSION_COVERAGE"]:
                L3+=1
    # L4: tier relaxations count (passed in)
    L4=len(tier_relaxations)
    # L5: BETWEEN-team average imbalance (FIX: was missing, caused 1.14 gap)
    avg_metrics=team_avg_metrics(teams, profiles)
    L5=avg_metrics["gap"]  # raw gap, continuous penalty
    # L6: WITHIN-team spread-gap (max spread - min spread)
    spreads=[team_spread(t, profiles) for t in teams]
    L6=round(max(spreads)-min(spreads),3) if spreads else 0.0
    return {"L1":L1,"L2":L2,"L3":L3,"L4":L4,"L5":L5,"L6":L6, "spreads":spreads, "avg_metrics":avg_metrics}

def lexicographic_better(levelsA, levelsB, order):
    for lvl in order:
        a=levelsA[lvl]; b=levelsB[lvl]
        if a < b: return True  # A better
        if a > b: return False # B better
    return None  # tie

def levels_tuple(levels, order):
    return tuple(levels[o] for o in order)

# ── Section 3.2 + 3.3 Draft with veto pre-check and adjacent-tier relaxation ──
def veto_holds(a,b,pair_min, cfg):
    # one-directional check: either direction <= threshold triggers veto per 4.1
    # pair_min is min, so min <= threshold means at least one direction <= threshold
    return pair_min[a][b] <= cfg["VETO_THRESHOLD"]

def draft_greedy_simple(profiles, roster, m_slots, f_slots, pair_min, cfg):
    """Fallback for dense veto graphs: gender-balanced snake draft by overall_skill, veto-checked greedily, no tier constraints"""
    K=len(m_slots)
    teams=[[] for _ in range(K)]
    # pools sorted by overall
    men=sorted([n for n,g in roster.items() if g=='M'], key=lambda n: profiles[n]['overall_skill'], reverse=True)
    women=sorted([n for n,g in roster.items() if g=='F'], key=lambda n: profiles[n]['overall_skill'], reverse=True)
    def snake_draft(pool, slots):
        t=[[] for _ in range(K)]
        p=list(pool)
        max_slots=max(slots) if slots else 0
        rnd=random.Random(cfg.get("RANDOM_SEED",42))
        for rnd_idx in range(max_slots):
            order=range(K) if rnd_idx%2==0 else reversed(range(K))
            for ti in order:
                if len(t[ti])>=slots[ti]: continue
                if not p: break
                # find first veto-safe candidate for this team
                placed=False
                for cand_idx, cand in enumerate(p):
                    veto=False
                    for existing in teams[ti] + t[ti]:
                        if veto_holds(cand, existing, pair_min, cfg):
                            veto=True; break
                    if not veto:
                        t[ti].append(p.pop(cand_idx))
                        placed=True
                        break
                if not placed and p:
                    # last resort: place first even if veto
                    t[ti].append(p.pop(0))
        return t
    men_teams=snake_draft(men, m_slots)
    women_teams=snake_draft(women, f_slots)
    for i in range(K):
        teams[i]=men_teams[i]+women_teams[i]
    return teams, []  # no tier relaxations for fallback

def draft_teams(profiles, roster, m_slots, f_slots, pair_min, cfg):
    K=len(m_slots)
    teams=[[] for _ in range(K)]
    tier_info=build_tiers(profiles, roster, m_slots, f_slots, cfg)
    tier_relaxations=[]
    # Multi-start randomness: seed controls jitter within tiers for diversity
    rnd = random.Random(cfg.get("RANDOM_SEED", 42))
    # For each gender independently per Section 3.1
    for gender in ['M','F']:
        tiers, demands, tier_count = tier_info[gender]
        slots = m_slots if gender=='M' else f_slots
        # For each tier_index 1..max_slots
        for tier_idx in range(1, tier_count+1):
            # eligible teams where slots >= tier_idx
            eligible=[t for t in range(K) if slots[t] >= tier_idx]
            assert len(eligible)==demands[tier_idx-1], f"tier {tier_idx} demand {demands[tier_idx-1]} != eligible {len(eligible)}"
            tier_members=tiers[tier_idx-1]  # list of profile dicts
            # order tier members: if NUM_STARTS>1, shuffle within tier using seed for diversity; else deterministic
            if cfg.get("NUM_STARTS",1) > 1:
                tmp=list(tier_members)
                rnd.shuffle(tmp)
                # keep sorted by skill but with shuffle tie-break: stable sort by skill then random order
                tier_members_sorted=sorted(tmp, key=lambda p: (-p["overall_skill"], rnd.random()))
            else:
                tier_members_sorted=sorted(tier_members, key=lambda p: (-p["overall_skill"], p["name"]))
            # Snake order across eligible teams — if multi-start, shuffle eligible order with seed variant
            snake_order = eligible if tier_idx%2==1 else list(reversed(eligible))
            if cfg.get("NUM_STARTS",1) > 1 and rnd.random() < 0.5:
                rnd.shuffle(snake_order)
            # We need to place one member per eligible team
            # For each team in snake_order, try candidates in tier order with veto check
            unplaced=list(tier_members_sorted)  # copy
            for team_idx in snake_order:
                placed=False
                # Try same-tier candidates veto-safe
                for cand_idx, cand_prof in enumerate(list(unplaced)):
                    cand_name=cand_prof["name"]
                    # check veto against existing team members
                    veto=False
                    for existing in teams[team_idx]:
                        if veto_holds(cand_name, existing, pair_min, cfg):
                            veto=True; break
                    if not veto:
                        teams[team_idx].append(cand_name)
                        unplaced.remove(cand_prof)
                        placed=True
                        break
                if placed: continue
                # No same-tier veto-safe -> try adjacent tier (tier_idx ±1) per 3.3, fallback to any same-gender if dense veto (controlled relaxation)
                adjacent_tiers=[]
                for adj in [tier_idx-1, tier_idx+1]:
                    if 1 <= adj <= tier_count:
                        # Find unused members in adjacent tier that are not yet placed elsewhere
                        # But adjacent tier members may already be placed? In draft order, adjacent tiers not yet drafted (if adj > tier_idx) or already drafted (if adj < tier_idx)
                        # Spec 3.3: search adjacent tier for a veto-safe same-gender candidate
                        # We need to consider pool of adjacent tier members not yet assigned
                        adj_members=tiers[adj-1]
                        for cand_prof in sorted(adj_members, key=lambda p: (-p["overall_skill"], p["name"])):
                            cand_name=cand_prof["name"]
                            # check if candidate already placed in any team
                            if any(cand_name in t for t in teams):
                                continue
                            # veto check
                            veto=False
                            for existing in teams[team_idx]:
                                if veto_holds(cand_name, existing, pair_min, cfg):
                                    veto=True; break
                            if not veto:
                                adjacent_tiers.append(cand_prof)
                                break
                        # only first eligible per adjacent tier
                # pick closest adjacent tier candidate (prefer lower distance? spec says tier ±1; if both, pick one deterministically)
                if adjacent_tiers:
                    # deterministic: sort by tier distance then overall_skill then name
                    # Choose tier with smallest distance; if tie, higher skill first
                    cand_prof=sorted(adjacent_tiers, key=lambda p: (abs(p["tier"]-tier_idx), -p["overall_skill"], p["name"]))[0]
                    cand_name=cand_prof["name"]
                    teams[team_idx].append(cand_name)
                    # Remove from its original tier list so it won't be placed again
                    orig_tier=tiers[cand_prof["tier"]-1]
                    if cand_prof in orig_tier:
                        orig_tier.remove(cand_prof)
                    # Also remove from unplaced if it was there (shouldn't be)
                    if cand_prof in unplaced:
                        unplaced.remove(cand_prof)
                    tier_relaxations.append({
                        "team": team_idx+1,
                        "tier_substituted": tier_idx,
                        "adjacent_tier_used": cand_prof["tier"],
                        "person_placed": cand_name,
                        "reason": f"no same-tier veto-safe candidate for tier {tier_idx} team {team_idx+1}; used adjacent tier {cand_prof['tier']}"
                    })
                    placed=True
                    continue
                # Fallback: try any same-gender tier (controlled relaxation for dense veto graphs)
                # This allows feasible placement when adjacent-tier also blocked, but logs as tier relaxation with distance >1
                fallback_candidates=[]
                for adj in range(1, tier_count+1):
                    if adj in [tier_idx, tier_idx-1, tier_idx+1]:
                        continue
                    adj_members=tiers[adj-1]
                    for cand_prof in sorted(adj_members, key=lambda p: (-p["overall_skill"], p["name"])):
                        cand_name=cand_prof["name"]
                        if any(cand_name in t for t in teams):
                            continue
                        veto=False
                        for existing in teams[team_idx]:
                            if veto_holds(cand_name, existing, pair_min, cfg):
                                veto=True; break
                        if not veto:
                            fallback_candidates.append(cand_prof)
                            break
                if fallback_candidates:
                    cand_prof=sorted(fallback_candidates, key=lambda p: (abs(p["tier"]-tier_idx), -p["overall_skill"], p["name"]))[0]
                    cand_name=cand_prof["name"]
                    teams[team_idx].append(cand_name)
                    orig_tier=tiers[cand_prof["tier"]-1]
                    if cand_prof in orig_tier:
                        orig_tier.remove(cand_prof)
                    if cand_prof in unplaced:
                        unplaced.remove(cand_prof)
                    tier_relaxations.append({
                        "team": team_idx+1,
                        "tier_substituted": tier_idx,
                        "adjacent_tier_used": cand_prof["tier"],
                        "person_placed": cand_name,
                        "reason": f"dense veto fallback: no same/adjacent veto-safe for tier {tier_idx} team {team_idx+1}; used far tier {cand_prof['tier']} (distance {abs(cand_prof['tier']-tier_idx)})"
                    })
                    placed=True
                    continue
                # Last resort: place veto-violating candidate (hard violation) to allow output for instructor review
                last_resort=[]
                for adj in range(1, tier_count+1):
                    adj_members=tiers[adj-1]
                    for cand_prof in sorted(adj_members, key=lambda p: (-p["overall_skill"], p["name"])):
                        cand_name=cand_prof["name"]
                        if any(cand_name in t for t in teams):
                            continue
                        last_resort.append(cand_prof)
                        break
                if last_resort:
                    cand_prof=sorted(last_resort, key=lambda p: (abs(p["tier"]-tier_idx), -p["overall_skill"], p["name"]))[0]
                    cand_name=cand_prof["name"]
                    teams[team_idx].append(cand_name)
                    orig_tier=tiers[cand_prof["tier"]-1]
                    if cand_prof in orig_tier:
                        orig_tier.remove(cand_prof)
                    if cand_prof in unplaced:
                        unplaced.remove(cand_prof)
                    tier_relaxations.append({
                        "team": team_idx+1,
                        "tier_substituted": tier_idx,
                        "adjacent_tier_used": cand_prof["tier"],
                        "person_placed": cand_name,
                        "reason": f"HARD VETO VIOLATION fallback: no veto-safe candidate for tier {tier_idx} team {team_idx+1}; placed {cand_name} tier {cand_prof['tier']} despite veto (requires instructor review)"
                    })
                    placed=True
                    continue
                # If still not placed -> infeasible per 6.2
                raise InfeasibleError(f"Team {team_idx+1} tier {tier_idx} gender {gender}: no candidate at all (even veto-violating fallback exhausted)", tier_relaxations, teams)
            # After iterating eligible teams, any leftover unplaced members indicate logic error (should be zero because len==eligible)
            if unplaced:
                # These are members of tier that were skipped due to adjacent-tier substitution taking one from another tier
                # They will be placed when their own tier's turn comes? Actually we consumed one from adjacent tier, so this tier has one leftover
                # Need to keep them for later placement? Spec says every tier supplies exactly demand teams; if we stole from adjacent tier, we now have extra person in current tier unplaced
                # This extra person should be considered for placement in next tier's eligible set? Simpler: keep unplaced and try to place them in remaining teams that still need that gender
                # For now, push them back to pool and let next tier handle? But spec says adjacent-tier relaxation is swapping one person: the team gets adjacent tier person instead of tier person, so the tier person remains unplaced and must go elsewhere
                # That elsewhere must be a team that needs that tier's gender slot but hasn't been filled yet — however all eligible teams for this tier already got someone (or adjacent substitute)
                # So leftover means we have one extra person who couldn't be placed without veto
                # This is the case where even adjacent tier fails for some team, but we found adjacent for this team, leaving original tier member stranded
                # The stranded member will be attempted in its adjacent tier's draft when that tier's turn comes, but that tier's demand already accounts for its own members
                # To avoid miscount, we put leftover back into its tier's list for future consideration as adjacent candidate
                # Keep them in tiers structure for future adjacent searches
                for leftover in unplaced:
                    # Keep tier membership, will be considered as adjacent candidate later
                    pass
                # Log but continue
                # For now, carry leftover forward: add to next tier's pool? Not ideal
                # Instead, try to place leftover into any team that still has remaining gender slots and veto-safe
                for leftover_prof in list(unplaced):
                    leftover_name=leftover_prof["name"]
                    placed2=False
                    for t in range(K):
                        if len([n for n in teams[t] if profiles[n]["gender"]==gender]) < slots[t]:
                            veto=False
                            for existing in teams[t]:
                                if veto_holds(leftover_name, existing, pair_min, cfg):
                                    veto=True; break
                            if not veto:
                                teams[t].append(leftover_name)
                                unplaced.remove(leftover_prof)
                                tier_relaxations.append({
                                    "team": t+1,
                                    "tier_substituted": tier_idx,
                                    "adjacent_tier_used": tier_idx,
                                    "person_placed": leftover_name,
                                    "reason": f"leftover tier {tier_idx} member placed via overflow to team {t+1}"
                                })
                                placed2=True
                                break
                    if not placed2:
                        # Last resort: place even with veto violation
                        for t in range(K):
                            if len([n for n in teams[t] if profiles[n]["gender"]==gender]) < slots[t]:
                                teams[t].append(leftover_name)
                                unplaced.remove(leftover_prof)
                                tier_relaxations.append({
                                    "team": t+1,
                                    "tier_substituted": tier_idx,
                                    "adjacent_tier_used": leftover_prof.get("tier",tier_idx),
                                    "person_placed": leftover_name,
                                    "reason": f"HARD VETO VIOLATION leftover fallback: tier {tier_idx} member {leftover_name} placed to team {t+1} despite veto (dense graph)"
                                })
                                placed2=True
                                break
                    if not placed2:
                        raise InfeasibleError(f"Leftover tier {tier_idx} member {leftover_name} has no team at all", tier_relaxations, teams)
    return teams, tier_relaxations

class InfeasibleError(Exception):
    def __init__(self, reason, tier_relaxations, partial_teams):
        super().__init__(reason)
        self.reason=reason
        self.tier_relaxations=tier_relaxations
        self.partial_teams=partial_teams

# ── Section 7: Refinement deterministic ──
def refinement(teams, profiles, roster, m_slots, f_slots, pair_min, tier_info, cfg, initial_relaxations):
    max_passes=cfg["MAX_PASSES"]
    tier_relaxations=list(initial_relaxations)
    swap_log=[]
    order_all=cfg["LEVEL_ORDER"]  # L1..L5
    # Map level to detection function
    def flagged_teams_for_level(level):
        flagged=[]
        if level=="L1":
            for idx,t in enumerate(teams):
                if team_skill_avg(t, profiles) < cfg["MIN_SKILL_FLOOR"]:
                    flagged.append(idx)
        elif level=="L2":
            for idx,t in enumerate(teams):
                if team_willingness(t, pair_min) < cfg["MIN_WILL_FLOOR"]:
                    flagged.append(idx)
        elif level=="L3":
            for idx,t in enumerate(teams):
                for d in TECH_DIMS:
                    if team_dim_max(t, profiles, d) < cfg["MIN_DIMENSION_COVERAGE"]:
                        flagged.append(idx); break
        elif level=="L4":
            flagged=[]
        elif level=="L5":
            # BETWEEN-team avg imbalance — all teams contribute if gap > threshold
            gap=team_avg_metrics(teams, profiles)["gap"]
            if gap > cfg.get("TEAM_AVG_GAP_THRESHOLD",0.6):
                flagged=list(range(len(teams)))
        elif level=="L6":
            spreads=[team_spread(t, profiles) for t in teams]
            if max(spreads)-min(spreads) > cfg["SPREAD_GAP_THRESHOLD"]:
                flagged=list(range(len(teams)))
        return flagged

    for p in range(1, max_passes+1):
        any_swap=False
        # Process level-by-level per 7.1 last paragraph
        for level in order_all:
            if level=="L4": continue  # tier relax not fixable via swap
            flagged=flagged_teams_for_level(level)
            if not flagged: continue
            flagged=sorted(flagged)  # fixed deterministic order asc team_id
            for t_idx in flagged:
                # members contributing to flag, fixed order ascending name
                members=sorted(teams[t_idx])  # asc name deterministic
                # For each member, try candidates
                best_swap=None
                best_levels=None
                best_new_teams=None
                # Precompute current levels
                cur_levels=compute_levels(teams, profiles, pair_min, tier_relaxations, cfg)
                for m_name in members:
                    # candidate swaps: every same-gender same-or-adjacent tier person in another team, fixed order team_id asc then name asc
                    m_gender=roster[m_name]; m_tier=profiles[m_name].get("tier",1)
                    candidates=[]
                    for ot in sorted(range(len(teams))):
                        if ot==t_idx: continue
                        for cand_name in sorted(teams[ot]):
                            if roster[cand_name]!=m_gender: continue
                            c_tier=profiles[cand_name].get("tier",1)
                            if abs(c_tier - m_tier) >1: continue  # only same or adjacent per 7 + 3.3 bound
                            candidates.append((ot, cand_name))
                    candidates=sorted(candidates)  # team_id asc then name asc (already)
                    for ot, cand_name in candidates:
                        # Hard constraint check L0
                        # Create new teams copy
                        new_teams=copy.deepcopy(teams)
                        # swap
                        new_teams[t_idx].remove(m_name); new_teams[t_idx].append(cand_name)
                        new_teams[ot].remove(cand_name); new_teams[ot].append(m_name)
                        # Hard: gender slots still satisfied? Since same gender swap, counts preserved, sizes preserved -> ok
                        # Hard: veto check entire teams
                        veto_ok=True
                        for chk_idx in (t_idx, ot):
                            tn=new_teams[chk_idx]
                            for i in range(len(tn)):
                                for j in range(i+1,len(tn)):
                                    if veto_holds(tn[i], tn[j], pair_min, cfg):
                                        veto_ok=False; break
                                if not veto_ok: break
                            if not veto_ok: break
                        if not veto_ok: continue
                        # Check lexicographic improvement per 5.4-5.5: must not worsen any level above target, and strictly improve target
                        new_levels=compute_levels(new_teams, profiles, pair_min, tier_relaxations, cfg)
                        # Determine if swap worsens any level above target level
                        target_idx=order_all.index(level)
                        worsens_above=False
                        for above in order_all[:target_idx]:
                            if new_levels[above] > cur_levels[above]:
                                worsens_above=True; break
                        if worsens_above: continue
                        # Must strictly improve target level
                        if new_levels[level] >= cur_levels[level]:
                            continue
                        # Among candidates, pick best (lowest) target level value; tie break earliest fixed order (first encountered wins)
                        if best_levels is None or new_levels[level] < best_levels[level]:
                            best_levels=new_levels
                            best_swap=(t_idx, ot, m_name, cand_name, level, cur_levels[level], new_levels[level])
                            best_new_teams=new_teams
                        # If tie on target level, need to check lexicographic tie-break beyond target (per 5.4)
                        elif new_levels[level]==best_levels[level]:
                            # Compare full lexicographic tuple from target onwards
                            # Use lexicographic_better to see if new is better than best
                            # Build order starting from target
                            sub_order=order_all[target_idx:]
                            # Create dicts for comparison
                            cur_best_tuple=tuple(best_levels[o] for o in sub_order)
                            new_tuple=tuple(new_levels[o] for o in sub_order)
                            if new_tuple < cur_best_tuple:
                                best_levels=new_levels
                                best_swap=(t_idx, ot, m_name, cand_name, level, cur_levels[level], new_levels[level])
                                best_new_teams=new_teams
                if best_swap:
                    # Apply best swap for this team
                    t_idx, ot, m_name, cand_name, lvl, before, after = best_swap
                    teams=best_new_teams
                    swap_log.append({
                        "pass": p,
                        "teams": (t_idx+1, ot+1),
                        "swapped": (m_name, cand_name),
                        "level": lvl,
                        "before": before,
                        "after": after
                    })
                    any_swap=True
                    # After applying swap for this team, break to next team? Spec says after checking all candidates for this team, apply current_best if improves
                    # Continue to next flagged team in same pass with updated teams
        if not any_swap:
            break
    return teams, swap_log, tier_relaxations

# ── Section 6: Outcome classification ──
def classify_outcome(teams, tier_relaxations, profiles, pair_min, cfg):
    levels=compute_levels(teams, profiles, pair_min, tier_relaxations, cfg)
    # L5 team avg gap threshold, L6 spread gap threshold
    avg_violation = levels["L5"] > cfg.get("TEAM_AVG_GAP_THRESHOLD",0.6)
    spread_violation = levels["L6"] > cfg["SPREAD_GAP_THRESHOLD"]
    has_soft_real = (levels["L1"]!=0 or levels["L2"]!=0 or levels["L3"]!=0 or avg_violation or spread_violation)
    has_relax = len(tier_relaxations)>0
    if not has_relax and not has_soft_real:
        status="FEASIBLE"
    elif has_relax and not has_soft_real:
        status="FEASIBLE_WITH_RELAXATION"
    elif has_soft_real:
        status="FEASIBLE_WITH_REMAINING_SOFT_VIOLATIONS"
    else:
        status="FEASIBLE"
    remaining=[]
    if levels["L1"]!=0: remaining.append({"level":"L1_skill_floor","magnitude":levels["L1"]})
    if levels["L2"]!=0: remaining.append({"level":"L2_will_floor","magnitude":levels["L2"]})
    if levels["L3"]!=0: remaining.append({"level":"L3_specialization","magnitude":levels["L3"]})
    if avg_violation: remaining.append({"level":"L5_team_avg_gap","magnitude":levels["L5"]})
    if spread_violation: remaining.append({"level":"L6_spread_gap","magnitude":levels["L6"]})
    return status, levels, remaining

# ── Excel/CSV output ──
def write_outputs(result, profiles, roster, pair_min, pair_avg, diagnostics, cfg, out_teams, out_review, out_excel):
    teams=result["teams"]; tier_relaxations=result["tier_relaxations"]; swap_log=result["swap_log"]
    levels=result["levels"]
    # CSV teams
    with open(out_teams,'w',newline='',encoding='utf-8') as f:
        w=csv.writer(f)
        hdr=["team_id","name","gender","overall_skill","devops","ai_ml","technical","involvement","tier","team_avg","team_total","team_men","team_women","team_worst_willing","team_spread"]
        w.writerow(hdr)
        for idx, team in enumerate(teams,1):
            avg=team_skill_avg(team, profiles); total=round(sum(profiles[n]["overall_skill"] for n in team),3)
            worst=team_willingness(team, pair_min); spread=team_spread(team, profiles)
            for name in sorted(team, key=lambda n: profiles[n]["overall_skill"], reverse=True):
                p=profiles[name]
                w.writerow([idx, name, p["gender"], p["overall_skill"], p["final"]["devops"], p["final"]["ai_ml"], p["final"]["technical"], p["final"]["involvement"], p.get("tier",""), avg, total, sum(1 for n in team if roster[n]=='M'), sum(1 for n in team if roster[n]=='F'), worst, spread])
    # review csv
    with open(out_review,'w',newline='',encoding='utf-8') as f:
        w=csv.writer(f); w.writerow(["type","detail"])
        for s in swap_log:
            w.writerow(["swap_made", f"Pass {s['pass']} Teams {s['teams'][0]}<->{s['teams'][1]} {s['swapped'][0]}<->{s['swapped'][1]} level {s['level']} {s['before']}->{s['after']}"])
        for tr in tier_relaxations:
            w.writerow(["tier_relaxation", f"Team {tr['team']} tier {tr['tier_substituted']} -> adjacent {tr['adjacent_tier_used']} person {tr['person_placed']} reason: {tr['reason']}"])
        for rv in result["remaining"]:
            w.writerow(["remaining_soft_violation", f"{rv['level']} magnitude {rv['magnitude']}"])
        for d in diagnostics["disagreements"]:
            w.writerow(["disagreement_flag", f"{d['person']} {d['dim']} self {d['self']} peer {d['peer']} gap {d['gap']} {d['flag']}"])
        for rc in diagnostics["rater_consistency"]:
            w.writerow(["rater_consistency_flag", f"{rc['rater']} corr {rc['correlation']} n {rc['n']}"])
        for lf in diagnostics["low_flags"]:
            w.writerow(["low_confidence", lf])
        if result["infeasibility_reason"]:
            w.writerow(["infeasibility", result["infeasibility_reason"]])
        w.writerow(["levels", str(levels)])
        w.writerow(["status", result["status"]])
        w.writerow(["config", str(cfg)])
        w.writerow(["summary", f"cost levels {levels} swaps {len(swap_log)} relaxations {len(tier_relaxations)} remaining {len(result['remaining'])} status {result['status']} seed {cfg.get('seed')} v{ALGORITHM_VERSION}"])

def write_excel(result, profiles, roster, pair_min, pair_avg, diagnostics, cfg, path):
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("openpyxl missing"); return
    wb=openpyxl.Workbook()
    hf=Font(name='Calibri', bold=True, color='FFFFFF', size=9)
    hfill=PatternFill(start_color='2F5496', end_color='2F5496', fill_type='solid')
    thin=Border(left=Side(style='thin',color='B4C6E7'),right=Side(style='thin',color='B4C6E7'),top=Side(style='thin',color='B4C6E7'),bottom=Side(style='thin',color='B4C6E7'))
    team_colors=['4472C4','ED7D31','A5A5A5','FFC000','548235']
    # Teams — compact headers (fix: old dumped full dict caused huge column width)
    ws=wb.active; ws.title="Teams"
    ws.merge_cells('A1:O1')
    am= result['levels'].get('avg_metrics', {})
    ws['A1'].value=f"EquiTeam v{ALGORITHM_VERSION} — {result['status']} | gap {am.get('gap','?')} std {am.get('std','?')} | teams {len(result['teams'])} | seed {cfg.get('seed')}"
    ws['A1'].font=Font(bold=True,size=11,color='2F5496'); ws['A1'].alignment=Alignment(horizontal='center')
    ws.merge_cells('A2:O2')
    ws['A2'].value=f"L1 {result['levels']['L1']} | L2 {result['levels']['L2']} | L5 avg_gap {result['levels']['L5']} | L3 spec {result['levels']['L3']} | L6 spread {result['levels']['L6']} | VETO {cfg['VETO_THRESHOLD']} | WILL {cfg['MIN_WILL_FLOOR']} | SKILL {cfg['MIN_SKILL_FLOOR']}"
    ws['A2'].font=Font(italic=True,size=8,color='595959'); ws['A2'].alignment=Alignment(horizontal='center')
    headers=["Team","Name","Gender","Overall","DevOps","AI/ML","Tech","Involv","Tier","Team Avg","Total","M/F","Worst Will","Spread","Status"]
    widths=[8,32,8,8,8,8,8,8,6,8,9,7,8,7,10]
    for i,w in enumerate(widths,1): ws.column_dimensions[get_column_letter(i)].width=w
    for col,h in enumerate(headers,1):
        c=ws.cell(row=4,column=col,value=h); c.font=hf; c.fill=hfill; c.alignment=Alignment(horizontal='center',vertical='center',wrap_text=True); c.border=thin
    ws.row_dimensions[4].height=18
    r=5
    for idx, team in enumerate(result['teams'],1):
        avg=team_skill_avg(team, profiles); total=round(sum(profiles[n]["overall_skill"] for n in team),3)
        worst=team_willingness(team, pair_min); spread=team_spread(team, profiles)
        # check per-team violations for status col
        per_status=[]
        if avg < cfg["MIN_SKILL_FLOOR"]: per_status.append("L1")
        if worst < cfg["MIN_WILL_FLOOR"]: per_status.append("L2")
        spec_gaps=sum(1 for d in TECH_DIMS if team_dim_max(team, profiles, d) < cfg["MIN_DIMENSION_COVERAGE"])
        if spec_gaps: per_status.append(f"L3:{spec_gaps}")
        light=PatternFill(start_color=['D9E1F2','FCE4D6','EDEDED','FFF2CC','E2EFDA'][(idx-1)%5], end_color=['D9E1F2','FCE4D6','EDEDED','FFF2CC','E2EFDA'][(idx-1)%5], fill_type='solid')
        dark=PatternFill(start_color=team_colors[(idx-1)%len(team_colors)], end_color=team_colors[(idx-1)%len(team_colors)], fill_type='solid')
        for name in sorted(team, key=lambda n: profiles[n]["overall_skill"], reverse=True):
            p=profiles[name]
            vals=[f"Team {idx}", name, p["gender"], p["overall_skill"], p["final"]["devops"], p["final"]["ai_ml"], p["final"]["technical"], p["final"]["involvement"], p.get("tier",""), avg, total, f"{sum(1 for n in team if roster[n]=='M')}M/{sum(1 for n in team if roster[n]=='F')}F", worst, spread, ",".join(per_status) if per_status else "OK"]
            ws.row_dimensions[r].height=22
            for col,v in enumerate(vals,1):
                c=ws.cell(row=r,column=col,value=v); c.font=Font(size=8); c.border=thin
                if col==2:
                    c.alignment=Alignment(horizontal='left',vertical='center',wrap_text=True)
                else:
                    c.alignment=Alignment(horizontal='center',vertical='center')
                if col==1: c.fill=dark; c.font=Font(bold=True,color='FFFFFF',size=8)
                else: c.fill=light
                if col in (4,5,6,7,8,10,11,13,14): c.number_format='0.00'
            r+=1
    # Summary
    r+=1
    ws.merge_cells(f'A{r}:O{r}'); ws.cell(row=r,column=1,value=f"TEAM SUMMARY — {result['status']} | tier_relaxations {len(result['tier_relaxations'])} | remaining violations {len(result['remaining'])}").font=Font(bold=True,color='FFFFFF',size=9); ws.cell(row=r,column=1).fill=PatternFill(start_color='2F5496',end_color='2F5496',fill_type='solid'); ws.cell(row=r,column=1).alignment=Alignment(horizontal='center')
    # Compatibility
    ws2=wb.create_sheet("Compatibility")
    ws2.merge_cells('A1:E1'); ws2['A1'].value="Pairwise min willing (L0 veto <= threshold) — worst per team is L2 floor check"; ws2['A1'].font=Font(bold=True,color='2F5496')
    rr=3
    for idx, team in enumerate(result['teams'],1):
        ws2.merge_cells(f'A{rr}:E{rr}'); c=ws2.cell(row=rr,column=1,value=f"Team {idx} worst {team_willingness(team,pair_min)}"); c.font=Font(bold=True,color='FFFFFF'); c.fill=PatternFill(start_color=team_colors[(idx-1)%len(team_colors)],end_color=team_colors[(idx-1)%len(team_colors)],fill_type='solid'); rr+=1
        for col,h in enumerate(["A","B","min willing","avg willing","veto?"],1):
            c=ws2.cell(row=rr,column=col,value=h); c.font=hf; c.fill=hfill; c.border=thin
        rr+=1
        pairs=[]
        for i in range(len(team)):
            for j in range(i+1,len(team)):
                a=team[i]; b=team[j]
                pairs.append((a,b,pair_min[a][b], pair_avg[a][b]))
        for a,b,mn,av in sorted(pairs, key=lambda x: x[2]):
            for col,v in enumerate([a,b,mn,av, "VETO" if mn<=cfg["VETO_THRESHOLD"] else ""],1):
                c=ws2.cell(row=rr,column=col,value=v); c.font=Font(size=8); c.alignment=Alignment(horizontal='center'); c.border=thin
                if col in (3,4): c.number_format='0.00'
                if mn<=cfg["VETO_THRESHOLD"]: c.fill=PatternFill(start_color='F4CCCC',end_color='F4CCCC',fill_type='solid')
            rr+=1
        rr+=1
    for i,w in enumerate([16,16,12,12,8],1): ws2.column_dimensions[get_column_letter(i)].width=w
    # Review Log
    ws3=wb.create_sheet("Review Log")
    ws3.merge_cells('A1:B1'); ws3['A1'].value=f"Review Log v{ALGORITHM_VERSION} status {result['status']}"; ws3['A1'].font=Font(bold=True,color='2F5496')
    ws3.column_dimensions['A'].width=22; ws3.column_dimensions['B'].width=115
    for col,h in enumerate(["Type","Detail"],1):
        c=ws3.cell(row=3,column=col,value=h); c.font=hf; c.fill=hfill; c.border=thin
    rr=4
    rows=[]
    for s in result["swap_log"]: rows.append(("swap_made", f"Pass {s['pass']} Teams {s['teams'][0]}<->{s['teams'][1]} {s['swapped'][0]}<->{s['swapped'][1]} level {s['level']} {s['before']}->{s['after']}"))
    for tr in result["tier_relaxations"]: rows.append(("tier_relaxation", f"Team {tr['team']} tier {tr['tier_substituted']}->adj {tr['adjacent_tier_used']} {tr['person_placed']} : {tr['reason']}"))
    for rv in result["remaining"]: rows.append(("remaining_soft_violation", f"{rv['level']} mag {rv['magnitude']}"))
    for d in diagnostics["disagreements"]: rows.append(("disagreement_flag", f"{d['person']} {d['dim']} self {d['self']} peer {d['peer']} gap {d['gap']} {d['flag']}"))
    for rc in diagnostics["rater_consistency"]: rows.append(("rater_consistency_flag", f"{rc['rater']} corr {rc['correlation']} n={rc['n']}"))
    for lf in diagnostics["low_flags"]: rows.append(("low_confidence", lf))
    rows.append(("levels", str(result["levels"]))); rows.append(("status", result["status"]))
    if result["infeasibility_reason"]: rows.append(("infeasibility", result["infeasibility_reason"]))
    for typ,det in rows:
        a=ws3.cell(row=rr,column=1,value=typ); b=ws3.cell(row=rr,column=2,value=det)
        a.font=Font(bold=True,size=8); b.font=Font(size=8); a.border=thin; b.border=thin
        fill={'swap_made':'FFF2CC','tier_relaxation':'DAEEF3','remaining_soft_violation':'F4CCCC','disagreement_flag':'EAD1DC','rater_consistency_flag':'FCE4D6'}.get(typ,'FFFFFF')
        pf=PatternFill(start_color=fill,end_color=fill,fill_type='solid'); a.fill=pf; b.fill=pf
        b.alignment=Alignment(wrap_text=True,vertical='center'); ws3.row_dimensions[rr].height=14; rr+=1
    # Validation
    ws4=wb.create_sheet("Validation")
    checks=[
        ("Every person assigned exactly once", result["hard_ok"]["assigned_once"]),
        ("Correct number of teams", result["hard_ok"]["team_count"]),
        ("Valid team sizes", result["hard_ok"]["sizes"]),
        ("Gender slots satisfied", result["hard_ok"]["gender"]),
        ("No veto pairs", result["hard_ok"]["no_veto"]),
        ("Skill composition calculated", True),
        ("Willingness floors checked", True),
        ("Spread calculated", True),
        ("Unresolved recorded", True),
    ]
    ws4.column_dimensions['A'].width=42; ws4.column_dimensions['B'].width=14
    for col,h in enumerate(["Check","Pass"],1):
        c=ws4.cell(row=2,column=col,value=h); c.font=hf; c.fill=hfill
    for i,(desc,ok) in enumerate(checks,3):
        ws4.cell(row=i,column=1,value=desc).font=Font(size=9)
        c=ws4.cell(row=i,column=2,value="PASS" if ok else "FAIL"); c.font=Font(bold=True,color='274E13' if ok else 'C00000'); c.fill=PatternFill(start_color='D9EAD3' if ok else 'F4CCCC',end_color='D9EAD3' if ok else 'F4CCCC',fill_type='solid')
    wb.save(path)
    print(f"Wrote {path} sheets={wb.sheetnames}")

def main():
    ap=argparse.ArgumentParser(description=f"EquiTeam v{ALGORITHM_VERSION} — Formal Spec")
    ap.add_argument('--responses', default='responses.csv')
    ap.add_argument('--roster', default='roster.csv')
    ap.add_argument('--teams', type=int, required=True)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--out-teams', default='teams_output_v3.csv')
    ap.add_argument('--out-review', default='review_log_v3.csv')
    ap.add_argument('--out-excel', default='FairMatch_Teams_v3.xlsx')
    for k,v in CONFIG_DEFAULTS.items():
        dash=k.lower().replace('_','-')
        if isinstance(v,float): ap.add_argument(f'--{k.lower()}', f'--{dash}', type=float, default=v)
        elif isinstance(v,int): ap.add_argument(f'--{k.lower()}', f'--{dash}', type=int, default=v)
        elif v is None: ap.add_argument(f'--{k.lower()}', f'--{dash}', type=float, default=None)
        else: ap.add_argument(f'--{k.lower()}', f'--{dash}', default=v)
    args=ap.parse_args()
    cfg=dict(CONFIG_DEFAULTS)
    for k in CONFIG_DEFAULTS:
        val=getattr(args, k.lower(), None)
        if val is not None: cfg[k]=val
    # Derive floors from data if None
    cfg["seed"]=args.seed
    roster=load_roster(args.roster)
    responses=load_responses(args.responses)
    profiles, diagnostics = compute_profiles(responses, roster, cfg)
    directed, pair_min, pair_avg = build_willing_matrices(responses, roster)
    total_m=sum(1 for g in roster.values() if g=='M'); total_f=len(roster)-total_m
    m_slots,f_slots=gender_slots(total_m,total_f, args.teams)
    sizes=team_sizes_from_slots(m_slots,f_slots)
    # preflight
    errors=preflight_check(roster, args.teams, m_slots, f_slots, cfg)
    if errors:
        print("PREFLIGHT ERRORS:")
        for e in errors: print(" ",e)
        # continue but mark infeasible if critical
    if cfg["MIN_SKILL_FLOOR"] is None:
        vals=sorted(p["overall_skill"] for p in profiles.values())
        cfg["MIN_SKILL_FLOOR"]= round(vals[max(0,int(len(vals)*0.1))] -0.3,3)
    if cfg["MIN_WILL_FLOOR"] is None:
        cfg["MIN_WILL_FLOOR"]=2.5
    print(f"Loaded {len(roster)} ppl {total_m}M/{total_f}F v{ALGORITHM_VERSION} K={args.teams} seed={args.seed}")
    print(f"Sizes {sizes} m_slots {m_slots} f_slots {f_slots}")
    print(f"VETO {cfg['VETO_THRESHOLD']} skill_floor {cfg['MIN_SKILL_FLOOR']} will_floor {cfg['MIN_WILL_FLOOR']} coverage {cfg['MIN_DIMENSION_COVERAGE']} spread_thr {cfg['SPREAD_GAP_THRESHOLD']}")
    print(f"Disagreements {len(diagnostics['disagreements'])} rater_consistency {len(diagnostics['rater_consistency'])} low_conf {len(diagnostics['low_flags'])}")
    veto_pairs=[(a,b) for a in roster for b in roster if a<b and pair_min[a][b]<=cfg["VETO_THRESHOLD"]]
    print(f"Veto pairs <= {cfg['VETO_THRESHOLD']}: {len(veto_pairs)} {veto_pairs[:3]}")
    # ── Phase 13: Multi-start optimization (NUM_STARTS) ──
    num_starts=cfg.get("NUM_STARTS",1)
    best_result=None; best_levels=None
    best_teams=None; best_relax=None; best_swaps=None
    infeasible_reason=None
    for start_idx in range(num_starts):
        cfg_try=dict(cfg); cfg_try["RANDOM_SEED"]=cfg["RANDOM_SEED"] + start_idx*997 if "RANDOM_SEED" in cfg else args.seed + start_idx*997
        cfg_try["seed"]=args.seed + start_idx*997
        teams_try=None; relax_try=[]
        try:
            teams_try, relax_try = draft_teams(profiles, roster, m_slots, f_slots, pair_min, cfg_try)
        except InfeasibleError as e:
            # Fallback to greedy without tier constraints for dense veto graphs
            try:
                teams_try, relax_try = draft_greedy_simple(profiles, roster, m_slots, f_slots, pair_min, cfg_try)
                relax_try.append({"team":0,"tier_substituted":0,"adjacent_tier_used":0,"person_placed":"fallback","reason":f"Tier draft infeasible ({e.reason}) -> greedy fallback used"})
                infeasible_reason=e.reason
            except Exception as e2:
                if best_result is None:
                    infeasible_reason=str(e)
                    best_relax=e.tier_relaxations
                continue
        init_levels_try=compute_levels(teams_try, profiles, pair_min, relax_try, cfg_try)
        teams_r_try, swaps_try, relax_try = refinement(teams_try, profiles, roster, m_slots, f_slots, pair_min, {"M":None,"F":None}, cfg_try, relax_try)
        levels_try=compute_levels(teams_r_try, profiles, pair_min, relax_try, cfg_try)
        hard_ok_try = all(pair_min[teams_r_try[t][i]][teams_r_try[t][j]] > cfg_try["VETO_THRESHOLD"] for t in range(len(teams_r_try)) for i in range(len(teams_r_try[t])) for j in range(i+1,len(teams_r_try[t])))
        # For dense veto graphs, allow hard violations but penalize heavily — keep best even with violations
        veto_penalty= sum(1 for t in teams_r_try for i in range(len(t)) for j in range(i+1,len(t)) if pair_min[t[i]][t[j]] <= cfg_try["VETO_THRESHOLD"])*10
        levels_try_adj=dict(levels_try)
        levels_try_adj["L1"]=levels_try["L1"]+veto_penalty  # hijack L1 to penalize veto, ensures veto-free preferred but veto-violating still considered if no alternative
        # lexicographic comparison (use adjusted levels for selection)
        if best_levels is None or lexicographic_better(levels_try_adj, best_levels, cfg["LEVEL_ORDER"]):
            best_levels=levels_try_adj; best_teams=teams_r_try; best_relax=relax_try; best_swaps=swaps_try
            best_result={"teams":teams_r_try,"levels":levels_try,"swaps":swaps_try,"relax":relax_try}
    if best_teams is None:
        reason=infeasible_reason or "All multi-starts infeasible (hard constraints unsatisfiable)"
        print(f"INFEASIBLE after {num_starts} starts: {reason}")
        result={
            "teams":[], "tier_relaxations": best_relax or [], "swap_log":[], "levels":{}, "remaining":[],
            "status":"INFEASIBLE", "infeasibility_reason": reason,
            "hard_ok":{"assigned_once":False,"team_count":False,"sizes":False,"gender":False,"no_veto":False}
        }
        with open(args.out_review,'w',newline='',encoding='utf-8') as f:
            w=csv.writer(f); w.writerow(["type","detail"])
            w.writerow(["infeasibility", reason])
            for tr in (best_relax or []): w.writerow(["tier_relaxation", str(tr)])
        print(f"Wrote {args.out_review} (INFEASIBLE)"); return
    # Use best (original levels for reporting, adjusted was only for selection)
    teams=best_teams; tier_relaxations=best_relax; swap_log=best_swaps; levels=best_result["levels"]
    print(f"Multi-start best among {num_starts} starts: levels {levels} relax {len(tier_relaxations)} swaps {len(swap_log)}")
    # Recompute init for display (pre-refine already inside best, but print final)
    status, _, remaining = classify_outcome(teams, tier_relaxations, profiles, pair_min, cfg)
    # hard checks
    assigned=set(x for t in teams for x in t)
    hard_ok={
        "assigned_once": len(assigned)==len(roster) and sum(len(t) for t in teams)==len(roster),
        "team_count": len(teams)==args.teams,
        "sizes": all(len(t)==s for t,s in zip(teams, sizes)),
        "gender": all(sum(1 for n in t if roster[n]=='M')==ms and sum(1 for n in t if roster[n]=='F')==fs for t,ms,fs in zip(teams, m_slots, f_slots)),
        "no_veto": all(pair_min[t[i]][t[j]] > cfg["VETO_THRESHOLD"] for t in teams for i in range(len(t)) for j in range(i+1,len(t)))
    }
    print(f"\nFinal {status} levels {levels}")
    for i,t in enumerate(teams,1):
        print(f"Team {i} ({len(t)}): {sorted(t)} | avg {team_skill_avg(t,profiles)} worst {team_willingness(t,pair_min)} spread {team_spread(t,profiles)} dim_max {[team_dim_max(t,profiles,d) for d in TECH_DIMS]}")
    print(f"Swaps {len(swap_log)} relaxations {len(tier_relaxations)} remaining {remaining}")
    result={"teams":teams,"tier_relaxations":tier_relaxations,"swap_log":swap_log,"levels":levels,"remaining":remaining,"status":status,"infeasibility_reason":None,"hard_ok":hard_ok}
    write_outputs(result, profiles, roster, pair_min, pair_avg, diagnostics, cfg, args.out_teams, args.out_review, args.out_excel)
    write_excel(result, profiles, roster, pair_min, pair_avg, diagnostics, cfg, args.out_excel)
    print(f"Wrote {args.out_teams}\nWrote {args.out_review}\nWrote {args.out_excel}")

# --- v4 willing-first overrides ---
ALGORITHM_VERSION = "4.0"
CONFIG_DEFAULTS = dict(CONFIG_DEFAULTS)
CONFIG_DEFAULTS.update({
    "LEVEL_ORDER": ["L1", "L2V", "L2", "L2C", "L5", "L3", "L6", "L4"],
    "MAX_PASSES": 6,
    "NUM_STARTS": 20,
    "WILL_LOW_PAIR": 2.5,
})




def team_low_stats(team, pair_min, cfg):
    veto = 0
    low = 0
    tot = 0
    s = 0.0
    n = 0
    for i in range(len(team)):
        for j in range(i + 1, len(team)):
            m = pair_min[team[i]][team[j]]
            tot += 1
            s += m
            n += 1
            if m <= cfg["VETO_THRESHOLD"]:
                veto += 1
            if m < cfg.get("WILL_LOW_PAIR", cfg.get("MIN_WILL_FLOOR", 2.5)):
                low += 1
    avg = round(s / n, 3) if n else 5.0
    return veto, low, avg


def tier_stacking(teams, profiles):
    # fairness-relevant stacking only: excess Tier-1 (top talent) per team
    # full-duplicate counting penalizes inevitable packing in 6-member teams
    pen = 0
    for t in teams:
        c1 = sum(1 for n in t if profiles[n].get("tier") == 1)
        if c1 > 1:
            pen += (c1 - 1)
    return pen


def compute_levels(teams, profiles, pair_min, tier_relaxations, cfg):
    base = compute_levels_v3base(teams, profiles, pair_min, tier_relaxations, cfg)
    L2V = 0
    L2C = 0
    for t in teams:
        v, lo, _ = team_low_stats(t, pair_min, cfg)
        L2V += v
        L2C += lo
    out = dict(base)
    out["L2V"] = L2V
    out["L2C"] = L2C
    out["L4"] = tier_stacking(teams, profiles)
    return out


def draft_v4(profiles, roster, m_slots, f_slots, pair_min, cfg):
    K = len(m_slots)
    # labels for tiers (needed for L4 + reporting)
    build_tiers(profiles, roster, m_slots, f_slots, cfg)
    teams = [[] for _ in range(K)]
    gmean = sum(p["overall_skill"] for p in profiles.values()) / len(profiles)
    # toxicity degree
    degree = {}
    for a in roster:
        d = sum(1 for b in roster if a != b and pair_min[a][b] <= cfg["VETO_THRESHOLD"])
        degree[a] = d
    seed = cfg.get("RANDOM_SEED", 42)
    rnd = random.Random(seed)
    order = sorted(roster.keys(), key=lambda n: (-degree[n], -profiles[n]["overall_skill"], rnd.random()))
    for name in order:
        g = roster[name]
        cands = []
        for ti in range(K):
            cur_m = sum(1 for n in teams[ti] if roster[n] == "M")
            cur_f = len(teams[ti]) - cur_m
            cap_m = m_slots[ti]
            cap_f = f_slots[ti]
            if g == "M" and cur_m >= cap_m:
                continue
            if g == "F" and cur_f >= cap_f:
                continue
            if len(teams[ti]) >= cap_m + cap_f:
                continue
            add_veto = sum(1 for e in teams[ti] if veto_holds(name, e, pair_min, cfg))
            add_low = sum(1 for e in teams[ti] if pair_min[name][e] < cfg.get("WILL_LOW_PAIR", 2.5))
            nteam = len(teams[ti])
            tavg = sum(profiles[n]["overall_skill"] for n in teams[ti]) / nteam if nteam else gmean
            new_avg = (tavg * nteam + profiles[name]["overall_skill"]) / (nteam + 1)
            skill_dev = abs(new_avg - gmean)
            # willing avg to team
            if nteam:
                wavg = sum(pair_min[name][e] for e in teams[ti]) / nteam
            else:
                wavg = 5.0
            cost = (add_veto * 100.0 + add_low * 10.0 + skill_dev * 2.0 - wavg * 0.5, rnd.random())
            cands.append((cost, ti))
        if not cands:
            # overflow: pick least violating team with space
            for ti in range(K):
                if len(teams[ti]) < m_slots[ti] + f_slots[ti]:
                    add_veto = sum(1 for e in teams[ti] if veto_holds(name, e, pair_min, cfg))
                    cands.append(((add_veto, rnd.random()), ti))
        cands.sort()
        teams[cands[0][1]].append(name)
    return teams, []


def refinement_v4(teams, profiles, roster, m_slots, f_slots, pair_min, cfg, relax):
    teams = copy.deepcopy(teams)
    relax = list(relax)
    order = cfg["LEVEL_ORDER"]
    log = []
    cur = compute_levels(teams, profiles, pair_min, relax, cfg)
    for p in range(1, cfg.get("MAX_PASSES", 6) + 1):
        improved = False
        # 1) same-gender swaps any tier, any team pair
        best = None
        best_lv = None
        best_nt = None
        for a in range(len(teams)):
            for b in range(a + 1, len(teams)):
                # same-gender candidates
                for ma in list(teams[a]):
                    for mb in list(teams[b]):
                        if roster[ma] != roster[mb]:
                            continue
                        nt = copy.deepcopy(teams)
                        nt[a].remove(ma); nt[a].append(mb)
                        nt[b].remove(mb); nt[b].append(ma)
                        lv = compute_levels(nt, profiles, pair_min, relax, cfg)
                        tup_new = tuple(lv[o] for o in order)
                        tup_cur = tuple(cur[o] for o in order)
                        if tup_new < tup_cur:
                            if best_lv is None or tup_new < tuple(best_lv[o] for o in order):
                                best = (a, b, ma, mb, "swap")
                                best_lv = lv
                                best_nt = nt
                # 2x2 cross-gender: swap one M + one F each way (preserves counts)
                ma_M = [n for n in teams[a] if roster[n] == "M"]
                ma_F = [n for n in teams[a] if roster[n] == "F"]
                mb_M = [n for n in teams[b] if roster[n] == "M"]
                mb_F = [n for n in teams[b] if roster[n] == "F"]
                for xa in ma_M:
                    for xb in mb_M:
                        for ya in ma_F:
                            for yb in mb_F:
                                nt = copy.deepcopy(teams)
                                nt[a].remove(xa); nt[a].remove(ya); nt[a].extend([xb, yb])
                                nt[b].remove(xb); nt[b].remove(yb); nt[b].extend([xa, ya])
                                lv = compute_levels(nt, profiles, pair_min, relax, cfg)
                                tup_new = tuple(lv[o] for o in order)
                                tup_cur = tuple(cur[o] for o in order)
                                if tup_new < tup_cur:
                                    if best_lv is None or tup_new < tuple(best_lv[o] for o in order):
                                        best = (a, b, (xa, ya), (xb, yb), "swap2x2")
                                        best_lv = lv
                                        best_nt = nt
                                        # cap explosion: take first improving 2x2 per pair
                                        break
                            if best_nt is not None and best == (a, b, (xa, ya), (xb, yb), "swap2x2"):
                                pass
        if best is not None:
            a, b, ma, mb, kind = best
            teams = best_nt
            cur = best_lv
            log.append({"pass": p, "teams": (a + 1, b + 1), "swapped": (str(ma), str(mb)),
                        "level": kind, "before": "", "after": str(tuple(best_lv[o] for o in order))})
            improved = True
        if not improved:
            break
    return teams, log, relax


def classify_outcome(teams, relax, profiles, pair_min, cfg):
    lv = compute_levels(teams, profiles, pair_min, relax, cfg)
    avg_v = lv["L5"] > cfg.get("TEAM_AVG_GAP_THRESHOLD", 0.6)
    spread_v = lv["L6"] > cfg["SPREAD_GAP_THRESHOLD"]
    remaining = []
    if lv["L1"] != 0:
        remaining.append({"level": "L1_skill_floor", "magnitude": lv["L1"]})
    if lv.get("L2V", 0) != 0:
        remaining.append({"level": "L2V_veto_count", "magnitude": lv["L2V"]})
    if lv["L2"] != 0:
        remaining.append({"level": "L2_will_floor", "magnitude": lv["L2"]})
    if lv.get("L2C", 0) != 0:
        remaining.append({"level": "L2C_low_pairs", "magnitude": lv["L2C"]})
    if lv["L3"] != 0:
        remaining.append({"level": "L3_specialization", "magnitude": lv["L3"]})
    if avg_v:
        remaining.append({"level": "L5_team_avg_gap", "magnitude": lv["L5"]})
    if spread_v:
        remaining.append({"level": "L6_spread_gap", "magnitude": lv["L6"]})
    if lv.get("L4", 0) != 0:
        remaining.append({"level": "L4_tier_stacking", "magnitude": lv["L4"]})
    if not remaining and not relax:
        status = "FEASIBLE"
    elif not remaining:
        status = "FEASIBLE_WITH_RELAXATION"
    else:
        status = "FEASIBLE_WITH_REMAINING_SOFT_VIOLATIONS"
    return status, lv, remaining


def main():
    ap = argparse.ArgumentParser(description="EquiTeam v4 willing-first")
    ap.add_argument("--responses", default="responses.csv")
    ap.add_argument("--roster", default="roster.csv")
    ap.add_argument("--teams", type=int, required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-teams", default="teams_output_v4.csv")
    ap.add_argument("--out-review", default="review_log_v4.csv")
    ap.add_argument("--out-excel", default="FairMatch_Teams_v4.xlsx")
    for k, v in CONFIG_DEFAULTS.items():
        dash = k.lower().replace("_", "-")
        if isinstance(v, float):
            ap.add_argument("--" + k.lower(), "--" + dash, type=float, default=v)
        elif isinstance(v, int):
            ap.add_argument("--" + k.lower(), "--" + dash, type=int, default=v)
        elif v is None:
            ap.add_argument("--" + k.lower(), "--" + dash, type=float, default=None)
        else:
            ap.add_argument("--" + k.lower(), "--" + dash, default=v)
    args = ap.parse_args()
    cfg = dict(CONFIG_DEFAULTS)
    for k in CONFIG_DEFAULTS:
        val = getattr(args, k.lower(), None)
        if val is not None:
            cfg[k] = val
    cfg["seed"] = args.seed
    roster = load_roster(args.roster)
    responses = load_responses(args.responses)
    profiles, diagnostics = compute_profiles(responses, roster, cfg)
    directed, pair_min, pair_avg = build_willing_matrices(responses, roster)
    total_m = sum(1 for g in roster.values() if g == "M")
    total_f = len(roster) - total_m
    m_slots, f_slots = gender_slots(total_m, total_f, args.teams)
    sizes = team_sizes_from_slots(m_slots, f_slots)
    errs = preflight_check(roster, args.teams, m_slots, f_slots, cfg)
    for e in errs:
        print("PREFLIGHT:", e)
    if cfg["MIN_SKILL_FLOOR"] is None:
        vals = sorted(p["overall_skill"] for p in profiles.values())
        cfg["MIN_SKILL_FLOOR"] = round(vals[max(0, int(len(vals) * 0.1))] - 0.3, 3)
    if cfg["MIN_WILL_FLOOR"] is None:
        cfg["MIN_WILL_FLOOR"] = 2.5
    print(f"Loaded {len(roster)} ppl {total_m}M/{total_f}F v{ALGORITHM_VERSION} K={args.teams} seed={args.seed}")
    print(f"VETO {cfg['VETO_THRESHOLD']} will_floor {cfg['MIN_WILL_FLOOR']} low_pair {cfg['WILL_LOW_PAIR']}")
    veto_pairs = [(a, b) for a in roster for b in roster if a < b and pair_min[a][b] <= cfg["VETO_THRESHOLD"]]
    print(f"Veto pairs: {len(veto_pairs)}")
    num_starts = cfg.get("NUM_STARTS", 20)
    best = None
    best_tup = None
    best_pack = None
    for s in range(num_starts):
        c = dict(cfg)
        c["RANDOM_SEED"] = cfg.get("RANDOM_SEED", args.seed) + s * 997
        c["seed"] = args.seed + s * 997
        teams_try, relax_try = draft_v4(profiles, roster, m_slots, f_slots, pair_min, c)
        teams_r, log_r, relax_r = refinement_v4(teams_try, profiles, roster, m_slots, f_slots, pair_min, c, relax_try)
        lv = compute_levels(teams_r, profiles, pair_min, relax_r, c)
        tup = tuple(lv[o] for o in c["LEVEL_ORDER"])
        if best_tup is None or tup < best_tup:
            best_tup = tup
            best = lv
            best_pack = (teams_r, log_r, relax_r, lv)
    teams, swap_log, relax, levels = best_pack
    status, _, remaining = classify_outcome(teams, relax, profiles, pair_min, cfg)
    assigned = set(x for t in teams for x in t)
    hard_ok = {
        "assigned_once": len(assigned) == len(roster) and sum(len(t) for t in teams) == len(roster),
        "team_count": len(teams) == args.teams,
        "sizes": all(len(t) == s for t, s in zip(teams, sizes)),
        "gender": all(sum(1 for n in t if roster[n] == "M") == ms and sum(1 for n in t if roster[n] == "F") == fs for t, ms, fs in zip(teams, m_slots, f_slots)),
        "no_veto": all(pair_min[t[i]][t[j]] > cfg["VETO_THRESHOLD"] for t in teams for i in range(len(t)) for j in range(i + 1, len(t))),
    }
    print(f"Best {status} levels {levels} swaps {len(swap_log)} remaining {remaining} hard {hard_ok}")
    for i, t in enumerate(teams, 1):
        print(f"Team {i}: {sorted(t)} | avg {team_skill_avg(t, profiles)} worst {team_willingness(t, pair_min)} spread {team_spread(t, profiles)}")
    result = {"teams": teams, "tier_relaxations": relax, "swap_log": swap_log, "levels": levels,
              "remaining": remaining, "status": status, "infeasibility_reason": None, "hard_ok": hard_ok}
    # v3 writers expect swap dict keys teams/swapped/level/before/after + tier keys — ours match loosely
    write_outputs(result, profiles, roster, pair_min, pair_avg, diagnostics, cfg, args.out_teams, args.out_review, args.out_excel)
    write_excel(result, profiles, roster, pair_min, pair_avg, diagnostics, cfg, args.out_excel)
    print(f"Wrote {args.out_teams} {args.out_review} {args.out_excel}")


if __name__ == "__main__":
    main()
