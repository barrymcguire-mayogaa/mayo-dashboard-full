#!/usr/bin/env python3
"""
Mayo GAA Dashboard Auto-Update Script
======================================
Trigger phrase:  update dashboard 'ROUND' Opponent Venue
Examples:
  update dashboard 'AISFC Rd.1' Tyrone Away
  update dashboard 'CSFC Final' Kerry Home
  update dashboard 'Rd.1' Galway Home

CLI usage:
  python3 update_dashboard.py 'ROUND' Opponent Venue [--xml /path/to/file.xml] [--gk hennelly|livingstone]

If called with no args (or just 'update dashboard'), prints usage reminder.
"""
import sys, re, json, os, glob, subprocess
import xml.etree.ElementTree as ET

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DASHBOARD = os.path.join(BASE_DIR, 'mayo-dashboard.html')
XML_DIR   = os.path.join(BASE_DIR, 'NFL Timelines')

# ── Period config ─────────────────────────────────────────────────────────────
PERIOD_BOUNDS = [0, 12, 24, 35, 47, 59, 9999]
N_PERIODS = 6

# ── Season-aggregate source/KO constants ─────────────────────────────────────
SOURCE_CAT_MAP = {
    'FORCED TURNOVER': 'to', 'UNFORCED TURNOVER': 'to', 'BALL RECOVERED': 'to',
    'OWN KICKOUT': 'ownKO', 'OPP KICKOUT': 'oppKO',
    'FREE WON': 'freeWon', 'THROW-IN': 'throwIn',
}
SOURCES = ['to', 'ownKO', 'oppKO', 'freeWon', 'throwIn']
SOURCE_DISPLAY = {
    'to': 'Turnover', 'ownKO': 'Own KO', 'oppKO': 'Opp KO',
    'freeWon': 'Free Won', 'throwIn': 'Throw-in',
}
WON_KO_OUTCOMES = {'KO WON CLEAN', 'KO BREAK WON', 'KO SIDELINE WON'}
KO_OUTCOME_DISPLAY = {
    'KO WON CLEAN': 'Won Clean', 'KO BREAK WON': 'Break Won',
    'KO BREAK LOST': 'Break Lost', 'KO LOST CLEAN': 'Lost Clean',
    'KO SIDELINE WON': 'Sideline Won', 'KO SIDELINE LOST': 'Sideline Lost',
    'KO FREE WON': 'Free Won', 'KO FREE LOST': 'Free Lost',
}
KO_LOC_MAP = {'KO SHORT': 'short', 'KO MEDIUM': 'medium', 'KO LONG': 'long'}

def get_period(gm):
    for i in range(N_PERIODS):
        if PERIOD_BOUNDS[i] <= gm < PERIOD_BOUNDS[i+1]:
            return i
    return N_PERIODS - 1

# ── Competition category ──────────────────────────────────────────────────────
def comp_category(round_label):
    if re.match(r'^Rd\.', round_label, re.IGNORECASE):
        return 'league'
    return 'championship'

# ── XML parsing ───────────────────────────────────────────────────────────────
def parse_xml(xml_path):
    with open(xml_path, 'rb') as f:
        raw = f.read()
    text = raw.decode('utf-16') if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else raw.decode('utf-8', errors='replace')
    tree = ET.fromstring(text)
    instances = tree.findall('ALL_INSTANCES/instance')

    H1_START = H1_END = H2_START = H2_END = None
    for inst in instances:
        code = inst.findtext('code', '').strip()
        if code == '1st Half':
            H1_START = float(inst.findtext('start', 0))
            H1_END   = float(inst.findtext('end', 0))
        elif code == '2nd Half':
            H2_START = float(inst.findtext('start', 0))
            H2_END   = float(inst.findtext('end', 0))

    if None in (H1_START, H1_END, H2_START):
        raise ValueError("Half markers not found in XML — check file.")

    def game_min(ts):
        if ts <= H1_END:
            return (ts - H1_START) / 60.0
        return (H1_END - H1_START) / 60.0 + (ts - H2_START) / 60.0

    def get_half(ts):
        return 1 if ts <= H1_END else 2

    def period_of(ts):
        return get_period(game_min(ts))

    def labels_of(inst):
        d = {}
        for lbl in inst.findall('label'):
            g = lbl.findtext('group', '').strip()
            t = lbl.findtext('text',  '').strip()
            d.setdefault(g, []).append(t)
        return d

    def first_lbl(lbls, group, default='Unknown'):
        return lbls.get(group, [default])[0]

    mayo_shots, opp_shots = [], []
    mayo_kos,   opp_kos   = [], []
    mayo_attacks, opp_attacks = [], []
    mayo_poss,  opp_poss  = [], []
    mayo_tos,   opp_tos   = [], []
    mayo_fouls, opp_fouls = [], []
    mayo_tackles = []
    mayo_scores, opp_scores = [], []
    mayo_wides,  opp_wides  = [], []
    opp_team_upper = None

    for inst in instances:
        code = inst.findtext('code', '').strip()
        ts   = float(inst.findtext('start', 0))
        end  = float(inst.findtext('end',   ts))
        lbls = labels_of(inst)

        # ── Mayo shots ───────────────────────────────────────────────────
        if code in ('MAYO SHOT OPEN PLAY', 'MAYO SHOT DEADBALL'):
            stype  = 'deadball' if 'DEADBALL' in code else 'play'
            oc     = first_lbl(lbls, 'Shot Outcomes', '')
            at_raw = first_lbl(lbls, 'Shot Attempts', '1 Point Attempt')
            x      = int(first_lbl(lbls, 'X-Shot', '50'))
            y      = int(first_lbl(lbls, 'Y-Shot', '50'))
            player = first_lbl(lbls, 'Mayo Player Labels', 'Unknown')
            at_map = {'1 Point Attempt':'pt1Att','2 Point Attempt':'pt2Att','Goal Attempt':'goalAtt'}
            att    = at_map.get(at_raw, 'pt1Att')
            if oc == '1 POINT':   outcome = '1pt'
            elif oc == '2 POINT': outcome = '2pt'
            elif oc == 'GOAL':    outcome = 'goal'
            else:                 outcome = 'miss'
            mayo_shots.append({'ts':ts,'x':x,'y':y,'stype':stype,'outcome':outcome,
                                'player':player,'att':att,'oc_raw':oc,'at_raw':at_raw})

        # ── Opp shots ────────────────────────────────────────────────────
        elif ('SHOT OPEN PLAY' in code or 'SHOT DEADBALL' in code) and 'MAYO' not in code:
            stype  = 'deadball' if 'DEADBALL' in code else 'play'
            oc     = first_lbl(lbls, 'Shot Outcomes', '')
            at_raw = first_lbl(lbls, 'Shot Attempts', '1 Point Attempt')
            x      = int(first_lbl(lbls, 'X-Shot_away', '50'))
            y      = int(first_lbl(lbls, 'Y-Shot_away', '50'))
            at_map = {'1 Point Attempt':'pt1Att','2 Point Attempt':'pt2Att','Goal Attempt':'goalAtt'}
            att    = at_map.get(at_raw, 'pt1Att')
            if oc == '1 POINT':   outcome = '1pt'
            elif oc == '2 POINT': outcome = '2pt'
            elif oc == 'GOAL':    outcome = 'goal'
            else:                 outcome = 'miss'
            opp_shots.append({'ts':ts,'x':x,'y':y,'stype':stype,'outcome':outcome,
                               'att':att,'oc_raw':oc,'at_raw':at_raw})

        # ── Mayo KO ──────────────────────────────────────────────────────
        elif code == 'MAYO KO':
            x   = int(first_lbl(lbls, 'X-KOs', '50'))
            y   = int(first_lbl(lbls, 'Y-KOs', '50'))
            oc  = first_lbl(lbls, 'Kickout Outcomes', '')
            loc = first_lbl(lbls, 'Kickout Locations', 'KO LONG')
            won = 1 if oc in ('KO WON CLEAN','KO BREAK WON','KO SIDELINE WON') else 0
            lmap = {'KO SHORT':'short','KO MEDIUM':'medium','KO LONG':'long'}
            mayo_kos.append({'ts':ts,'x':x,'y':y,'won':won,'loc':lmap.get(loc,'long')})

        # ── Opp KO ───────────────────────────────────────────────────────
        elif code.endswith(' KO') and 'MAYO' not in code:
            x   = int(first_lbl(lbls, 'X-KOs_away', '50'))
            y   = int(first_lbl(lbls, 'Y-KOs_away', '50'))
            oc  = first_lbl(lbls, 'Kickout Outcomes', '')
            won = 1 if oc in ('KO WON CLEAN','KO BREAK WON') else 0
            opp_kos.append({'ts':ts,'x':x,'y':y,'opp_won':won})
            if opp_team_upper is None:
                opp_team_upper = code[:-3].strip()

        # ── Attacks ──────────────────────────────────────────────────────
        elif code == 'MAYO ATTACKS':
            players = lbls.get('Mayo Player Labels', [])
            mayo_attacks.append({'ts':ts,'end':end,'dur':end-ts,'players':players})
        elif code.endswith(' ATTACKS') and 'MAYO' not in code:
            opp_attacks.append({'ts':ts,'end':end,'dur':end-ts})

        # ── Possession ───────────────────────────────────────────────────
        elif code == 'MAYO TEAM POSSESSION':
            mayo_poss.append({'ts':ts,'end':end,'dur':end-ts})
        elif 'TEAM POSSESSION' in code and 'MAYO' not in code:
            opp_poss.append({'ts':ts,'end':end,'dur':end-ts})

        # ── Turnovers ────────────────────────────────────────────────────
        elif code == 'MAYO TOs':
            mayo_tos.append({'ts':ts})
        elif code.endswith(' TOs') and 'MAYO' not in code:
            opp_tos.append({'ts':ts})
            if opp_team_upper is None:
                opp_team_upper = code[:-4].strip()

        # ── Fouls ────────────────────────────────────────────────────────
        elif code == 'MAYO FOUL' or code == 'MAYO TECHNICAL FOUL':
            mayo_fouls.append({'ts':ts})
        elif (code.endswith(' FOUL') or code.endswith(' TECHNICAL FOUL')) and 'MAYO' not in code:
            opp_fouls.append({'ts':ts})

        # ── Tackles ──────────────────────────────────────────────────────
        elif code == 'MAYO TACKLE':
            player = first_lbl(lbls, 'Mayo Player Labels', 'Unknown')
            mayo_tackles.append({'ts':ts,'player':player})

        # ── Scoring events ───────────────────────────────────────────────
        elif code == 'MAYO 1 POINT':
            p = first_lbl(lbls, 'Mayo Player Labels', 'Unknown')
            mayo_scores.append({'ts':ts,'type':'1pt','player':p,
                                'half':get_half(ts),'minute':round(game_min(ts),1)})
        elif code == 'MAYO 2 POINT':
            p = first_lbl(lbls, 'Mayo Player Labels', 'Unknown')
            mayo_scores.append({'ts':ts,'type':'2pt','player':p,
                                'half':get_half(ts),'minute':round(game_min(ts),1)})
        elif code == 'MAYO GOAL':
            p = first_lbl(lbls, 'Mayo Player Labels', 'Unknown')
            mayo_scores.append({'ts':ts,'type':'goal','player':p,
                                'half':get_half(ts),'minute':round(game_min(ts),1)})
        elif code.endswith(' 1 POINT') and 'MAYO' not in code:
            opp = code[:-8].strip()
            p = first_lbl(lbls, f'{opp.title()} Player Labels', 'Unknown')
            opp_scores.append({'ts':ts,'type':'1pt','player':p,
                               'half':get_half(ts),'minute':round(game_min(ts),1)})
            if opp_team_upper is None: opp_team_upper = opp
        elif code.endswith(' 2 POINT') and 'MAYO' not in code:
            opp = code[:-8].strip()
            p = first_lbl(lbls, f'{opp.title()} Player Labels', 'Unknown')
            opp_scores.append({'ts':ts,'type':'2pt','player':p,
                               'half':get_half(ts),'minute':round(game_min(ts),1)})
        elif code.endswith(' GOAL') and 'MAYO' not in code and 'CHANCE' not in code:
            opp = code[:-5].strip()
            p = first_lbl(lbls, f'{opp.title()} Player Labels', 'Unknown')
            opp_scores.append({'ts':ts,'type':'goal','player':p,
                               'half':get_half(ts),'minute':round(game_min(ts),1)})

        # ── Wides ────────────────────────────────────────────────────────
        elif code == 'MAYO WIDE':
            mayo_wides.append({'ts':ts})
        elif code.endswith(' WIDE') and 'MAYO' not in code:
            opp_wides.append({'ts':ts})

    # Fallback opp team name
    if opp_team_upper is None:
        for inst in instances:
            c = inst.findtext('code','').strip()
            if c.endswith(' ATTACKS') and 'MAYO' not in c:
                opp_team_upper = c[:-8].strip()
                break
    opp_team_upper = opp_team_upper or 'OPPONENT'

    return {
        'H1_START':H1_START,'H1_END':H1_END,'H2_START':H2_START,'H2_END':H2_END,
        'game_min':game_min,'period_of':period_of,'get_half':get_half,
        'mayo_shots':mayo_shots,'opp_shots':opp_shots,
        'mayo_kos':mayo_kos,'opp_kos':opp_kos,
        'mayo_attacks':mayo_attacks,'opp_attacks':opp_attacks,
        'mayo_poss':mayo_poss,'opp_poss':opp_poss,
        'mayo_tos':mayo_tos,'opp_tos':opp_tos,
        'mayo_fouls':mayo_fouls,'opp_fouls':opp_fouls,
        'mayo_tackles':mayo_tackles,
        'mayo_scores':mayo_scores,'opp_scores':opp_scores,
        'mayo_wides':mayo_wides,'opp_wides':opp_wides,
        'opp_team_upper':opp_team_upper,
    }

