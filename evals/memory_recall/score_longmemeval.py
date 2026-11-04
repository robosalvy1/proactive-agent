"""Summarize run_longmemeval.py output by question type: evidence recall in Home's top 8."""
import collections
import json
import statistics
import sys

for path in sys.argv[1:]:
    rows = json.load(open(path))['results']
    print(f'\n{path}  (n={len(rows)})')
    groups = collections.defaultdict(list)
    for row in rows:
        groups['abstention' if row['abstention'] else row['type']].append(row)
    groups['ALL (answerable)'] = [r for r in rows if not r['abstention']]
    legs = ('keyword', 'semantic', 'merged')
    print(f"{'type':28} {'n':>3}  " + '  '.join(f'{leg + " any/all/turn":>22}' for leg in legs))
    for name in sorted(groups, key=lambda n: (n.startswith('ALL'), n)):
        group = groups[name]
        cells = []
        for leg in legs:
            pct = lambda key: 100 * sum(bool(r[leg][key]) for r in group) / len(group)
            cells.append(f"{pct('session_any'):6.0f}%{pct('session_all'):6.0f}%{pct('turn_any'):6.0f}%")
        print(f'{name:28} {len(group):3}  ' + '  '.join(f'{c:>22}' for c in cells))
    abst = groups.get('abstention', [])
    if abst:
        print('abstention questions returning anything (merged):',
              sum(r['merged']['returned'] > 0 for r in abst), '/', len(abst))
    print('median recall ms', round(statistics.median(r['ms'] for r in rows), 1))
