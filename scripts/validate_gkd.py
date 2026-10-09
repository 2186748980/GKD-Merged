# -*- coding: utf-8 -*-
"""Standalone quality gate for the generated merged subscription.

Reads gkd/gkd.json5 fresh (via json5) and cross-checks it against the raw
upstream caches. Deliberately shares NO code with scripts/merge_gkd.py so the
verification logic is independent of the build logic.

Exit code 0 = all checks passed; non-zero = failures (listed on stdout).

Usage (repo root):
    python scripts/validate_gkd.py
"""
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    import json5
except ImportError:
    raise SystemExit('json5 package missing (pip install json5)')

SUB = Path('gkd/gkd.json5')
STATUS = Path('gkd/merge-status.json')
REPORT = Path('gkd/duplicate-report.json')
CACHES = sorted(Path('cache/sources').glob('*.json5'))

failures = []
results = {}


def check(name, ok, detail=''):
    results[name] = 'PASS' if ok else 'FAIL'
    if not ok:
        failures.append(f'{name}: {detail}')


sub = None
try:
    sub = json5.loads(SUB.read_text(encoding='utf-8'))
    check('01 json5 parseable', isinstance(sub, dict))
except Exception as e:  # noqa: BLE001
    check('01 json5 parseable', False, repr(e))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    raise SystemExit(1)

scopes = [(a.get('id'), a.get('groups') or []) for a in sub.get('apps', [])]
if isinstance(sub.get('globalGroups'), list):
    scopes.append(('globalGroups', sub['globalGroups']))

dup_rule_keys = []
dup_group_keys = []
dangling = []
ambiguous = []
dup_evidence_urls = []
ref_total = 0

rule_fields = ('preKeys', 'actionCdKey', 'actionMaximumKey')
group_fields = ('actionMaximumKey',)

# Audited preserved dangling references: the merge build deliberately keeps
# upstream references that point at a missing rule key (dropping them would
# open the rule gate). These are the ONLY dangling references allowed, and
# EACH declared one must actually be present in the output (bidirectional
# multiset equality checked at step 12).
declared_dangling = defaultdict(int)
resolved_expect = {}  # refs annotated as resolvable after key normalization
try:
    report = json.loads(REPORT.read_text(encoding='utf-8'))
    for ev in (report.get('referenceRepairsByType') or {}).get('keptDanglingReference', []):
        sig = (ev.get('scope'), ev.get('group'), ev.get('rule'), ev.get('field'), ev.get('referencedKey'))
        if ev.get('resolvesAfterRenumbering'):
            resolved_expect[sig] = ev
        else:
            declared_dangling[sig] = declared_dangling.get(sig, 0) + 1
except FileNotFoundError:
    pass  # no report -> nothing may dangle


def consume_declared(scope, group_name, rule_name, fld, key):
    sig = (scope, group_name, rule_name, fld, key)
    if declared_dangling.get(sig, 0) > 0:
        declared_dangling[sig] -= 1
        return True
    return False


declared_dangling_total = sum(declared_dangling.values())