# ── Compute helpers ───────────────────────────────────────────────────────────
def score_totals(scores):
    """Return (goals, pt2, pt1, total_value) from a list of score events."""
    g = p2 = p1 = 0
    for s in scores:
        if s['type'] == 'goal': g  += 1
        elif s['type'] == '2pt': p2 += 1
        else:                    p1 += 1
    return g, p2, p1, g*3 + p2*2 + p1

def score_string(goals, pt2, pt1):
    pts_str = pt2*2 + pt1
    total   = goals*3 + pt2*2 + pt1
    return f"{goals}-{pts_str} ({total})"

def compute_scorers(mayo_scores):
    """Return dict player→scoring_value."""
    d = {}
    for s in mayo_scores:
        p = s['player']
        if p in ('Unknown','?'): continue
        v = 3 if s['type']=='goal' else 2 if s['type']=='2pt' else 1
        d[p] = d.get(p,0) + v
    return d

def shot_acc(shots):
    if not shots: return 0.0
    scored = sum(1 for s in shots if s['oc_raw'] in ('1 POINT','2 POINT','GOAL'))
    return round(scored / len(shots) * 100, 1)

def ko_win_pct(kos, won_key='won'):
    if not kos: return 0.0
    won = sum(k[won_key] for k in kos)
    return round(won / len(kos) * 100, 1)

def build_flags(round_label, opponent, venue, parsed, mayo_goals, mayo_pt2, mayo_pt1,
                opp_goals, opp_pt2, opp_pt1, scorers, mayo_goal_att, opp_goal_att):
    mayo_total = mayo_goals*3 + mayo_pt2*2 + mayo_pt1
    opp_total  = opp_goals*3  + opp_pt2*2  + opp_pt1
    diff = mayo_total - opp_total
    flags = []

    if diff > 0:
        flags.append(f'✅ Mayo won by {diff} point{"s" if diff!=1 else ""}.')
    elif diff < 0:
        flags.append(f'⚠️ {opponent} won by {-diff} point{"s" if -diff!=1 else ""}.')
    else:
        flags.append('ℹ️ Match ended level.')

    ms_acc = shot_acc(parsed['mayo_shots'])
    os_acc = shot_acc(parsed['opp_shots'])
    if ms_acc >= 65: flags.append(f'✅ Mayo clinical — {ms_acc:.1f}% accuracy ({sum(1 for s in parsed["mayo_shots"] if s["oc_raw"] in ("1 POINT","2 POINT","GOAL"))}/{len(parsed["mayo_shots"])}).')
    if ms_acc < 45:  flags.append(f'⚠️ Mayo shot accuracy low at {ms_acc:.1f}% ({sum(1 for s in parsed["mayo_shots"] if s["oc_raw"] in ("1 POINT","2 POINT","GOAL"))}/{len(parsed["mayo_shots"])}).')
    if os_acc >= 65: flags.append(f'✅ {opponent} clinical — {os_acc:.1f}% accuracy.')
    if os_acc < 45:  flags.append(f'⚠️ {opponent} shot accuracy low at {os_acc:.1f}%.')

    mko_pct = ko_win_pct(parsed['mayo_kos'])
    oko_pct = ko_win_pct(parsed['opp_kos'], 'opp_won')
    if mko_pct >= 70: flags.append(f'✅ Mayo dominated kickouts — {mko_pct:.1f}% ({sum(k["won"] for k in parsed["mayo_kos"])}/{len(parsed["mayo_kos"])}).')
    if oko_pct <= 40: flags.append(f'⚠️ {opponent} kickout struggles — {oko_pct:.1f}% ({sum(k["opp_won"] for k in parsed["opp_kos"])}/{len(parsed["opp_kos"])}).')
    if oko_pct >= 70: flags.append(f'⚠️ {opponent} KO dominance — {oko_pct:.1f}% ({sum(k["opp_won"] for k in parsed["opp_kos"])}/{len(parsed["opp_kos"])}).')

    if opp_pt2 >= 2: flags.append(f'✅ {opponent} scored {opp_pt2} two-pointers = {opp_pt2*2} extra pts.')
    if mayo_pt2 >= 2: flags.append(f'✅ Mayo scored {mayo_pt2} two-pointers = {mayo_pt2*2} extra pts.')

    if scorers:
        top = max(scorers, key=scorers.get)
        flags.append(f'🌟 Top scorer: {top} with {scorers[top]} points.')

    if mayo_goal_att > 0: flags.append(f'ℹ️ Mayo created {mayo_goal_att} goal chance{"s" if mayo_goal_att!=1 else ""}.')
    if opp_goal_att > 0:  flags.append(f'ℹ️ {opponent} created {opp_goal_att} goal chance{"s" if opp_goal_att!=1 else ""}.')

    return flags

# ── Shot period data ──────────────────────────────────────────────────────────
def build_shot_period_data(parsed):
    period_of = parsed['period_of']
    zero6 = lambda: [0]*6
    mayo_pd = {k: zero6() for k in ('total','scored','pt1Att','pt1','pt2Att','pt2','goalAtt','goal')}
    opp_pd  = {k: zero6() for k in ('total','scored')}

    for s in parsed['mayo_shots']:
        p  = period_of(s['ts'])
        at = s['at_raw']
        oc = s['oc_raw']
        mayo_pd['total'][p] += 1
        if oc in ('1 POINT','2 POINT','GOAL'): mayo_pd['scored'][p] += 1
        if at == '1 Point Attempt':
            mayo_pd['pt1Att'][p] += 1
            if oc == '1 POINT': mayo_pd['pt1'][p] += 1
        elif at == '2 Point Attempt':
            mayo_pd['pt2Att'][p] += 1
            if oc == '2 POINT': mayo_pd['pt2'][p] += 1
        elif at == 'Goal Attempt':
            mayo_pd['goalAtt'][p] += 1
            if oc == 'GOAL':    mayo_pd['goal'][p] += 1
            elif oc == '1 POINT': mayo_pd['pt1'][p] += 1  # over the bar

    for s in parsed['opp_shots']:
        p  = period_of(s['ts'])
        oc = s['oc_raw']
        opp_pd['total'][p]  += 1
        if oc in ('1 POINT','2 POINT','GOAL'): opp_pd['scored'][p] += 1

    return mayo_pd, opp_pd

