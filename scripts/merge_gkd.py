import json
import hashlib
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SOURCES = [
    {"id": "linarm", "name": "Lin-arm", "priority": 100, "url": "https://raw.githubusercontent.com/Lin-arm/GKD_subscription/main/dist/gkd.json5"},
    {"id": "ganlinte", "name": "ganlinte", "priority": 90, "url": "https://raw.githubusercontent.com/ganlinte/GKD-subscription/main/dist/ganlin_gkd.json5"},
    {"id": "aisouler", "name": "AIsouler（历史）", "priority": 50, "url": "https://raw.githubusercontent.com/q595002599/AIsouler_GKD_subscription/main/dist/AIsouler_gkd.json5"},
    {"id": "adpro", "name": "Adpro（历史）", "priority": 40, "url": "https://raw.githubusercontent.com/Adpro-Team/GKD_subscription/main/dist/Adpro_gkd.json5"},
]

CACHE = Path('cache/sources')
OUT = Path('gkd')
CACHE.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

try:
    import json5
except ImportError:
    raise SystemExit('json5 package missing')

STATUS = []


def load_source(src):
    cache = CACHE / f"{src['id']}.json5"
    try:
        req = urllib.request.Request(src['url'], headers={'User-Agent': 'GKD-Merged/2.0'})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        cache.write_bytes(data)
        STATUS.append({'id': src['id'], 'name': src['name'], 'download': 'ok', 'bytes': len(data)})
    except Exception as e:
        if not cache.exists():
            STATUS.append({'id': src['id'], 'name': src['name'], 'download': 'failed', 'error': repr(e)})
            return None
        STATUS.append({'id': src['id'], 'name': src['name'], 'download': 'cache', 'error': repr(e)})
    try:
        data = json5.loads(cache.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise TypeError(f'root is {type(data).__name__}, expected object')
        STATUS[-1]['parse'] = 'ok'
        STATUS[-1]['sourceVersion'] = data.get('version')
        return data
    except Exception as e:
        STATUS[-1]['parse'] = 'failed'
        STATUS[-1]['parseError'] = repr(e)
        return None


def normalize_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def ensure_rules_list(group):
    rules = group.get('rules')
    if rules is None:
        group['rules'] = []
    elif isinstance(rules, dict):
        group['rules'] = [rules]
    elif not isinstance(rules, list):
        group['rules'] = []
    return group['rules']


def fingerprint(obj):
    if not isinstance(obj, dict):
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    x = {k: v for k, v in obj.items() if k not in {'key', 'preKeys'}}
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def remap_rules(dst_rules, src_rules):
    """Merge rules while preserving the complete old->new key map before rewriting preKeys."""
    dst_rules = dst_rules if isinstance(dst_rules, list) else []
    used = {r.get('key') for r in dst_rules if isinstance(r, dict) and isinstance(r.get('key'), int)}
    existing_by_fp = {fingerprint(r): r.get('key') for r in dst_rules if isinstance(r, dict)}
    next_key = max(used, default=-1) + 1
    mapping = {}
    pending = []

    for r in src_rules:
        if not isinstance(r, dict):
            continue
        old = r.get('key')
        fp = fingerprint(r)
        if fp in existing_by_fp:
            if isinstance(old, int):
                mapping[old] = existing_by_fp[fp]
            continue
        nr = dict(r)
        if isinstance(old, int):
            while next_key in used:
                next_key += 1
            mapping[old] = next_key
            nr['key'] = next_key
            used.add(next_key)
            next_key += 1
        pending.append(nr)
        existing_by_fp[fp] = nr.get('key')

    for nr in pending:
        if isinstance(nr.get('preKeys'), list):
            nr['preKeys'] = [mapping.get(k, k) for k in nr['preKeys']]
        elif isinstance(nr.get('preKeys'), int):
            nr['preKeys'] = mapping.get(nr['preKeys'], nr['preKeys'])
        dst_rules.append(nr)
    return dst_rules


def merge_groups(dst_groups, src_groups):
    by_name = {g.get('name'): g for g in dst_groups if isinstance(g, dict) and g.get('name') is not None}
    used_keys = {g.get('key') for g in dst_groups if isinstance(g, dict) and isinstance(g.get('key'), int)}
    next_key = max(used_keys, default=-1) + 1
    for sg in normalize_list(src_groups):
        if not isinstance(sg, dict):
            continue
        name = sg.get('name')
        if name in by_name:
            dg = by_name[name]
            ensure_rules_list(dg)
            remap_rules(dg['rules'], normalize_list(sg.get('rules')))
            for k, v in sg.items():
                if k not in dg and k != 'rules':
                    dg[k] = v
            continue
        ng = dict(sg)
        if isinstance(ng.get('key'), int):
            while next_key in used_keys:
                next_key += 1
            ng['key'] = next_key
            used_keys.add(next_key)
            next_key += 1
        ng['rules'] = [dict(r) for r in normalize_list(ng.get('rules')) if isinstance(r, dict)]
        dst_groups.append(ng)
        if name is not None:
            by_name[name] = ng


def merge_global_groups(dst, src):
    by_name = {g.get('name'): g for g in dst if isinstance(g, dict) and g.get('name') is not None}
    used_keys = {g.get('key') for g in dst if isinstance(g, dict) and isinstance(g.get('key'), int)}
    next_key = max(used_keys, default=-1) + 1
    for sg in normalize_list(src):
        if not isinstance(sg, dict):
            continue
        name = sg.get('name')
        if name in by_name:
            dg = by_name[name]
            ensure_rules_list(dg)
            remap_rules(dg['rules'], normalize_list(sg.get('rules')))
            for k, v in sg.items():
                if k not in dg and k != 'rules':
                    dg[k] = v
            continue
        ng = dict(sg)
        if isinstance(ng.get('key'), int):
            while next_key in used_keys:
                next_key += 1
            ng['key'] = next_key
            used_keys.add(next_key)
            next_key += 1
        ng['rules'] = [dict(r) for r in normalize_list(ng.get('rules')) if isinstance(r, dict)]
        dst.append(ng)
        if name is not None:
            by_name[name] = ng


def canonical_hash(obj):
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def next_version(content_hash):
    meta_path = OUT / 'version-state.json'
    today = datetime.now(timezone.utc).strftime('%Y%m%d')
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
        except Exception:
            meta = {}
    else:
        meta = {}

    if meta.get('contentHash') == content_hash and meta.get('version'):
        return int(meta['version']), meta

    old_version = int(meta.get('version', 0) or 0)
    old_day = str(old_version)[:8] if old_version >= 100000000 else ''
    old_seq = int(str(old_version)[8:]) if old_day and str(old_version)[8:] else 0
    seq = old_seq + 1 if old_day == today else 1
    version = int(f'{today}{seq:02d}')
    new_meta = {'version': version, 'date': today, 'sequence': seq, 'contentHash': content_hash}
    return version, new_meta


loaded = []
for s in SOURCES:
    d = load_source(s)
    if isinstance(d, dict):
        loaded.append((s, d))

if not loaded:
    (OUT / 'merge-status.json').write_text(json.dumps({'ok': False, 'time': int(time.time()), 'sources': STATUS}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('No upstream subscription could be loaded; wrote gkd/merge-status.json')
    raise SystemExit(1)

result = {
    'id': 2186748980,
    'name': 'GKD-Merged',
    'version': 0,
    'author': '吹落日晚风',
    'description': '自动整合 Lin-arm、ganlinte、AIsouler、Adpro；高优先级来源优先，低优先级来源用于补充缺失规则。',
    'checkUpdateUrl': './gkd.version.json5',
    'supportUri': 'https://github.com/2186748980/GKD-Merged',
}

cats = []
cat_names = set()
for _, d in loaded:
    for c in normalize_list(d.get('categories')):
        if isinstance(c, dict) and c.get('name') not in cat_names:
            cats.append(dict(c))
            cat_names.add(c.get('name'))
result['categories'] = cats

result['globalGroups'] = []
for _, d in loaded:
    merge_global_groups(result['globalGroups'], d.get('globalGroups'))

apps_by_id = {}
apps = []
for _, d in loaded:
    for a in normalize_list(d.get('apps')):
        if not isinstance(a, dict) or not a.get('id'):
            continue
        aid = a['id']
        if aid not in apps_by_id:
            na = dict(a)
            na['groups'] = [dict(g) for g in normalize_list(a.get('groups')) if isinstance(g, dict)]
            for g in na['groups']:
                ensure_rules_list(g)
            apps_by_id[aid] = na
            apps.append(na)
        else:
            merge_groups(apps_by_id[aid].setdefault('groups', []), a.get('groups'))

for a in apps:
    a['groups'] = sorted(a.get('groups', []), key=lambda g: (g.get('key', 10**9), g.get('name', '')))
apps.sort(key=lambda a: a.get('id', ''))
result['apps'] = apps

# Hash only the actual subscription content; metadata/version is deliberately excluded.
content_hash = canonical_hash({k: v for k, v in result.items() if k not in {'version', 'checkUpdateUrl'}})
version, meta = next_version(content_hash)
result['version'] = version

(OUT / 'gkd.json5').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(OUT / 'gkd.version.json5').write_text(json.dumps({'version': version}) + '\n', encoding='utf-8')
meta['sourceVersions'] = {s['id']: d.get('version') for s, d in loaded}
(OUT / 'version-state.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(OUT / 'merge-status.json').write_text(json.dumps({'ok': True, 'time': int(time.time()), 'version': version, 'contentHash': content_hash, 'sources': STATUS, 'apps': len(apps), 'globalGroups': len(result['globalGroups'])}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(f"Generated {OUT/'gkd.json5'}: version {version}, {len(apps)} apps, {len(result['globalGroups'])} global groups")