# 02/03 uniqueness + 04-08 reference resolution
for scope, groups in scopes:
    key_index = defaultdict(list)
    gkeys = defaultdict(int)
    rules_all = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        if isinstance(g.get('key'), int):
            gkeys[g['key']] += 1
        rules = g.get('rules')
        if isinstance(rules, dict):
            rules = [rules]
        for r in rules or []:
            if not isinstance(r, dict):
                continue
            rules_all.append((g, r))
            if isinstance(r.get('key'), int):
                key_index[r['key']].append((g, r))
    for k, holders in key_index.items():
        if len(holders) > 1:
            dup_rule_keys.append((scope, k, len(holders)))
    for k, n in gkeys.items():
        if n > 1:
            dup_group_keys.append((scope, k, n))
    for g, r in rules_all:
        for fld in rule_fields:
            v = r.get(fld)
            vals = [x for x in v if isinstance(x, int)] if isinstance(v, list) else ([v] if isinstance(v, int) else [])
            for k in vals:
                n = len(key_index.get(k, []))
                ref_total += 1
                if n == 0:
                    if not consume_declared(scope, g.get('name'), r.get('name'), fld, k):
                        dangling.append((scope, g.get('name'), r.get('name'), fld, k))
                elif n > 1:
                    ambiguous.append((scope, g.get('name'), r.get('name'), fld, k, n))
        for fld in ('snapshotUrls', 'exampleUrls'):
            v = r.get(fld)
            if isinstance(v, list) and len(v) != len(set(v)):
                dup_evidence_urls.append((scope, g.get('name'), r.get('name'), fld))
    for g in groups:
        if not isinstance(g, dict):
            continue
        for fld in group_fields:
            v = g.get(fld)
            if isinstance(v, int):
                ref_total += 1
                n = len(key_index.get(v, []))
                if n == 0:
                    if not consume_declared(scope, g.get('name'), None, fld, v):
                        dangling.append((scope, g.get('name'), None, f'group.{fld}', v))
                elif n > 1:
                    ambiguous.append((scope, g.get('name'), None, f'group.{fld}', v, n))

check('02 rule keys unique per app', not dup_rule_keys, str(dup_rule_keys[:5]))
check('03 group keys unique per scope', not dup_group_keys, str(dup_group_keys[:5]))
check('04 preKeys hit exactly one rule', not any(d[3] == 'preKeys' or (isinstance(d[3], str) and d[3].endswith('preKeys')) for d in dangling + ambiguous))
check('05 actionCdKey hit exactly one rule', not any(d[3] == 'actionCdKey' for d in dangling + ambiguous))
check('06 actionMaximumKey hit exactly one rule (rule+group)',
      not any('actionMaximumKey' in d[3] for d in dangling + ambiguous))
check('07 no un-audited dangling references', not dangling, str(dangling[:5]))
check('08 no ambiguous references', not ambiguous, str(ambiguous[:5]))
check('09 no dependency breakage', not dangling and not ambiguous)
check('10 evidence URL lists have no duplicates', not dup_evidence_urls, str(dup_evidence_urls[:5]))

# 12 bidirectional closure of the audited dangling set: every dangling
# reference still in the output was declared (enforced above by consumption),
# and every declared reference is STILL in the output (none below > 0).
undeclared_left = {sig: n for sig, n in declared_dangling.items() if n > 0}
check('12 audited dangling refs reproduced exactly (none lost, none extra)',
      not undeclared_left, str(sorted(undeclared_left.items())[:5]))

# 12b references annotated as "was dangling, resolves uniquely after key
# normalization" must be VERIFIABLY single-hit in the final output, and the
# referring rule must still carry the preserved value in the reported field.
scope_index = {}
scope_groups = {}
for scope, groups in scopes:
    idx = defaultdict(list)
    for g in groups:
        if not isinstance(g, dict):
            continue
        for r in (g.get('rules') or []):
            if isinstance(r, dict) and isinstance(r.get('key'), int):
                idx[r['key']].append((g, r))
    scope_index[scope] = idx
    scope_groups[scope] = [g for g in groups if isinstance(g, dict)]

bad_resolved = []
for (scope, group_name, rule_name, fld, key), ev in resolved_expect.items():
    idx = scope_index.get(scope, {})
    if len(idx.get(key, [])) != 1:
        bad_resolved.append((scope, group_name, rule_name, fld, key,
                             f'target hits={len(idx.get(key, []))}'))
        continue
    holder_found = False
    for g in scope_groups.get(scope, []):
        if g.get('name') != group_name:
            continue
        for r in (g.get('rules') or []):
            if not isinstance(r, dict) or r.get('name') != rule_name:
                continue
            v = r.get(fld)
            vals = v if isinstance(v, list) else ([v] if isinstance(v, int) else [])
            if key in vals:
                holder_found = True
    if not holder_found:
        bad_resolved.append((scope, group_name, rule_name, fld, key, 'holder no longer carries value'))