# ── Period attack data ────────────────────────────────────────────────────────
def build_period_attack_data(parsed):
    period_of   = parsed['period_of']
    mayo_scores = parsed['mayo_scores']
    mayo_shots  = parsed['mayo_shots']
    result = [[0,0,0,0] for _ in range(N_PERIODS)]

    for a in parsed['mayo_attacks']:
        s, e = a['ts'], a['end']
        p = min(period_of(s), N_PERIODS-1)
        result[p][0] += 1
        has_score = any(s <= sc['ts'] <= e for sc in mayo_scores)
        has_shot  = any(s <= sh['ts'] <= e for sh in mayo_shots)
        if has_score:   result[p][1] += 1
        elif has_shot:  result[p][2] += 1
        else:           result[p][3] += 1

    return result

# ── Period tempo data ─────────────────────────────────────────────────────────
def build_period_tempo_data(parsed):
    period_of   = parsed['period_of']
    mayo_scores = parsed['mayo_scores']
    result = [[0]*10 for _ in range(N_PERIODS)]

    for a in parsed['mayo_attacks']:
        s, e, d = a['ts'], a['end'], a['dur']
        p = min(period_of(s), N_PERIODS-1)
        result[p][0] += 1
        if d <= 25:   cat=0; result[p][1]+=1
        elif d <= 50: cat=1; result[p][2]+=1
        else:         cat=2; result[p][3]+=1

        ag = ap = 0
        for sc in mayo_scores:
            if s <= sc['ts'] <= e:
                if sc['type']=='goal': ag+=1; ap+=3
                elif sc['type']=='2pt': ap+=2
                else: ap+=1
        base = 4 + cat*2
        result[p][base]   += ag
        result[p][base+1] += ap

    return result

# ── Round tempo ───────────────────────────────────────────────────────────────
def build_round_tempo(parsed, round_label, opponent):
    def tempo(attacks):
        fast=ctrl=patient=total_d=0
        for a in attacks:
            d = a['dur']
            if d <= 25:   fast += 1
            elif d <= 50: ctrl += 1
            else:         patient += 1
            total_d += d
        n = len(attacks)
        return {'fast':fast,'ctrl':ctrl,'patient':patient,'avg':round(total_d/n,1) if n else 0}
    return {'round':round_label,'oppName':opponent,
            'mayo':tempo(parsed['mayo_attacks']),'opp':tempo(parsed['opp_attacks'])}

# ── Possession data ───────────────────────────────────────────────────────────
def build_possession_data(parsed):
    period_of = parsed['period_of']
    mayo_p = [0]*N_PERIODS
    opp_p  = [0]*N_PERIODS
    for poss in parsed['mayo_poss']:
        p = min(period_of(poss['ts']), N_PERIODS-1)
        mayo_p[p] += round(poss['dur'])
    for poss in parsed['opp_poss']:
        p = min(period_of(poss['ts']), N_PERIODS-1)
        opp_p[p] += round(poss['dur'])
    return [[mayo_p[i], opp_p[i]] for i in range(N_PERIODS)]

# ── Momentum events ───────────────────────────────────────────────────────────
def build_momentum_events(parsed):
    opp_upper = parsed['opp_team_upper']
    events = []
    for t in parsed['mayo_tos']:   events.append({'time':t['ts'],'code':'MAYO TOs'})
    for t in parsed['opp_tos']:    events.append({'time':t['ts'],'code':f'{opp_upper} TOs'})
    for t in parsed['mayo_wides']: events.append({'time':t['ts'],'code':'MAYO WIDE'})
    for t in parsed['opp_wides']:  events.append({'time':t['ts'],'code':f'{opp_upper} WIDE'})
    events.sort(key=lambda e: e['time'])
    return {'halfTimeStart':parsed['H1_END'],'halfTimeEnd':parsed['H2_START'],'events':events}

# ── Score timeline ────────────────────────────────────────────────────────────
def build_score_timeline(parsed, opponent):
    all_s = []
    for s in parsed['mayo_scores']:
        all_s.append({'time':s['ts'],'team':'MAYO','type':s['type'],
                      'player':s['player'],'half':s['half'],'minute':s['minute']})
    for s in parsed['opp_scores']:
        all_s.append({'time':s['ts'],'team':opponent.upper(),'type':s['type'],
                      'player':s['player'],'half':s['half'],'minute':s['minute']})
    all_s.sort(key=lambda x: x['time'])
    return all_s

# ── HTML update helpers ───────────────────────────────────────────────────────
def insert_before_struct_close(html, const_name, new_text, close='}'):
    """Insert new_text before the first ]; or }; (at column 0) after const_name declaration."""
    marker = f'const {const_name}'
    start  = html.find(marker)
    if start == -1:
        marker = f'const {const_name} '
        start  = html.find(marker)
    if start == -1:
        return html, False
    close_seq = '\n' + close + ';'
    pos = html.find(close_seq, start)
    if pos == -1:
        return html, False
    # Insert at pos+1 (after the \n, before the close char)
    return html[:pos+1] + new_text + html[pos+1:], True

def js_list(values):
    return '[' + ','.join(str(v) for v in values) + ']'

def js_dict_inline(d):
    parts = []
    for k, v in d.items():
        parts.append(f'{k}:{js_list(v)}')
    return '{' + ','.join(parts) + '}'

# ── Update RAW.matches ────────────────────────────────────────────────────────
def update_raw_matches(html, new_match):
    lines = html.split('\n')
    for i, line in enumerate(lines):
        if line.startswith('const RAW='):
            json_str = line[len('const RAW='):]
            if json_str.endswith(';'):
                json_str = json_str[:-1]
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError as e:
                print(f'  ⚠️  Could not parse RAW JSON: {e}')
                return html
            data['matches'].append(new_match)
            lines[i] = 'const RAW=' + json.dumps(data, ensure_ascii=False, separators=(',',':')) + ';'
            break
    return '\n'.join(lines)

# ── Update PLAYER_SCORE_ASSIST_DETAIL ────────────────────────────────────────
def update_player_score_detail(html, mayo_scores):
    delta = {}
    for s in mayo_scores:
        p = s['player']
        if p in ('Unknown','?'): continue
        if p not in delta: delta[p] = {'goals':0,'pt2':0,'pt1':0}
        if s['type']=='goal':   delta[p]['goals'] += 1
        elif s['type']=='2pt':  delta[p]['pt2']   += 1
        else:                   delta[p]['pt1']    += 1
    if not delta: return html

    start = html.find('const PLAYER_SCORE_ASSIST_DETAIL=')
    end   = html.find('};', start) + 2
    block = html[start:end]

    for player, d in delta.items():
        esc = re.escape(player)
        pat = re.compile(r'"' + esc + r'"\s*:\s*\{goals:(\d+),pt2:(\d+),pt1:(\d+),total:(\d+)\}')
        def updater(m, _d=d):
            g  = int(m.group(1)) + _d['goals']
            p2 = int(m.group(2)) + _d['pt2']
            p1 = int(m.group(3)) + _d['pt1']
            return f'"{player}"' + '{' + f'goals:{g},pt2:{p2},pt1:{p1},total:{g+p2+p1}' + '}'
        new_block, n = pat.subn(updater, block)
        if n == 0:
            close = new_block.rfind('};')
            entry = f'  "{player}"' + '{' + f'goals:{d["goals"]},pt2:{d["pt2"]},pt1:{d["pt1"]},total:{d["goals"]+d["pt2"]+d["pt1"]}' + '},\n'
            new_block = new_block[:close] + entry + new_block[close:]
        block = new_block

    return html[:start] + block + html[end:]

# ── Update PLAYER_ATTACK_META ─────────────────────────────────────────────────
def update_player_attack_meta(html, round_label, mayo_attacks):
    counts = {}
    for a in mayo_attacks:
        for p in a['players']:
            counts[p] = counts.get(p,0) + 1

    start = html.find('const PLAYER_ATTACK_META=')
    end   = html.find('\n};', start) + 3
    block = html[start:end]

    # Find all existing player entries (single-line dict format)
    pat = re.compile(r'"([^"]+)"\s*:\s*(\{[^}]+\})')
    known = set()
    def add_round(m, _rl=round_label, _c=counts):
        player  = m.group(1)
        content = m.group(2)  # e.g. {"Rd.1":4, ...}
        known.add(player)
        cnt = _c.get(player, 0)
        # Insert before closing }
        inner = content[1:-1].rstrip()
        return f'"{player}":  {{{inner}, "{_rl}":{cnt}}}'
    block = pat.sub(add_round, block)

    # Add new players not yet in meta
    for player, cnt in counts.items():
        if player not in known:
            close_pos = block.rfind('\n};')
            entry = f'  "{player}":  {{"{round_label}":{cnt}}},\n'
            block = block[:close_pos+1] + entry + block[close_pos+1:]

    return html[:start] + block + html[end:]

# ── Update SHOT_META ──────────────────────────────────────────────────────────
def update_shot_meta(html, round_label, mayo_shots):
    # Build per-player shot stats for this round
    stats = {}
    for s in mayo_shots:
        p = s['player']
        if p == 'Unknown': continue
        if p not in stats:
            stats[p] = {'play':0,'playMade':0,'deadball':0,'deadballMade':0,
                        'goals':0,'goalAtt':0,'pt2':0,'pt2Att':0,'pt1':0,'pt1Att':0}
        d  = stats[p]
        at = s['at_raw']
        oc = s['oc_raw']
        scored = oc in ('1 POINT','2 POINT','GOAL')
        if s['stype'] == 'play':
            d['play'] += 1
            if scored: d['playMade'] += 1
        else:
            d['deadball'] += 1
            if scored: d['deadballMade'] += 1
        if at == 'Goal Attempt':
            d['goalAtt'] += 1
            if oc == 'GOAL':    d['goals'] += 1
            elif oc == '1 POINT': d['pt1'] += 1
        elif at == '2 Point Attempt':
            d['pt2Att'] += 1
            if oc == '2 POINT': d['pt2'] += 1
        else:
            d['pt1Att'] += 1
            if oc == '1 POINT': d['pt1'] += 1

    if not stats: return html

    start = html.find('const SHOT_META=')
    end   = html.find('\n};', start) + 3
    block = html[start:end]

    for player, d in stats.items():
        esc = re.escape(player)
        round_entry = (f'"{round_label}":'
                       '{' + f'play:{d["play"]},playMade:{d["playMade"]},'
                       f'deadball:{d["deadball"]},deadballMade:{d["deadballMade"]},'
                       f'goals:{d["goals"]},goalAtt:{d["goalAtt"]},'
                       f'pt2:{d["pt2"]},pt2Att:{d["pt2Att"]},'
                       f'pt1:{d["pt1"]},pt1Att:{d["pt1Att"]}' + '}')

        # Try to find existing player entry (may have nested {})
        # Use depth-counting to find the outer object
        search_pat = re.compile(r'"' + esc + r'"\s*:\s*\{')
        m = search_pat.search(block)
        if m:
            brace_start = m.end() - 1
            depth = 0
            i = brace_start
            while i < len(block):
                if block[i] == '{': depth += 1
                elif block[i] == '}':
                    depth -= 1
                    if depth == 0:
                        # Insert `,round_entry` before the closing }
                        inner = block[brace_start+1:i]
                        replacement = m.group(0) + inner + ',' + round_entry + '}'
                        block = block[:m.start()] + replacement + block[i+1:]
                        break
                i += 1
        else:
            # New player — add to end
            close_pos = block.rfind('\n};')
            entry = f'  "{player}":{{{round_entry}}},\n'
            block = block[:close_pos+1] + entry + block[close_pos+1:]

    return html[:start] + block + html[end:]

