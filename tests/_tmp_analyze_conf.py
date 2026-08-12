# -*- coding: utf-8 -*-
import json, os, re

base = r'e:\杂项\BNOS_AI_project\docs\experiments\cognitive_evolution_test\runs\20260812_subjconf_212205'
for gid in ('AGREE', 'DISAGREE'):
    r = json.load(open(os.path.join(base, f'so_{gid}_rounds.json'), encoding='utf-8'))
    print('=' * 70)
    print('GROUP', gid, 'final=', r['final_vector'])
    # 抽样中间几轮
    idxs = [0, 3, 7, 12, 17, 19]
    for i in idxs:
        if i >= len(r['log']):
            continue
        e = r['log'][i]
        raw = (e.get('raw') or '').replace('\n', ' ')
        obs = {k: round(v, 2) for k, v in e['obs'].items()}
        print(f"-- r{e['round']} obs={obs}")
        print('   reply: ' + (e.get('reply') or '')[:160])
        print('   self : ' + (e.get('self_report') or '')[:160])