check('12b renumbering-resolved refs truly single-hit and value preserved',
      not bad_resolved, str(bad_resolved[:5]))

# 11 activityIds / evidence values were never invented or rewritten: every
# such string in the output must appear verbatim in at least one upstream cache.
upstream_activities = set()
upstream_urls = set()


def harvest(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == 'activityIds':
                items = v if isinstance(v, list) else [v]
                for it in items:
                    if isinstance(it, str):
                        upstream_activities.add(it)
            elif k in ('snapshotUrls', 'exampleUrls'):
                items = v if isinstance(v, list) else [v]
                for it in items:
                    if isinstance(it, str):
                        upstream_urls.add(it)
            harvest(v)
    elif isinstance(node, list):
        for x in node:
            harvest(x)


for path in CACHES:
    try:
        harvest(json5.loads(path.read_text(encoding='utf-8')))
    except Exception as e:  # noqa: BLE001
        print(f'warn: cannot read upstream cache {path}: {e}', file=sys.stderr)

out_activities = set()
out_urls = set()
for _scope, groups in scopes:
    for g in groups:
        if not isinstance(g, dict):
            continue
        v = g.get('activityIds')
        for it in (v if isinstance(v, list) else ([v] if isinstance(v, str) else [])):
            out_activities.add(it)
        for r in g.get('rules') or []:
            if not isinstance(r, dict):
                continue
            v = r.get('activityIds')
            for it in (v if isinstance(v, list) else ([v] if isinstance(v, str) else [])):
                out_activities.add(it)
            for fld in ('snapshotUrls', 'exampleUrls'):
                rv = r.get(fld)
                for it in (rv if isinstance(rv, list) else ([rv] if isinstance(rv, str) else [])):
                    if isinstance(it, str):
                        out_urls.add(it)

unknown_act = {a for a in out_activities if a not in upstream_activities}
unknown_urls = {u for u in out_urls if u not in upstream_urls}
check('11a activityIds never rewritten (output ⊆ upstream verbatim)', not unknown_act,
      str(sorted(unknown_act)[:5]))
check('11b evidence URLs never invented (output ⊆ upstream)', not unknown_urls,
      str(sorted(unknown_urls)[:5]))

# 13 content hash consistency between gkd.json5 and merge-status.json
try:
    status = json.loads(STATUS.read_text(encoding='utf-8'))
    core = {k: v for k, v in sub.items() if k not in {'version', 'checkUpdateUrl'}}
    raw = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    got = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    check('13 contentHash matches merge-status', got == status.get('contentHash'),
          f'computed {got} vs status {status.get("contentHash")}')
    check('14 status validation ok', bool(status.get('validation', {}).get('ok')))
except Exception as e:  # noqa: BLE001
    check('13 contentHash matches merge-status', False, repr(e))

counts = {
    'apps': len(sub.get('apps', [])),
    'appRuleGroups': sum(len(a.get('groups') or []) for a in sub.get('apps', [])),
    'ruleObjects': sum(len(g.get('rules') or []) if isinstance(g.get('rules'), list) else 1
                       for a in sub.get('apps', []) for g in a.get('groups') or []),
    'dependencyRefsChecked': ref_total,
    'auditedDanglingReferences': declared_dangling_total,
    'renumberingResolvedReferences': len(resolved_expect),
    'unauditedDanglingReferences': len(dangling),
    'upstreamCaches': [p.name for p in CACHES],
}
print(json.dumps({'checks': results, 'counts': counts}, ensure_ascii=False, indent=2))
if failures:
    print('FAILURES:')
    for f in failures:
        print(' -', f)
    raise SystemExit(1)
print('ALL CHECKS PASSED')