# ── Update GK_KO_DATA ─────────────────────────────────────────────────────────
def update_gk_ko_data(html, gk_key, round_label, mayo_kos, all_league_rounds, all_champ_rounds):
    """Update GK_KO_DATA totals for gk_key and rebuild rounds string."""
    if not mayo_kos: return html

    start = html.find('const GK_KO_DATA=')
    end   = html.find('\n};', start) + 3
    block = html[start:end]

    # Find gk's sub-block
    gk_start = block.find(f'{gk_key}:{{')
    if gk_start == -1: return html

    # Count new KOs
    short = sum(1 for k in mayo_kos if k['loc']=='short')
    med   = sum(1 for k in mayo_kos if k['loc']=='medium')
    long_ = sum(1 for k in mayo_kos if k['loc']=='long')
    total = len(mayo_kos)
    w_s   = sum(k['won'] for k in mayo_kos if k['loc']=='short')
    w_m   = sum(k['won'] for k in mayo_kos if k['loc']=='medium')
    w_l   = sum(k['won'] for k in mayo_kos if k['loc']=='long')
    w_tot = w_s + w_m + w_l

    def update_field(blk, field, delta, as_int=True):
        p = re.compile(field + r':(\d+(?:\.\d+)?)')
        def repl(m):
            old = float(m.group(1))
            new = old + delta
            return field + ':' + (str(int(new)) if as_int else str(round(new,1)))
        return p.sub(repl, blk, count=1)

    # Rebuild rounds string from all rounds this GK played
    gk_rounds = _get_gk_rounds_from_html(html, gk_key)
    gk_rounds.append(round_label)

    league_rounds = [r for r in gk_rounds if comp_category(r)=='league']
    champ_rounds  = [r for r in gk_rounds if comp_category(r)=='championship']

    rounds_str = _format_rounds_string(league_rounds, champ_rounds)

    # Update totals in the block
    # Extract gk sub-object using depth counting
    brace_idx = block.find('{', gk_start)
    depth = 0
    i = brace_idx
    while i < len(block):
        if block[i]=='{': depth += 1
        elif block[i]=='}':
            depth -= 1
            if depth == 0:
                gk_end = i+1
                break
        i += 1

    gk_block = block[gk_start:gk_end]

    # Update total fields
    # Update totals
    def update_group(blk, grp_name, add_won, add_total):
        pat = re.compile(re.escape(grp_name) + r':\{won:(\d+),total:(\d+),pct:[0-9.]+\}')
        def repl(m):
            w = int(m.group(1)) + add_won
            t = int(m.group(2)) + add_total
            pct = round(w/t*100,1) if t else 0
            return f'{grp_name}:' + '{' + f'won:{w},total:{t},pct:{pct}' + '}'
        return pat.sub(repl, blk)

    gk_block = update_group(gk_block, 'total', w_tot, total)
    gk_block = update_group(gk_block, 'short', w_s,   short)
    gk_block = update_group(gk_block, 'medium',w_m,   med)
    gk_block = update_group(gk_block, 'long',  w_l,   long_)

    # Update rounds string
    gk_block = re.sub(r"rounds:'[^']*'", f"rounds:'{rounds_str}'", gk_block)

    block = block[:gk_start] + gk_block + block[gk_end:]
    return html[:start] + block + html[end:]

def _get_gk_rounds_from_html(html, gk_key):
    """Extract list of rounds already attributed to this GK from GK_KO_DATA."""
    start = html.find(f'{gk_key}:{{')
    end   = html.find('\n  },', start)
    if end == -1: end = html.find('\n};', start)
    chunk = html[start:end]
    m = re.search(r"rounds:'([^']*)'", chunk)
    if not m: return []
    rs = m.group(1)
    # Parse e.g. "Rd.1–6 + CSFC QF" → ['Rd.1','Rd.2',...,'Rd.6','CSFC QF']
    result = []
    for part in rs.split(' + '):
        part = part.strip()
        rng  = re.match(r'Rd\.(\d+)–(\d+)', part)
        if rng:
            for n in range(int(rng.group(1)), int(rng.group(2))+1):
                result.append(f'Rd.{n}')
        elif part:
            result.append(part)
    return result

def _format_rounds_string(league_rounds, champ_rounds):
    """Build 'Rd.1–7 + CSFC QF + CSFC SF' style string."""
    parts = []
    if league_rounds:
        nums = sorted(int(r[3:]) for r in league_rounds if re.match(r'Rd\.\d+$', r))
        if nums:
            if len(nums) == 1:
                parts.append(f'Rd.{nums[0]}')
            else:
                parts.append(f'Rd.{nums[0]}–{nums[-1]}')
    for r in champ_rounds:
        parts.append(r)
    return ' + '.join(parts)

# ── Update COMPETITION_ROUNDS ─────────────────────────────────────────────────
def update_competition_rounds(html, round_label, category):
    start = html.find('const COMPETITION_ROUNDS=')
    end   = html.find('};', start) + 2
    block = html[start:end]

    def append_to_array(blk, key, val):
        pat = re.compile(r"(" + re.escape(key) + r"\s*:\s*\[)(.*?)(\])", re.DOTALL)
        def repl(m):
            return m.group(1) + m.group(2) + f",'{val}'" + m.group(3)
        return pat.sub(repl, blk)

    block = append_to_array(block, 'all', round_label)
    block = append_to_array(block, category, round_label)
    return html[:start] + block + html[end:]

# ── Update ROUNDS_HOME_AWAY ───────────────────────────────────────────────────
def update_rounds_home_away(html, round_label, venue):
    start = html.find('const ROUNDS_HOME_AWAY =')
    if start == -1: start = html.find('const ROUNDS_HOME_AWAY=')
    end   = html.find('};', start) + 2
    block = html[start:end]
    close = block.rfind('\n};')
    block = block[:close] + f",'{round_label}':'{venue}'" + block[close:]
    return html[:start] + block + html[end:]

# ── Format JS for appending ───────────────────────────────────────────────────
def fmt_shot_map_entries(shots, round_label):
    lines = []
    for s in shots:
        player = s['player'].replace("'", "\\'")
        lines.append(f"  [{s['x']},{s['y']},'{s['stype']}','{s['outcome']}','{round_label}','{player}','{s['att']}'],")
    return '\n'.join(lines) + '\n' if lines else ''

def fmt_opp_shot_map_entries(shots, round_label):
    lines = []
    for s in shots:
        lines.append(f"  [{s['x']},{s['y']},'{s['stype']}','{s['outcome']}','{round_label}','{s['att']}'],")
    return '\n'.join(lines) + '\n' if lines else ''

def fmt_ko_pitch_entries(kos, round_label, venue):
    v = 'H' if venue == 'Home' else 'A'
    lines = []
    for k in kos:
        lines.append(f"  [{k['x']},{k['y']},{k['won']},\"{round_label}\",\"{v}\",\"{k['loc']}\"],")
    return '\n'.join(lines) + '\n' if lines else ''

def fmt_opp_ko_entries(kos, round_label):
    lines = []
    for k in kos:
        lines.append(f"  [{k['x']},{k['y']},{k['opp_won']},'{round_label}',null],")
    return '\n'.join(lines) + '\n' if lines else ''

def fmt_period_dict_entry(round_label, data):
    """Format [[a,b,c,d],[...]] as one-liner."""
    inner = ','.join('[' + ','.join(str(x) for x in row) + ']' for row in data)
    return f'  "{round_label}":[{inner}],\n'

def fmt_opp_ko_period(round_label, opp_kos, period_of):
    rows = [[0,0,0] for _ in range(N_PERIODS)]
    for k in opp_kos:
        p = min(period_of(k['ts']), N_PERIODS-1)
        rows[p][0] += 1
        if k['opp_won']: rows[p][1] += 1
        else:            rows[p][2] += 1
    return fmt_period_dict_entry(round_label, rows)

def fmt_turnover_period(round_label, parsed):
    period_of = parsed['period_of']
    mayo_t = [0]*N_PERIODS
    opp_t  = [0]*N_PERIODS
    for t in parsed['mayo_tos']:
        p = min(period_of(t['ts']), N_PERIODS-1)
        mayo_t[p] += 1
    for t in parsed['opp_tos']:
        p = min(period_of(t['ts']), N_PERIODS-1)
        opp_t[p] += 1
    return f'  "{round_label}":{{"mayo":{js_list(mayo_t)},"opp":{js_list(opp_t)}}},\n'

def fmt_foul_period(round_label, parsed):
    period_of = parsed['period_of']
    mayo_f = [0]*N_PERIODS
    opp_f  = [0]*N_PERIODS
    for f in parsed['mayo_fouls']:
        p = min(period_of(f['ts']), N_PERIODS-1)
        mayo_f[p] += 1
    for f in parsed['opp_fouls']:
        p = min(period_of(f['ts']), N_PERIODS-1)
        opp_f[p] += 1
    return f'  "{round_label}":{{"mayo":{js_list(mayo_f)},"opp":{js_list(opp_f)}}},\n'

def fmt_tackle_period(round_label, parsed):
    period_of = parsed['period_of']
    rows = [0]*N_PERIODS
    for t in parsed['mayo_tackles']:
        p = min(period_of(t['ts']), N_PERIODS-1)
        rows[p] += 1
    return f'  "{round_label}":{js_list(rows)},\n'

