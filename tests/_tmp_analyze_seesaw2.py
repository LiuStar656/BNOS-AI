# -*- coding: utf-8 -*-
import json, os

base = r'e:\杂项\BNOS_AI_project\docs\experiments\cognitive_evolution_test\runs\20260812_seesaw2_214124'
for gid in ('SUBJPUSH', 'OBJPUSH'):
    r = json.load(open(os.path.join(base, f'seesaw2_{gid}_rounds.json'), encoding='utf-8'))
    print('=' * 70)
    print('GROUP', gid)
    for i in (0, 4, 9):
        e = r['log'][i]
        print(f"-- r{e['round']} in={e['input']}")
        print('   reply: ' + (e.get('reply') or '')[:260])
        print('   self : ' + (e.get('self_report') or '')[:200])
