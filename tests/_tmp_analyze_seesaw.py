# -*- coding: utf-8 -*-
import json, os

base = r'e:\杂项\BNOS_AI_project\docs\experiments\cognitive_evolution_test\runs\20260812_seesaw_213411'
for gid in ('OBJNEG', 'SUBJASK'):
    r = json.load(open(os.path.join(base, f'seesaw_{gid}_rounds.json'), encoding='utf-8'))
    print('=' * 70)
    print('GROUP', gid, 'final=', r['final_vector'])
    for i in (0, 5, 10, 15, 19):
        if i >= len(r['log']):
            continue
        e = r['log'][i]
        print(f"-- r{e['round']} in={e['input']}")
        print('   obs=', {k: round(v, 2) for k, v in e['obs'].items()})
        print('   reply: ' + (e.get('reply') or '')[:180])
        print('   self : ' + (e.get('self_report') or '')[:150])