def fmt_tackle_counts(round_label, parsed):
    period_of = parsed['period_of']
    counts = {}
    for t in parsed['mayo_tackles']:
        p = t['player']
        if p == 'Unknown': continue
        counts[p] = counts.get(p,0) + 1
    if not counts: return f'  "{round_label}":{{}},\n'
    sorted_c = sorted(counts.items(), key=lambda x: -x[1])
    inner = ','.join(f'"{p}":{c}' for p,c in sorted_c)
    return f'  "{round_label}":{{{inner}}},\n'

def fmt_round_tempo(rt):
    m = rt['mayo']
    o = rt['opp']
    return (f"  {{round:'{rt['round']}',oppName:'{rt['oppName']}',"
            f"mayo:{{fast:{m['fast']},ctrl:{m['ctrl']},patient:{m['patient']},avg:{m['avg']}}},"
            f"opp:{{fast:{o['fast']},ctrl:{o['ctrl']},patient:{o['patient']},avg:{o['avg']}}}}},\n")

def fmt_possession(round_label, data):
    inner = ','.join(f'[{r[0]},{r[1]}]' for r in data)
    return f'  "{round_label}":[{inner}],\n'

def fmt_shot_period_entry(round_label, mayo_pd, opp_pd):
    def lst(arr): return '[' + ','.join(str(x) for x in arr) + ']'
    m = mayo_pd
    o = opp_pd
    return (f'  "{round_label}":{{mayo:'
            '{' + f'total:{lst(m["total"])},scored:{lst(m["scored"])},'
            f'pt1Att:{lst(m["pt1Att"])},pt1:{lst(m["pt1"])},'
            f'pt2Att:{lst(m["pt2Att"])},pt2:{lst(m["pt2"])},'
            f'goalAtt:{lst(m["goalAtt"])},goal:{lst(m["goal"])}' + '},'
            f'opp:{{total:{lst(o["total"])},scored:{lst(o["scored"])}}}' + '},\n')

def fmt_momentum_entry(round_label, me):
    evts = json.dumps(me['events'], ensure_ascii=False, separators=(',',':'))
    return (f'  "{round_label}": {{\n'
            f'    halfTimeStart: {me["halfTimeStart"]},\n'
            f'    halfTimeEnd: {me["halfTimeEnd"]},\n'
            f'    events: {evts}\n'
            f'  }},\n')

# ── Fix existing GK_KO_DATA Rd.1–6 bug ───────────────────────────────────────
def fix_gk_ko_rounds_bug(html):
    """Fix 'Rd.1–6 + CSFC QF' → correct string for Hennelly."""
    # Rebuild from scratch for hennelly using _get_gk_rounds_from_html
    # The bug: rounds string doesn't include all league/champ rounds played
    # We fix by rebuilding from COMPETITION_ROUNDS data
    gk_rounds = _get_gk_rounds_from_html(html, 'hennelly')
    league = [r for r in gk_rounds if comp_category(r)=='league']
    champ  = [r for r in gk_rounds if comp_category(r)=='championship']
    correct = _format_rounds_string(league, champ)

    start = html.find('const GK_KO_DATA=')
    end   = html.find('\n};', start) + 3
    block = html[start:end]
    # Fix rounds string for hennelly
    hen_start = block.find('hennelly:{')
    hen_end   = block.find('\n  },', hen_start)
    if hen_end == -1: hen_end = block.find('\n};', hen_start)
    hen_block = block[hen_start:hen_end]
    hen_block = re.sub(r"rounds:'[^']*'", f"rounds:'{correct}'", hen_block)
    block = block[:hen_start] + hen_block + block[hen_end:]
    return html[:start] + block + html[end:]

# ── Season-aggregate helpers ──────────────────────────────────────────────────

def replace_const(html, name, new_block):
    """Replace a complete const block (from 'const NAME=' to the first \\n}; at column 0)."""
    start = html.find(f'const {name}=')
    if start == -1:
        start = html.find(f'const {name} =')
    if start == -1:
        return html
    close_pos = html.find('\n};', start)
    if close_pos == -1:
        return html
    end = close_pos + 3  # include \n};
    return html[:start] + new_block + html[end:]


def _extract_round_from_filename(fname):
    b = os.path.basename(fname)
    m = re.search(r'\bRd\.(\d+)\b', b)
    if m:
        if 'AISFC' in b.upper():
            return f'AISFC Rd.{m.group(1)}'
        return f'Rd.{m.group(1)}'
    m = re.search(r'(CSFC|AISFC)\s+(QF|SF|Final)', b, re.IGNORECASE)
    if m:
        return f'{m.group(1).upper()} {m.group(2)}'
    return None


def _parse_season_data_from_xml(xml_path):
    """Lightweight parser returning data needed for season-aggregate structures."""
    try:
        with open(xml_path, 'rb') as f:
            raw = f.read()
        text = raw.decode('utf-16') if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else raw.decode('utf-8', errors='replace')
        tree = ET.fromstring(text)
    except Exception:
        return None

    instances = tree.findall('ALL_INSTANCES/instance')

    # Detect half timestamps for period calculation
    H1_START = H1_END = H2_START = None
    for inst in instances:
        code = inst.findtext('code', '').strip()
        if code == '1st Half':
            H1_START = float(inst.findtext('start', 0))
            H1_END   = float(inst.findtext('end',   0))
        elif code == '2nd Half':
            H2_START = float(inst.findtext('start', 0))
    if None in (H1_START, H1_END, H2_START):
        return None

    def game_min(ts):
        if ts <= H1_END:
            return (ts - H1_START) / 60.0
        return (H1_END - H1_START) / 60.0 + (ts - H2_START) / 60.0

    def first_lbl(inst, group, default=''):
        for lbl in inst.findall('label'):
            if lbl.findtext('group', '').strip() == group:
                return lbl.findtext('text', '').strip()
        return default

    opp_name = None
    mayo_score_srcs = []   # [{ts, cat, score_type}]
    opp_score_srcs  = []
    mayo_shot_srcs  = []   # [{ts, cat}]  — missed shots
    opp_shot_srcs   = []
    mayo_tos_loc    = []   # [{ts, loc}]
    opp_tos_loc     = []
    mayo_ko_full    = []   # [{ts, loc, outcome_raw}]
    opp_ko_full     = []
    # period_scores: scoring value (goals*3+2pt*2+1pt) per 6-period slot
    period_scores   = {'mayo': [0]*N_PERIODS, 'opp': [0]*N_PERIODS}

    for inst in instances:
        code = inst.findtext('code', '').strip()
        ts   = float(inst.findtext('start', 0))

        # ── SCORE SOURCE (scored shots) ───────────────────────────────────
        if code == 'MAYO SCORE SOURCE':
            raw_src    = first_lbl(inst, 'Score Source Outcomes')
            score_type = first_lbl(inst, 'Score Source Score Outcomes', '1 POINT')
            cat = SOURCE_CAT_MAP.get(raw_src)
            if cat:
                mayo_score_srcs.append({'ts': ts, 'cat': cat, 'score_type': score_type})

        elif code.endswith(' SCORE SOURCE') and 'MAYO' not in code:
            if opp_name is None:
                opp_name = code[:-13].strip()
            raw_src    = first_lbl(inst, 'Score Source Outcomes')
            score_type = first_lbl(inst, 'Score Source Score Outcomes', '1 POINT')
            cat = SOURCE_CAT_MAP.get(raw_src)
            if cat:
                opp_score_srcs.append({'ts': ts, 'cat': cat, 'score_type': score_type})

        # ── SHOT SOURCE (missed shots) ────────────────────────────────────
        elif code == 'MAYO SHOT SOURCE':
            raw_src = first_lbl(inst, 'Shot Source Outcomes')
            cat = SOURCE_CAT_MAP.get(raw_src)
            if cat:
                mayo_shot_srcs.append({'ts': ts, 'cat': cat})

        elif code.endswith(' SHOT SOURCE') and 'MAYO' not in code:
            raw_src = first_lbl(inst, 'Shot Source Outcomes')
            cat = SOURCE_CAT_MAP.get(raw_src)
            if cat:
                opp_shot_srcs.append({'ts': ts, 'cat': cat})

        # ── Turnovers with location ───────────────────────────────────────
        elif code == 'MAYO TOs':
            loc = first_lbl(inst, 'Turnover Location', 'MIDDLE THIRD')
            mayo_tos_loc.append({'ts': ts, 'loc': loc})

        elif code.endswith(' TOs') and 'MAYO' not in code:
            if opp_name is None:
                opp_name = code[:-4].strip()
            loc = first_lbl(inst, 'Turnover Location', 'MIDDLE THIRD')
            opp_tos_loc.append({'ts': ts, 'loc': loc})

        # ── KO with raw outcome ───────────────────────────────────────────
        elif code == 'MAYO KO':
            raw_loc     = first_lbl(inst, 'Kickout Locations', 'KO LONG')
            outcome_raw = first_lbl(inst, 'Kickout Outcomes', 'KO LOST CLEAN')
            loc = KO_LOC_MAP.get(raw_loc, 'long')
            mayo_ko_full.append({'ts': ts, 'loc': loc, 'outcome_raw': outcome_raw})

        elif code.endswith(' KO') and 'MAYO' not in code:
            if opp_name is None:
                opp_name = code[:-3].strip()
            raw_loc     = first_lbl(inst, 'Kickout Locations', 'KO LONG')
            outcome_raw = first_lbl(inst, 'Kickout Outcomes', 'KO LOST CLEAN')
            loc = KO_LOC_MAP.get(raw_loc, 'long')
            opp_ko_full.append({'ts': ts, 'loc': loc, 'outcome_raw': outcome_raw})

        # ── Scoring events (for PERIOD_SPLITS) ───────────────────────────
        elif code in ('MAYO 1 POINT', 'MAYO 2 POINT', 'MAYO GOAL'):
            p = get_period(game_min(ts))
            if code == 'MAYO GOAL':       period_scores['mayo'][p] += 3
            elif code == 'MAYO 2 POINT':  period_scores['mayo'][p] += 2
            else:                         period_scores['mayo'][p] += 1

        elif (code.endswith(' 1 POINT') or code.endswith(' 2 POINT') or
              (code.endswith(' GOAL') and 'CHANCE' not in code)) and 'MAYO' not in code:
            p = get_period(game_min(ts))
            if code.endswith(' GOAL'):    period_scores['opp'][p] += 3
            elif code.endswith(' 2 POINT'): period_scores['opp'][p] += 2
            else:                         period_scores['opp'][p] += 1

        # Detect opp name from other codes if still missing
        elif opp_name is None:
            if code.endswith(' ATTACKS') and 'MAYO' not in code:
                opp_name = code[:-8].strip()
            elif code.endswith(' FOUL') and 'MAYO' not in code:
                opp_name = code[:-5].strip()

    return {
        'opp_name':        opp_name or 'Opponent',
        'mayo_score_srcs': mayo_score_srcs,
        'opp_score_srcs':  opp_score_srcs,
        'mayo_shot_srcs':  mayo_shot_srcs,
        'opp_shot_srcs':   opp_shot_srcs,
        'mayo_tos_loc':    mayo_tos_loc,
        'opp_tos_loc':     opp_tos_loc,
        'mayo_ko_full':    mayo_ko_full,
        'opp_ko_full':     opp_ko_full,
        'period_scores':   period_scores,
    }


