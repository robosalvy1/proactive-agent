"""Summarize magic_run.py results per memory system and category."""
import collections
import json
import sys


def main(path):
    data = json.load(open(path))
    rows, systems = data['results'], data['args']['systems'].split(',')
    positive = [r for r in rows if r['category'] != 'negative']
    negative = [r for r in rows if r['category'] == 'negative']
    print(f'{path}: {len(positive)} scenarios with hidden facts, {len(negative)} negatives\n')
    print(f"{'system':15} {'magic':>7} {'facts used':>11} {'intrusion':>10} {'invented':>9} {'negatives ok':>13}")
    for system in systems:
        done = [r for r in positive if system in r]
        if not done:
            continue
        magic = sum(r[system]['magic'] for r in done)
        used = sum(sum(r[system]['used']) for r in done)
        facts = sum(len(r[system]['used']) for r in done)
        intrusion = sum(r[system]['intrusion'] for r in rows if system in r)
        invented = sum(r[system]['invented'] for r in rows if system in r)
        neg = sum(r[system]['magic'] for r in negative if system in r)
        n_all = sum(system in r for r in rows)
        print(f'{system:15} {100 * magic / len(done):6.0f}% {100 * used / max(1, facts):10.0f}% '
              f'{100 * intrusion / n_all:9.0f}% {100 * invented / n_all:8.0f}% '
              f'{neg:>6}/{len(negative)}')
    print('\nmagic by category:')
    by = collections.defaultdict(list)
    for r in positive:
        by[r['category']].append(r)
    print(f"{'category':12} " + ' '.join(f'{s[:13]:>13}' for s in systems))
    for category in sorted(by):
        cells = []
        for system in systems:
            done = [r for r in by[category] if system in r]
            cells.append(f"{sum(r[system]['magic'] for r in done)}/{len(done)}" if done else '-')
        print(f'{category:12} ' + ' '.join(f'{c:>13}' for c in cells))


if __name__ == '__main__':
    for arg in sys.argv[1:]:
        main(arg)