def _compute_at_impact(score_srcs, tos_loc):
    """Chain: for each TO-source score, find nearest preceding TO in attacking third."""
    result = {'total': 0, 'goals': 0, 'twopt': 0, 'onept': 0}
    for sc in score_srcs:
        if sc['cat'] != 'to':
            continue
        preceding = [t for t in tos_loc if t['ts'] <= sc['ts']]
        if not preceding:
            continue
        nearest = max(preceding, key=lambda t: t['ts'])
        if nearest['loc'] == 'ATTACKING THIRD':
            result['total'] += 1
            if sc['score_type'] == 'GOAL':
                result['goals'] += 1
            elif sc['score_type'] == '2 POINT':
                result['twopt'] += 1
            else:
                result['onept'] += 1
    return result


def _format_ko_outcomes_block(mayo_kos, opp_kos):
    """Build const KO_OUTCOMES={...}; JS block with _raw counts for future delta updates."""
    from collections import Counter

    def stats(kos, loc):
        entries = [k for k in kos if k['loc'] == loc]
        counts  = Counter(k['outcome_raw'] for k in entries)
        total   = len(entries)
        won     = sum(v for k, v in counts.items() if k in WON_KO_OUTCOMES)
        pct     = int(won / total * 100 + 0.5) if total else 0
        top     = [(KO_OUTCOME_DISPLAY.get(k, k), v) for k, v in counts.most_common()]
        return {'win': f'{pct}% ({won}/{total})', 'top': top, 'raw': dict(counts)}

    lines = ['const KO_OUTCOMES={']
    for loc in ('short', 'medium', 'long'):
        ms  = stats(mayo_kos, loc)
        opp = stats(opp_kos,  loc)
        m_raw = json.dumps(ms['raw'],  ensure_ascii=False, separators=(',', ':'))
        o_raw = json.dumps(opp['raw'], ensure_ascii=False, separators=(',', ':'))
        if loc == 'short':
            m1 = f"'{ms['top'][0][0]} ({ms['top'][0][1]})'"  if ms['top']  else "''"
            o1 = f"'{opp['top'][0][0]} ({opp['top'][0][1]})'" if opp['top'] else "''"
            lines.append(
                f"  {loc}:{{mayoWin:'{ms['win']}',mayoTop:{m1},"
                f"oppWin:'{opp['win']}',oppTop:{o1},"
                f"_raw:{{mayo:{m_raw},opp:{o_raw}}}}},"
            )
        else:
            m_tops = ','.join(
                f"mayoTop{i+1}:'{n} ({c})'" for i, (n, c) in enumerate(ms['top'][:3])
            )
            o_tops = ','.join(
                f"oppTop{i+1}:'{n} ({c})'" for i, (n, c) in enumerate(opp['top'][:2])
            )
            lines.append(
                f"  {loc}:{{mayoWin:'{ms['win']}',{m_tops},"
                f"oppWin:'{opp['win']}',{o_tops},"
                f"_raw:{{mayo:{m_raw},opp:{o_raw}}}}},"
            )
    lines.append('};')
    return '\n'.join(lines)


def rebuild_season_structures(html):
    """Recompute SCORE_SOURCES, TURNOVER_ZONES, KO_OUTCOMES, PERIOD_SPLITS from all XMLs."""
    xmls = sorted(glob.glob(os.path.join(XML_DIR, '*.xml')))
    all_data = []
    for xml_path in xmls:
        gd = _parse_season_data_from_xml(xml_path)
        if gd is None:
            continue
        round_label = _extract_round_from_filename(xml_path) or gd['opp_name'].title()
        all_data.append((round_label, gd))

    if not all_data:
        return html

    # ── Accumulate season totals ──────────────────────────────────────────────
    # Source stats: per-category counts of shots and scores
    src_stats = {
        team: {src: {'goals': 0, 'twopt': 0, 'onept': 0, 'shots': 0}
               for src in SOURCES}
        for team in ('mayo', 'opp')
    }
    # Turnover zones
    tz = {
        'mayo': {'ATTACKING THIRD': 0, 'MIDDLE THIRD': 0, 'DEFENSIVE THIRD': 0},
        'opp':  {'ATTACKING THIRD': 0, 'MIDDLE THIRD': 0, 'DEFENSIVE THIRD': 0},
    }
    # KO full data
    all_mayo_kos = []
    all_opp_kos  = []
    # Period splits
    ps = {'mayo': [0]*N_PERIODS, 'opp': [0]*N_PERIODS}
    # atImpact accumulator
    at_impact = {'total': 0, 'goals': 0, 'twopt': 0, 'onept': 0}
    at_from   = 0  # total ATTACKING THIRD TOs (for 'from' field)

    for _, gd in all_data:
        # Score sources
        for sc in gd['mayo_score_srcs']:
            s = src_stats['mayo'][sc['cat']]
            if sc['score_type'] == 'GOAL':    s['goals'] += 1
            elif sc['score_type'] == '2 POINT': s['twopt'] += 1
            else:                              s['onept'] += 1
        for sc in gd['opp_score_srcs']:
            s = src_stats['opp'][sc['cat']]
            if sc['score_type'] == 'GOAL':    s['goals'] += 1
            elif sc['score_type'] == '2 POINT': s['twopt'] += 1
            else:                              s['onept'] += 1
        # Shot sources (missed)
        for sh in gd['mayo_shot_srcs']:
            src_stats['mayo'][sh['cat']]['shots'] += 1
        for sh in gd['opp_shot_srcs']:
            src_stats['opp'][sh['cat']]['shots'] += 1

        # Turnover zones
        for t in gd['mayo_tos_loc']:
            loc = t['loc']
            if loc in tz['mayo']:
                tz['mayo'][loc] += 1
        for t in gd['opp_tos_loc']:
            loc = t['loc']
            if loc in tz['opp']:
                tz['opp'][loc] += 1

        # KOs
        all_mayo_kos.extend(gd['mayo_ko_full'])
        all_opp_kos.extend(gd['opp_ko_full'])

        # Period splits
        for i in range(N_PERIODS):
            ps['mayo'][i] += gd['period_scores']['mayo'][i]
            ps['opp'][i]  += gd['period_scores']['opp'][i]

        # atImpact chain
        ai = _compute_at_impact(gd['mayo_score_srcs'], gd['mayo_tos_loc'])
        at_impact['total']  += ai['total']
        at_impact['goals']  += ai['goals']
        at_impact['twopt']  += ai['twopt']
        at_impact['onept']  += ai['onept']
        at_from += tz['mayo']['ATTACKING THIRD']  # running total (recalculated below)

    # Recalculate at_from cleanly (total attacking-third TOs across all games)
    at_from = tz['mayo']['ATTACKING THIRD']

    # ── Build SCORE_SOURCES block ─────────────────────────────────────────────
    def src_pct(cat, team):
        s = src_stats[team]
        total_scores = sum(
            sv['goals'] + sv['twopt'] + sv['onept'] for sv in s.values()
        )
        scored = s[cat]['goals'] + s[cat]['twopt'] + s[cat]['onept']
        return int(scored / total_scores * 100 + 0.5) if total_scores else 0

    def src_eff(cat, team):
        s = src_stats[team][cat]
        scored = s['goals'] + s['twopt'] + s['onept']
        total  = scored + s['shots']
        return int(scored / total * 100 + 0.5) if total else 0

    def src_total_shots(cat, team):
        s = src_stats[team][cat]
        return s['goals'] + s['twopt'] + s['onept'] + s['shots']

    ss_lines = ['const SCORE_SOURCES={']
    ss_lines.append('  mayo:{')
    for cat in SOURCES:
        s     = src_stats['mayo'][cat]
        total = s['goals'] + s['twopt'] + s['onept']
        shots = src_total_shots(cat, 'mayo')
        eff   = src_eff(cat, 'mayo')
        pct   = src_pct(cat, 'mayo')
        ss_lines.append(
            f"    {cat}:{{goals:{s['goals']},twopt:{s['twopt']},onept:{s['onept']},"
            f"shots:{shots},eff:{eff},total:{total},pct:{pct}}},"
        )
    ss_lines.append('  },')
    ss_lines.append('  opp:{')
    for cat in SOURCES:
        s     = src_stats['opp'][cat]
        total = s['goals'] + s['twopt'] + s['onept']
        shots = src_total_shots(cat, 'opp')
        eff   = src_eff(cat, 'opp')
        pct   = src_pct(cat, 'opp')
        ss_lines.append(
            f"    {cat}:{{goals:{s['goals']},twopt:{s['twopt']},onept:{s['onept']},"
            f"shots:{shots},eff:{eff},total:{total},pct:{pct}}},"
        )
    ss_lines.append('  },')
    ss_lines.append('};')
    score_sources_block = '\n'.join(ss_lines)

    # ── Build TURNOVER_ZONES block ────────────────────────────────────────────
    m_total = sum(tz['mayo'].values())
    o_total = sum(tz['opp'].values())

    def tz_pct(zone, team):
        tot = sum(tz[team].values())
        return int(tz[team][zone] / tot * 100 + 0.5) if tot else 0

    ai_sv = at_impact['goals'] * 3 + at_impact['twopt'] * 2 + at_impact['onept']
    ai_pct = int(at_impact['total'] / at_from * 100 + 0.5) if at_from else 0

    tz_block = (
        'const TURNOVER_ZONES={\n'
        f"  mayo:{{total:{m_total},"
        f"attacking:{tz['mayo']['ATTACKING THIRD']},attackingPct:{tz_pct('ATTACKING THIRD','mayo')},"
        f"middle:{tz['mayo']['MIDDLE THIRD']},middlePct:{tz_pct('MIDDLE THIRD','mayo')},"
        f"defensive:{tz['mayo']['DEFENSIVE THIRD']},defensivePct:{tz_pct('DEFENSIVE THIRD','mayo')}}},"
        '\n'
        f"  opp:{{total:{o_total},"
        f"attacking:{tz['opp']['ATTACKING THIRD']},attackingPct:{tz_pct('ATTACKING THIRD','opp')},"
        f"middle:{tz['opp']['MIDDLE THIRD']},middlePct:{tz_pct('MIDDLE THIRD','opp')},"
        f"defensive:{tz['opp']['DEFENSIVE THIRD']},defensivePct:{tz_pct('DEFENSIVE THIRD','opp')}}},"
        '\n'
        f"  atImpact:{{total:{at_impact['total']},from:{at_from},pct:{ai_pct},"
        f"goals:{at_impact['goals']},twopt:{at_impact['twopt']},onept:{at_impact['onept']},"
        f"scoreValue:{ai_sv}}},\n"
        '};'
    )

    # ── Build KO_OUTCOMES block ───────────────────────────────────────────────
    ko_outcomes_block = _format_ko_outcomes_block(all_mayo_kos, all_opp_kos)

    # ── Build PERIOD_SPLITS block ─────────────────────────────────────────────
    m_ps = ps['mayo']
    o_ps = ps['opp']
    ps_block = (
        'const PERIOD_SPLITS={\n'
        f"  mayo:[{','.join(str(v) for v in m_ps)}],\n"
        f"  opp:[{','.join(str(v) for v in o_ps)}],\n"
        f"  mayoTotal:{sum(m_ps)},oppTotal:{sum(o_ps)},\n"
        '};'
    )

    # ── Replace all four blocks ───────────────────────────────────────────────
    html = replace_const(html, 'SCORE_SOURCES',   score_sources_block)
    html = replace_const(html, 'TURNOVER_ZONES',  tz_block)
    html = replace_const(html, 'KO_OUTCOMES',     ko_outcomes_block)
    html = replace_const(html, 'PERIOD_SPLITS',   ps_block)

    return html


# ── Main update function ──────────────────────────────────────────────────────
def update_html(html, round_label, opponent, venue, parsed, gk_key='hennelly'):
    period_of = parsed['period_of']

    # Compute scores
    mg, mp2, mp1, m_total = score_totals(parsed['mayo_scores'])
    og, op2, op1, o_total = score_totals(parsed['opp_scores'])
    scorers      = compute_scorers(parsed['mayo_scores'])
    mayo_score_s = score_string(mg, mp2, mp1)
    opp_score_s  = score_string(og, op2, op1)
    result       = 'W' if m_total > o_total else 'L' if m_total < o_total else 'D'

    # Shot accuracy
    ms_scored = sum(1 for s in parsed['mayo_shots'] if s['oc_raw'] in ('1 POINT','2 POINT','GOAL'))
    os_scored = sum(1 for s in parsed['opp_shots']  if s['oc_raw'] in ('1 POINT','2 POINT','GOAL'))
    ms_total  = len(parsed['mayo_shots'])
    os_total  = len(parsed['opp_shots'])
    ms_acc    = round(ms_scored / ms_total * 100, 1) if ms_total else 0
    os_acc    = round(os_scored / os_total * 100, 1) if os_total else 0

    # KO
    mko_won   = sum(k['won']     for k in parsed['mayo_kos'])
    mko_total = len(parsed['mayo_kos'])
    oko_won   = sum(k['opp_won'] for k in parsed['opp_kos'])
    oko_total = len(parsed['opp_kos'])
    mko_pct   = round(mko_won/mko_total*100,1) if mko_total else 0
    oko_pct   = round(oko_won/oko_total*100,1) if oko_total else 0

    # KO lengths
    mko_short  = sum(1 for k in parsed['mayo_kos'] if k['loc']=='short')
    mko_med    = sum(1 for k in parsed['mayo_kos'] if k['loc']=='medium')
    mko_long   = sum(1 for k in parsed['mayo_kos'] if k['loc']=='long')

    # Shot attempt types
    m_1ptAtt   = sum(1 for s in parsed['mayo_shots'] if s['at_raw']=='1 Point Attempt')
    m_2ptAtt   = sum(1 for s in parsed['mayo_shots'] if s['at_raw']=='2 Point Attempt')
    m_goalAtt  = sum(1 for s in parsed['mayo_shots'] if s['at_raw']=='Goal Attempt')
    o_goalAtt  = sum(1 for s in parsed['opp_shots']  if s['at_raw']=='Goal Attempt')

    # Turnovers
    m_tos = len(parsed['mayo_tos'])
    o_tos = len(parsed['opp_tos'])

    # Fouls
    m_fouls = len(parsed['mayo_fouls'])
    o_fouls = len(parsed['opp_fouls'])

    # Attacks
    m_atts = len(parsed['mayo_attacks'])
    o_atts = len(parsed['opp_attacks'])

    # Score timeline
    score_tl = build_score_timeline(parsed, opponent)

    # Get existing round numbers for auto-assign
    lines = html.split('\n')
    raw_line = next((l for l in lines if l.startswith('const RAW=')), None)
    existing_rounds = []
    if raw_line:
        try:
            raw_data = json.loads(raw_line[len('const RAW='):-1])
            existing_rounds = [m['roundNum'] for m in raw_data.get('matches',[])]
        except:
            pass
    round_num = (max(existing_rounds) + 1) if existing_rounds else 1

    flags = build_flags(round_label, opponent, venue, parsed,
                        mg, mp2, mp1, og, op2, op1, scorers, m_goalAtt, o_goalAtt)

    new_match = {
        'round': round_label, 'roundNum': round_num,
        'opponent': opponent, 'mayoScore': mayo_score_s, 'oppScore': opp_score_s,
        'result': result, 'mayoTotal': m_total, 'oppTotal': o_total,
        'mayoShotAcc': ms_acc, 'oppShotAcc': os_acc,
        'mayoKOWin': mko_pct, 'oppKOWin': oko_pct,
        'mayoAttacks': m_atts, 'oppAttacks': o_atts,
        'mayoShots': ms_total, 'oppShots': os_total,
        'mayoTurnovers': m_tos, 'oppTurnovers': o_tos,
        'mayoKOTotal': mko_total, 'mayoKOWon': mko_won,
        'oppKOTotal': oko_total, 'oppKOWon': oko_won,
        'mayo1pt': mp1, 'mayo1ptAtt': m_1ptAtt,
        'mayo2pt': mp2, 'mayo2ptAtt': m_2ptAtt,
        'mayoGoal': mg, 'mayoGoalAtt': m_goalAtt,
        'mayoFouls': m_fouls, 'oppFouls': o_fouls,
        'mayoKOShort': mko_short, 'mayoKOMed': mko_med, 'mayoKOLong': mko_long,
        'scorers': scorers, 'flags': flags, 'scoreTimeline': score_tl,
    }

    print(f'  Score: Mayo {mayo_score_s} {result} {opponent} {opp_score_s}')
    print(f'  Shots: Mayo {ms_scored}/{ms_total} ({ms_acc}%)  |  {opponent} {os_scored}/{os_total} ({os_acc}%)')
    print(f'  Mayo KO: {mko_won}/{mko_total} ({mko_pct}%)  |  {opponent} KO: {oko_won}/{oko_total} ({oko_pct}%)')
    print(f'  Turnovers: Mayo {m_tos}  {opponent} {o_tos}  |  Fouls: Mayo {m_fouls}  {opponent} {o_fouls}')
    print(f'  Attacks: Mayo {m_atts}  {opponent} {o_atts}')

    # Compute all derived data
    mayo_pd, opp_pd = build_shot_period_data(parsed)
    pad_data         = build_period_attack_data(parsed)
    ptd_data         = build_period_tempo_data(parsed)
    rt_entry         = build_round_tempo(parsed, round_label, opponent)
    poss_data        = build_possession_data(parsed)
    momentum         = build_momentum_events(parsed)
    category         = comp_category(round_label)

    print(f'\n  Updating data structures...')

    # 1. RAW.matches
    html = update_raw_matches(html, new_match)
    print('  ✓ RAW.matches')

    # 2. SHOT_MAP_DATA
    new_shot_entries = fmt_shot_map_entries(parsed['mayo_shots'], round_label)
    html, ok = insert_before_struct_close(html, 'SHOT_MAP_DATA', new_shot_entries, ']')
    print(f'  {"✓" if ok else "⚠"} SHOT_MAP_DATA ({len(parsed["mayo_shots"])} entries)')

    # 3. OPP_SHOT_MAP_DATA
    new_opp_shot = fmt_opp_shot_map_entries(parsed['opp_shots'], round_label)
    html, ok = insert_before_struct_close(html, 'OPP_SHOT_MAP_DATA', new_opp_shot, ']')
    print(f'  {"✓" if ok else "⚠"} OPP_SHOT_MAP_DATA ({len(parsed["opp_shots"])} entries)')

    # 4. KO_PITCH_DATA
    new_ko = fmt_ko_pitch_entries(parsed['mayo_kos'], round_label, venue)
    html, ok = insert_before_struct_close(html, 'KO_PITCH_DATA', new_ko, ']')
    print(f'  {"✓" if ok else "⚠"} KO_PITCH_DATA ({len(parsed["mayo_kos"])} entries)')

    # 5. OPP_KO_DATA
    new_opp_ko = fmt_opp_ko_entries(parsed['opp_kos'], round_label)
    html, ok = insert_before_struct_close(html, 'OPP_KO_DATA', new_opp_ko, ']')
    print(f'  {"✓" if ok else "⚠"} OPP_KO_DATA ({len(parsed["opp_kos"])} entries)')

    # 6. OPP_KO_PERIOD_DATA
    okp = fmt_opp_ko_period(round_label, parsed['opp_kos'], period_of)
    html, ok = insert_before_struct_close(html, 'OPP_KO_PERIOD_DATA', okp)
    print(f'  {"✓" if ok else "⚠"} OPP_KO_PERIOD_DATA')

    # 7. TURNOVER_PERIOD_DATA
    tp = fmt_turnover_period(round_label, parsed)
    html, ok = insert_before_struct_close(html, 'TURNOVER_PERIOD_DATA', tp)
    print(f'  {"✓" if ok else "⚠"} TURNOVER_PERIOD_DATA  (Mayo:{m_tos}  Opp:{o_tos})')

    # 8. FOUL_PERIOD_DATA
    fp = fmt_foul_period(round_label, parsed)
    html, ok = insert_before_struct_close(html, 'FOUL_PERIOD_DATA', fp)
    print(f'  {"✓" if ok else "⚠"} FOUL_PERIOD_DATA  (Mayo:{m_fouls}  Opp:{o_fouls})')

    # 9. TACKLE_PERIOD_DATA
    tack = fmt_tackle_period(round_label, parsed)
    html, ok = insert_before_struct_close(html, 'TACKLE_PERIOD_DATA', tack)
    print(f'  {"✓" if ok else "⚠"} TACKLE_PERIOD_DATA  (total:{len(parsed["mayo_tackles"])})')

    # 10. TACKLE_COUNTS_PER_PLAYER
    tack_c = fmt_tackle_counts(round_label, parsed)
    html, ok = insert_before_struct_close(html, 'TACKLE_COUNTS_PER_PLAYER', tack_c)
    print(f'  {"✓" if ok else "⚠"} TACKLE_COUNTS_PER_PLAYER')

    # 11. ROUND_TEMPO
    rt_str = fmt_round_tempo(rt_entry)
    html, ok = insert_before_struct_close(html, 'ROUND_TEMPO', rt_str, ']')
    print(f'  {"✓" if ok else "⚠"} ROUND_TEMPO  (avg mayo:{rt_entry["mayo"]["avg"]}s opp:{rt_entry["opp"]["avg"]}s)')

    # 12. PERIOD_ATTACK_DATA_BY_ROUND
    pad_str = fmt_period_dict_entry(round_label, pad_data)
    html, ok = insert_before_struct_close(html, 'PERIOD_ATTACK_DATA_BY_ROUND', pad_str)
    print(f'  {"✓" if ok else "⚠"} PERIOD_ATTACK_DATA_BY_ROUND')

    # 13. PERIOD_TEMPO_DATA_BY_ROUND
    ptd_str = fmt_period_dict_entry(round_label, ptd_data)
    html, ok = insert_before_struct_close(html, 'PERIOD_TEMPO_DATA_BY_ROUND', ptd_str)
    print(f'  {"✓" if ok else "⚠"} PERIOD_TEMPO_DATA_BY_ROUND')

    # 14. POSSESSION_PERIOD_DATA
    poss_str = fmt_possession(round_label, poss_data)
    html, ok = insert_before_struct_close(html, 'POSSESSION_PERIOD_DATA', poss_str)
    print(f'  {"✓" if ok else "⚠"} POSSESSION_PERIOD_DATA')

    # 15. MOMENTUM_EVENTS
    mom_str = fmt_momentum_entry(round_label, momentum)
    html, ok = insert_before_struct_close(html, 'MOMENTUM_EVENTS', mom_str)
    print(f'  {"✓" if ok else "⚠"} MOMENTUM_EVENTS  ({len(momentum["events"])} events)')

    # 16. SHOT_PERIOD_DATA
    spd_str = fmt_shot_period_entry(round_label, mayo_pd, opp_pd)
    html, ok = insert_before_struct_close(html, 'SHOT_PERIOD_DATA', spd_str)
    print(f'  {"✓" if ok else "⚠"} SHOT_PERIOD_DATA')

    # 17. PLAYER_ATTACK_META
    html = update_player_attack_meta(html, round_label, parsed['mayo_attacks'])
    print(f'  ✓ PLAYER_ATTACK_META')

    # 18. SHOT_META
    html = update_shot_meta(html, round_label, parsed['mayo_shots'])
    print(f'  ✓ SHOT_META')

    # 19. PLAYER_SCORE_ASSIST_DETAIL
    html = update_player_score_detail(html, parsed['mayo_scores'])
    print(f'  ✓ PLAYER_SCORE_ASSIST_DETAIL')

    # 20. GK_KO_DATA
    html = update_gk_ko_data(html, gk_key, round_label, parsed['mayo_kos'], [], [])
    print(f'  ✓ GK_KO_DATA  (gk: {gk_key})')

    # 21. COMPETITION_ROUNDS
    html = update_competition_rounds(html, round_label, category)
    print(f'  ✓ COMPETITION_ROUNDS  (category: {category})')

    # 22. ROUNDS_HOME_AWAY
    html = update_rounds_home_away(html, round_label, venue)
    print(f'  ✓ ROUNDS_HOME_AWAY  ({venue})')

    # Fix existing GK_KO_DATA Rd.1–6 bug (now includes all played rounds)
    html = fix_gk_ko_rounds_bug(html)
    print(f'  ✓ GK_KO_DATA rounds string rebuilt')

    # 23. SCORE_SOURCES / TURNOVER_ZONES / KO_OUTCOMES / PERIOD_SPLITS (rebuilt from all XMLs)
    html = rebuild_season_structures(html)
    print('  ✓ SCORE_SOURCES / TURNOVER_ZONES / KO_OUTCOMES / PERIOD_SPLITS (rebuilt)')

    return html

# ── Git commit & push ─────────────────────────────────────────────────────────
def git_commit_push(round_label, opponent):
    msg = f'Add {round_label} v {opponent} data via auto-update pipeline'
    cmds = [
        ['git', '-C', BASE_DIR, 'add', 'mayo-dashboard.html'],
        ['git', '-C', BASE_DIR, 'commit', '-m', msg],
        ['git', '-C', BASE_DIR, 'push'],
    ]
    for cmd in cmds:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f'  ⚠️  Git command failed: {" ".join(cmd)}')
            print(f'     {result.stderr.strip()}')
            return False
        print(f'  ✓  {" ".join(cmd[3:])}')
    return True

# ── Entry point ───────────────────────────────────────────────────────────────
def main(round_label, opponent, venue, xml_path=None, gk_key='hennelly'):
    print(f'\n🏈 Mayo Dashboard Update — {round_label} v {opponent} ({venue})')
    print('─' * 60)

    # Find XML
    if xml_path is None:
        xmls = glob.glob(os.path.join(XML_DIR, '*.xml'))
        if not xmls:
            print('❌ No XML files found in NFL Timelines/')
            return
        xml_path = max(xmls, key=os.path.getmtime)
    print(f'  XML: {os.path.basename(xml_path)}')

    # Parse
    print('\n📋 Parsing XML...')
    parsed = parse_xml(xml_path)
    opp_upper = parsed['opp_team_upper']
    print(f'  Detected opponent team code: {opp_upper}')
    print(f'  Mayo shots: {len(parsed["mayo_shots"])}  |  Opp shots: {len(parsed["opp_shots"])}')
    print(f'  Mayo KOs: {len(parsed["mayo_kos"])}  |  Opp KOs: {len(parsed["opp_kos"])}')
    print(f'  Mayo tackles: {len(parsed["mayo_tackles"])}')
    print(f'  Mayo attacks: {len(parsed["mayo_attacks"])}  |  Opp attacks: {len(parsed["opp_attacks"])}')

    # Read dashboard
    print('\n📝 Reading dashboard...')
    with open(DASHBOARD, 'r', encoding='utf-8') as f:
        html = f.read()
    orig_len = len(html)

    # Update
    print('\n⚙️  Updating data structures...')
    html = update_html(html, round_label, opponent, venue, parsed, gk_key)

    # Write
    with open(DASHBOARD, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'\n✅ Dashboard written  ({len(html) - orig_len:+,} bytes)')

    # Git
    print('\n🚀 Committing and pushing...')
    ok = git_commit_push(round_label, opponent)
    if ok:
        print('\n✅ Done! Dashboard live in ~30 seconds.')
    else:
        print('\n⚠️  Push failed — check git output above.')

    # Reminders
    print('\n📌 Manual reminders:')
    unknowns = [s['player'] for s in parsed['mayo_shots'] if s['player'] == 'Unknown']
    if unknowns:
        print(f'   ⚠️  {len(unknowns)} shot(s) with no player label — update XML and re-run or edit scoreTimeline manually.')
    print('   ℹ️  Update Team Sheets for this game.')
    print(f'   ℹ️  GK assigned to "{gk_key}" — verify this is correct.')
    print('   ℹ️  GK_KO_DATA.scoresFromKOWon and oppScoresFromKOLost require manual update.')
    print('   ℹ️  GK_KO_DATA.top3 player rankings require manual update from KO contest data.')
    print('   ℹ️  SCORE_SOURCES / TURNOVER_ZONES / KO_OUTCOMES / PERIOD_SPLITS are auto-rebuilt from all XMLs.')
    print('   ℹ️  RAW.seasonPlayers stats require manual update if needed.')

if __name__ == '__main__':
    args = sys.argv[1:]
    # Strip --xml and --gk flags
    xml_path = None
    gk_key   = 'hennelly'
    clean_args = []
    i = 0
    while i < len(args):
        if args[i] == '--xml' and i+1 < len(args):
            xml_path = args[i+1]; i += 2
        elif args[i] == '--gk' and i+1 < len(args):
            gk_key = args[i+1]; i += 2
        else:
            clean_args.append(args[i]); i += 1

    if len(clean_args) < 3:
        print('⚠️  Usage: update dashboard \'ROUND\' Opponent Venue')
        print('   e.g.:  update dashboard \'AISFC Rd.1\' Tyrone Away')
        print('\n   Required: ROUND (e.g. \'Rd.1\', \'AISFC SF\'), Opponent name, Home or Away')
        sys.exit(0)

    main(clean_args[0], clean_args[1], clean_args[2], xml_path, gk_key)
