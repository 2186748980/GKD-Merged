import json
import hashlib
import time
import urllib.request
from collections import defaultdict
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
DUPLICATE_REPORT = {'safeRemoved': [], 'review': [], 'referenceRepairs': [], 'disabledGroupAudit': []}

# Rule-key reference fields on rule objects, plus the group-level field.
RULE_REF_FIELDS = ('preKeys', 'actionCdKey', 'actionMaximumKey')
GROUP_REF_FIELDS = ('actionMaximumKey',)

# Evidence fields: display proof only, never part of duplicate detection.
# On removal their URLs are unioned into the kept copy (nothing is lost).
RULE_EVIDENCE_FIELDS = ('snapshotUrls', 'exampleUrls')
# Group display fields: excluded from the behavior-only group context.
GROUP_DISPLAY_FIELDS = {'desc', 'examples', 'exampleUrls', 'snapshotUrls', 'i18n'}

MAX_REVIEW_REFERRERS = 5

# Sentinel: unresolvable reference whose original value must be preserved.
_KEEP_DANGLING = object()

STATS = defaultdict(int)
REPAIR_SUSPECT_GROUPS = set()


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


# ---------------------------------------------------------------------------
# activityIds normalization -- COMPARISON ONLY. Stored values are never
# rewritten, so the actual matching scope of every rule/group is unchanged.
# Per GKD's relative-class convention ".Activity" is provably identical to
# "<appId>.Activity"; wildcard patterns and anything not provably relative to
# the current app id are kept verbatim (and can never trigger a merge).
# ---------------------------------------------------------------------------

def normalize_activity_item(item, app_id):
    if isinstance(item, str) and isinstance(app_id, str) and app_id:
        if len(item) > 1 and item[0] == '.' and '*' not in item and '?' not in item:
            return app_id + item
    return item


def canonical_activity_ids(value, app_id):
    items = value if isinstance(value, list) else [value]
    out = set()
    for it in items:
        if isinstance(it, str):
            out.add(normalize_activity_item(it, app_id))
        else:
            out.add(json.dumps(it, ensure_ascii=False, sort_keys=True))
    return sorted(out)


def has_unprovable_activity(group):
    """True when a group's activityIds contain wildcard/odd items, so a
    remaining set difference might be a notation artifact we cannot prove."""
    value = group.get('activityIds')
    items = value if isinstance(value, list) else ([value] if value is not None else [])
    for it in items:
        if isinstance(it, str) and ('*' in it or '?' in it):
            return True
        if isinstance(it, str) and it and not (it[0] == '.' or it[0].islower()):
            continue
        if not isinstance(it, str):
            return True
    return False


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------

def fingerprint(obj, app_id=None):
    """Behavioral rule fingerprint for duplicate detection.

    Excluded: key / preKeys (dependency identity, checked separately),
    snapshotUrls / exampleUrls (evidence only), and activityIds notation
    differences. name, matches, action and every other runtime field must
    match EXACTLY -- similar display text alone never counts as duplicate.
    """
    if not isinstance(obj, dict):
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    x = {k: v for k, v in obj.items() if k not in {'key', 'preKeys', 'snapshotUrls', 'exampleUrls'}}
    if app_id and 'activityIds' in x:
        x['activityIds'] = canonical_activity_ids(x['activityIds'], app_id)
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def legacy_fingerprint(obj):
    """Pre-optimization fingerprint; used to classify WHAT enabled a removal."""
    if not isinstance(obj, dict):
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    x = {k: v for k, v in obj.items() if k not in {'key', 'preKeys'}}
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def evidence_free_fingerprint(obj):
    """Legacy fingerprint minus evidence fields but WITHOUT activityIds
    normalization: equality proves the pair was a snapshotUrls/exampleUrls-only
    duplicate."""
    if not isinstance(obj, dict):
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    x = {k: v for k, v in obj.items() if k not in {'key', 'preKeys', 'snapshotUrls', 'exampleUrls'}}
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def group_context_fingerprint(group, app_id=None):
    """Strict group context: ignores display identity (name/key) and rules.
    activityIds normalized for comparison only."""
    x = {k: v for k, v in group.items() if k not in {'name', 'key', 'rules'}}
    if app_id and 'activityIds' in x:
        x['activityIds'] = canonical_activity_ids(x['activityIds'], app_id)
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def group_dict_behavior(group, app_id):
    x = {k: v for k, v in group.items()
         if k not in {'name', 'key', 'rules'} and k not in GROUP_DISPLAY_FIELDS}
    if app_id and 'activityIds' in x:
        x['activityIds'] = canonical_activity_ids(x['activityIds'], app_id)
    return x


def group_behavior_context(group, app_id=None):
    """Behavior-only group context. enable / activityIds / resetMatch /
    matchTime / matchDelay / matchRoot / fastQuery / actionMaximum /
    actionMaximumKey and every other runtime field must be identical;
    desc / snapshotUrls / examples are display-only and ignored."""
    return json.dumps(group_dict_behavior(group, app_id),
                      ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def context_diff_fields(group_a, group_b):
    a = {k: v for k, v in group_a.items() if k not in {'name', 'key', 'rules'}}
    b = {k: v for k, v in group_b.items() if k not in {'name', 'key', 'rules'}}
    missing = object()
    return sorted(k for k in set(a) | set(b) if a.get(k, missing) != b.get(k, missing))


def behavior_diff_fields(group_a, group_b, app_id):
    a = group_dict_behavior(group_a, app_id)
    b = group_dict_behavior(group_b, app_id)
    missing = object()
    return sorted(k for k in set(a) | set(b) if a.get(k, missing) != b.get(k, missing))


def has_prekeys(rule):
    value = rule.get('preKeys') if isinstance(rule, dict) else None
    return value not in (None, [], '')


def prekeys_equal(rule_a, rule_b):
    def norm(rule):
        v = rule.get('preKeys') if isinstance(rule, dict) else None
        if isinstance(v, int):
            return {v}
        if isinstance(v, list):
            return {k for k in v if isinstance(k, int)}
        return set()
    return norm(rule_a) == norm(rule_b)


def merge_evidence(kept_rule, removed_rule):
    """Union snapshotUrls / exampleUrls into the kept copy; URLs deduped,
    single-value scalar form preserved when possible."""
    merged_any = False
    for fld in RULE_EVIDENCE_FIELDS:
        a = normalize_list(kept_rule.get(fld))
        b = normalize_list(removed_rule.get(fld))
        if not a and not b:
            continue
        rebuilt = []
        for u in a + b:
            if u not in rebuilt:
                rebuilt.append(u)
        additions = len(rebuilt) - len(a)
        if additions <= 0:
            continue
        was_scalar = not isinstance(kept_rule.get(fld), list)
        if len(rebuilt) == 1 and was_scalar:
            kept_rule[fld] = rebuilt[0]
        else:
            kept_rule[fld] = rebuilt
        merged_any = True
    return merged_any


def normalize_evidence_lists(groups):
    """Deduplicate snapshotUrls / exampleUrls lists in place.

    Upstream subscriptions occasionally ship rules whose own evidence list
    repeats the same URL. Evidence URLs are display-only, so dropping
    repeats changes no rule behavior; this keeps post-build validation
    (every URL appears once) green for inherited data too.
    """
    for _group, rule in iter_scope_rules(groups):
        for fld in RULE_EVIDENCE_FIELDS:
            value = rule.get(fld)
            if not isinstance(value, list):
                continue
            deduped = []
            for u in value:
                if u not in deduped:
                    deduped.append(u)
            if len(deduped) != len(value):
                STATS['upstreamEvidenceUrlDedup'] += len(value) - len(deduped)
                rule[fld] = deduped


# ---------------------------------------------------------------------------
# Key / reference machinery (phase 1, unchanged semantics)
# ---------------------------------------------------------------------------

def iter_scope_rules(groups):
    for group in groups:
        if not isinstance(group, dict):
            continue
        for rule in ensure_rules_list(group):
            if isinstance(rule, dict):
                yield group, rule


def collect_rule_key_index(groups):
    index = defaultdict(list)
    for group, rule in iter_scope_rules(groups):
        key = rule.get('key')
        if isinstance(key, int):
            index[key].append((group, rule))
    return index


def referrers_for(groups, key, ignore_rule=None):
    """APP-wide scan: every rule field and group field referencing `key`."""
    hits = []
    if not isinstance(key, int):
        return hits
    for group in groups:
        if not isinstance(group, dict):
            continue
        for field in GROUP_REF_FIELDS:
            value = group.get(field)
            if isinstance(value, int) and value == key:
                hits.append({'group': group.get('name'), 'rule': None, 'field': field})
        for rule in ensure_rules_list(group):
            if rule is ignore_rule or not isinstance(rule, dict):
                continue
            for field in RULE_REF_FIELDS:
                value = rule.get(field)
                if isinstance(value, list) and key in value:
                    hits.append({'group': group.get('name'), 'rule': rule.get('name'), 'field': field})
                elif isinstance(value, int) and value == key:
                    hits.append({'group': group.get('name'), 'rule': rule.get('name'), 'field': field})
    return hits


def is_rule_key_referenced(groups, key, ignore_rule=None):
    return bool(referrers_for(groups, key, ignore_rule=ignore_rule))


def _reference_values(rule, field):
    value = rule.get(field)
    if isinstance(value, list):
        return [('list', i, v) for i, v in enumerate(value) if isinstance(v, int)]
    if isinstance(value, int):
        return [('scalar', None, value)]
    return []


def repair_scope_keys_and_references(groups, scope_label, events):
    """Ensure int rule keys are unique inside one scope (an app or
    globalGroups) and that every preKeys / actionCdKey / actionMaximumKey /
    group actionMaximumKey reference resolves to exactly one rule.

    Resolution happens BEFORE renumbering, by capturing the target rule
    object, so renumbering can never invalidate a reference. Lookup
    preference: own group (upstream convention) -> unique app-wide match ->
    deterministic first candidate (logged). Unresolvable (dangling) references
    are PRESERVED VERBATIM and logged -- silently dropping them would remove
    a gate and change the rule's trigger condition."""
    index = collect_rule_key_index(groups)
    max_key = -1
    for keys in index:
        if keys > max_key:
            max_key = keys

    kept_records = []
    pending_writes = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        holders = list(ensure_rules_list(group))
        for field in GROUP_REF_FIELDS:
            value = group.get(field)
            if isinstance(value, int):
                entries = [('scalar', None, value)]
                targets = [resolve_target(value, group, index, scope_label, group.get('name'), None, field,
                                          events, kept_records)]
                pending_writes.append((group, field, entries, targets))
        for rule in holders:
            if not isinstance(rule, dict):
                continue
            for field in RULE_REF_FIELDS:
                entries = _reference_values(rule, field)
                if not entries:
                    continue
                targets = [resolve_target(old, group, index, scope_label, group.get('name'), rule.get('name'), field,
                                          events, kept_records)
                            for _kind, _idx, old in entries]
                pending_writes.append((rule, field, entries, targets))

    seen = set()
    next_key = max_key + 1
    for group in groups:
        if not isinstance(group, dict):
            continue
        for rule in ensure_rules_list(group):
            if not isinstance(rule, dict):
                continue
            key = rule.get('key')
            if not isinstance(key, int):
                continue
            if key in seen:
                new_key = next_key
                next_key += 1
                rule['key'] = new_key
                events.append({
                    'type': 'duplicateKeyReassigned',
                    'scope': scope_label,
                    'group': group.get('name'),
                    'rule': rule.get('name'),
                    'oldKey': key,
                    'newKey': new_key,
                })
            else:
                seen.add(key)

    for holder, field, entries, targets in pending_writes:
        keys = []
        for target in targets:
            if target is _KEEP_DANGLING:
                keys.append(_KEEP_DANGLING)
            elif target is None:
                keys.append(None)
            else:
                tk = target.get('key')
                keys.append(tk if isinstance(tk, int) else None)
        original = holder.get(field)
        if isinstance(original, list):
            entry_positions = {idx: new for (_kind, idx, _old), new in zip(entries, keys)}
            rebuilt = []
            for pos, item in enumerate(original):
                if pos in entry_positions:
                    new_val = entry_positions[pos]
                    if new_val is _KEEP_DANGLING:
                        rebuilt.append(item)  # preserve unresolvable value verbatim
                    elif new_val is not None:
                        rebuilt.append(new_val)
                else:
                    rebuilt.append(item)
            if rebuilt:
                holder[field] = rebuilt
            else:
                holder.pop(field, None)
        elif isinstance(original, int):
            new_val = keys[0] if keys else None
            if new_val is _KEEP_DANGLING:
                pass  # preserve unresolvable value verbatim
            elif new_val is None:
                holder.pop(field, None)
            else:
                holder[field] = new_val

    # Re-audit preserved dangling values AFTER duplicate-key normalization:
    # a renumbered rule may now coincidentally carry the preserved value.
    # The value is never rewritten either way (trigger condition untouched);
    # the event and review entry state honestly what the output now means.
    if kept_records:
        final_index = collect_rule_key_index(groups)
        for rec in kept_records:
            final_cands = final_index.get(rec['oldKey'], [])
            if not final_cands:
                continue
            tg, tr = final_cands[0]
            same_group = tg is rec['holderGroup']
            rec['event']['resolvesAfterRenumbering'] = True
            rec['event']['resolvedTarget'] = {'group': tg.get('name'), 'rule': tr.get('name'),
                                              'targetRuleKey': tr.get('key'),
                                              'sameGroupAsReferrer': same_group}
            entry = rec['reviewEntry']
            entry['resolutionStatus'] = 'nowResolvesInOwnGroup' if same_group else 'nowResolvesCrossGroup'
            entry['reason'] = (
                'upstream dangling reference preserved verbatim; after duplicate-key normalization '
                'the value uniquely resolves to a rule in the referrer group -- gate semantics most '
                'likely restored as upstream intended'
                if same_group else
                'upstream dangling reference preserved verbatim; after duplicate-key normalization '
                'the value uniquely resolves, but to a rule in ANOTHER group -- whether that matches '
                'the upstream gate is unverifiable; value retained as-is, manual review required'
            )
    return seen


def resolve_target(old_key, holder_group, index, scope_label, group_name, rule_name, field, events,
                   kept_recorder=None):
    cands = index.get(old_key, [])
    if not cands:
        # Never drop a dangling reference: removing a gate would UNLOCK rules
        # that upstream (probably) never fired. Preserve the original value
        # byte-for-byte and file a review item so the change is auditable.
        event = {'type': 'keptDanglingReference', 'scope': scope_label, 'group': group_name,
                 'rule': rule_name, 'field': field, 'referencedKey': old_key}
        events.append(event)
        entry = {
            'app': scope_label,
            'groupA': group_name,
            'groupB': group_name,
            'rule': rule_name,
            'ruleA': rule_name,
            'ruleB': rule_name,
            'key': None,
            'matches': None,
            'contextDiff': [],
            'behaviorDiff': [],
            'referrers': [{'group': group_name, 'rule': rule_name, 'field': field}],
            'category': 'upstream_invalid_reference',
            'reason': 'upstream reference to a missing rule key preserved unchanged (dropping it would open the rule gate)',
            'field': field,
            'referencedKey': old_key,
        }
        DUPLICATE_REPORT['review'].append(entry)
        if kept_recorder is not None:
            kept_recorder.append({'event': event, 'reviewEntry': entry, 'oldKey': old_key,
                                  'holderGroup': holder_group})
        return _KEEP_DANGLING
    own = [rule for g, rule in cands if g is holder_group]
    if own:
        if len(own) > 1:
            events.append({'type': 'ambiguousReferenceResolvedToFirst', 'scope': scope_label,
                           'group': group_name, 'rule': rule_name, 'field': field,
                           'referencedKey': old_key, 'candidatesInGroup': len(own)})
        return own[0]
    if len(cands) == 1:
        return cands[0][1]
    events.append({'type': 'ambiguousCrossGroupReferenceResolvedToFirst', 'scope': scope_label,
                   'group': group_name, 'rule': rule_name, 'field': field, 'referencedKey': old_key,
                   'candidateGroups': [g.get('name') for g, _r in cands][:MAX_REVIEW_REFERRERS]})
    return cands[0][1]


def rewrite_scope_references(groups, mapping):
    """After safe duplicate removals: re-point every APP-wide reference at the
    kept key (rule fields + group-level actionMaximumKey)."""
    if not mapping:
        return
    for group in groups:
        if not isinstance(group, dict):
            continue
        for field in GROUP_REF_FIELDS:
            value = group.get(field)
            if isinstance(value, int) and value in mapping:
                group[field] = mapping[value]
        for rule in ensure_rules_list(group):
            if not isinstance(rule, dict):
                continue
            for field in RULE_REF_FIELDS:
                value = rule.get(field)
                if isinstance(value, list):
                    rule[field] = [mapping.get(k, k) for k in value]
                elif isinstance(value, int):
                    rule[field] = mapping.get(value, value)


# ---------------------------------------------------------------------------
# Review classification
# ---------------------------------------------------------------------------

def review_category(aid, group_a, group_b, blocked, behavior_diff):
    if group_a.get('enable') is False or group_b.get('enable') is False:
        return 'enable_disabled_group'
    if blocked == 'kept_dangling_reference':
        return 'upstream_invalid_reference'
    if blocked in ('dependency_references', 'preKeys'):
        if (aid, group_a.get('name')) in REPAIR_SUSPECT_GROUPS or (aid, group_b.get('name')) in REPAIR_SUSPECT_GROUPS:
            return 'upstream_invalid_reference'
        return 'dependency_difference'
    if 'activityIds' in behavior_diff:
        if has_unprovable_activity(group_a) or has_unprovable_activity(group_b):
            return 'ambiguous_activity'
        return 'behavior_difference'
    if behavior_diff:
        return 'behavior_difference'
    return 'uncertain_equivalence'


# ---------------------------------------------------------------------------
# Duplicate removal
# ---------------------------------------------------------------------------

def dedupe_cross_group_rules(app):
    """Remove only behavior-safe duplicates across/within groups of one app.

    Safety gates (ALL must hold for removal):
      - identical behavior-only group context (display fields excluded;
        enable / activityIds / resetMatch / matchTime / matchDelay / matchRoot
        / fastQuery / actionMaximum / actionMaximumKey are behavior fields and
        any difference blocks removal);
      - equal behavioral rule fingerprint (name, matches, action and all
        runtime fields identical; evidence fields excluded, activityIds
        notation normalized for comparison only);
      - neither copy carries preKeys and neither copy's key is referenced
        APP-WIDE by preKeys / actionCdKey / actionMaximumKey / group
        actionMaximumKey;
      - NEITHER group is enable:false: disabled groups are never touched,
        because a user who manually re-enabled one would silently lose
        behavior (unverifiable from subscription data).
      - NEITHER copy holds an upstream dangling reference (a rule-key int in
        preKeys / actionCdKey / actionMaximumKey that resolves to no rule):
        such values were preserved verbatim and audited; removing a holder
        would make the audit lie about the output.
    Removals merge evidence URLs into the kept copy and re-point references
    APP-WIDE through the removed->kept key map.
    """
    aid = app.get('id')
    groups = app.get('groups') or []

    key_index = collect_rule_key_index(groups)

    def holds_dangling_reference(rule):
        if not isinstance(rule, dict):
            return False
        for field in RULE_REF_FIELDS:
            value = rule.get(field)
            refs = [x for x in value if isinstance(x, int)] if isinstance(value, list) \
                else ([value] if isinstance(value, int) else [])
            for k in refs:
                if not key_index.get(k):
                    return True
        return False

    seen = {}       # (behavior_ctx, fp) -> (group, rule, strict_ctx, legacy_fp)
    seen_any = {}   # fp -> (group, rule)
    app_mapping = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        rules = ensure_rules_list(group)
        bctx = group_behavior_context(group, aid)
        strict_ctx = group_context_fingerprint(group, aid)
        group_disabled = group.get('enable') is False
        kept = []
        for rule in rules:
            fp = fingerprint(rule, aid)
            legacy = legacy_fingerprint(rule)
            key = rule.get('key') if isinstance(rule, dict) else None
            candidate = seen.get((bctx, fp))
            any_candidate = seen_any.get(fp)
            if candidate and isinstance(rule, dict):
                existing_group, existing_rule, existing_strict, existing_legacy = candidate
                existing_disabled = existing_group.get('enable') is False
                key_is_referenced = is_rule_key_referenced(groups, key, ignore_rule=rule)
                existing_key_is_referenced = is_rule_key_referenced(groups, existing_rule.get('key'), ignore_rule=existing_rule)
                blocked = None
                if key_is_referenced or existing_key_is_referenced:
                    blocked = 'dependency_references'
                elif has_prekeys(rule) or has_prekeys(existing_rule):
                    blocked = 'preKeys'
                elif group_disabled or existing_disabled:
                    blocked = 'disabled_guard'
                elif holds_dangling_reference(rule) or holds_dangling_reference(existing_rule):
                    blocked = 'kept_dangling_reference'
                if blocked is None:
                    if isinstance(key, int) and isinstance(existing_rule.get('key'), int):
                        app_mapping[key] = existing_rule['key']
                    evidence_merged = merge_evidence(existing_rule, rule)
                    if legacy == existing_legacy:
                        enabled_by = 'exact'
                    elif evidence_free_fingerprint(rule) == evidence_free_fingerprint(existing_rule):
                        enabled_by = 'evidenceFieldsOnly'
                    else:
                        enabled_by = 'activityIdsNormalization'
                    if strict_ctx != existing_strict:
                        STATS['groupDisplayContextDedupe'] += 1
                        if enabled_by == 'exact':
                            enabled_by = 'groupDisplayContextOnly'
                    STATS[f'removalEnabledBy:{enabled_by}'] += 1
                    DUPLICATE_REPORT['safeRemoved'].append({
                        'app': aid,
                        'removedGroup': group.get('name'),
                        'keptGroup': existing_group.get('name'),
                        'rule': rule.get('name'),
                        'ruleA': existing_rule.get('name'),
                        'ruleB': rule.get('name'),
                        'matches': rule.get('matches'),
                        'removedRuleKey': key,
                        'keptRuleKey': existing_rule.get('key'),
                        'enabledBy': enabled_by,
                        'evidenceMerged': evidence_merged,
                    })
                    continue
                bdiff = behavior_diff_fields(existing_group, group, aid)
                DUPLICATE_REPORT['review'].append({
                    'app': aid,
                    'groupA': existing_group.get('name'),
                    'groupB': group.get('name'),
                    'rule': rule.get('name'),
                    'ruleA': existing_rule.get('name'),
                    'ruleB': rule.get('name'),
                    'key': key,
                    'keptRuleKey': existing_rule.get('key'),
                    'candidateRuleKey': key,
                    'matches': rule.get('matches'),
                    'contextDiff': context_diff_fields(existing_group, group),
                    'behaviorDiff': bdiff,
                    'referrers': (
                        referrers_for(groups, key, ignore_rule=rule)
                        + referrers_for(groups, existing_rule.get('key'), ignore_rule=existing_rule)
                    )[:MAX_REVIEW_REFERRERS],
                    'category': review_category(aid, existing_group, group, blocked, bdiff),
                    'reason': (
                        'duplicate rule has key dependency references' if blocked == 'dependency_references'
                        else 'duplicate rule requires review because preKeys are involved' if blocked == 'preKeys'
                        else 'duplicate rule retained because it holds a preserved upstream dangling reference'
                        if blocked == 'kept_dangling_reference'
                        else 'duplicate rule retained because a group is enable:false (manual-enable semantics unverifiable)'
                    ),
                })
            else:
                if any_candidate and isinstance(rule, dict):
                    existing_group, existing_rule = any_candidate
                    bdiff = behavior_diff_fields(existing_group, group, aid)
                    DUPLICATE_REPORT['review'].append({
                        'app': aid,
                        'groupA': existing_group.get('name'),
                        'groupB': group.get('name'),
                        'rule': rule.get('name'),
                        'ruleA': existing_rule.get('name'),
                        'ruleB': rule.get('name'),
                        'key': key,
                        'keptRuleKey': existing_rule.get('key'),
                        'candidateRuleKey': key,
                        'matches': rule.get('matches'),
                        'contextDiff': context_diff_fields(existing_group, group),
                        'behaviorDiff': bdiff,
                        'referrers': referrers_for(groups, key, ignore_rule=rule)[:MAX_REVIEW_REFERRERS],
                        'category': review_category(aid, existing_group, group, None, bdiff),
                        'reason': 'duplicate rule retained because behavior-relevant group settings differ',
                    })
                seen[(bctx, fp)] = (group, rule, strict_ctx, legacy)
                seen_any.setdefault(fp, (group, rule))
            kept.append(rule)
        group['rules'] = kept
    rewrite_scope_references(groups, app_mapping)


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------

def remap_rules(dst_rules, src_rules, *, app_id=None, group_name=None):
    """Merge rules of a same-name group.

    Duplicate detection uses the behavioral fingerprint; a dropped src copy has
    its evidence URLs merged into the kept rule and its old key aliased.
    A src rule is dropped only when its preKeys gate is PROVABLY equivalent
    to the kept copy's gate: the integers are resolved to their target rule
    objects within each side's own rule list (upstream same-group convention)
    and the targets' behavioral fingerprints must match. Raw integer equality
    alone is never accepted (forks reuse numbers for different rules), and an
    unresolvable / multiply-resolvable target keeps the rule with a review
    item. Nothing is ever silently discarded."""
    dst_rules = dst_rules if isinstance(dst_rules, list) else []
    used = {r.get('key') for r in dst_rules if isinstance(r, dict) and isinstance(r.get('key'), int)}
    existing_by_fp = {fingerprint(r, app_id): r for r in dst_rules if isinstance(r, dict)}
    next_key = max(used, default=-1) + 1
    mapping = {}
    pending = []

    def _gate_keys(rule):
        """Normalized int gate of a rule; None marks an uninterpretable value."""
        v = rule.get('preKeys')
        if v is None:
            return []
        if isinstance(v, int):
            return [v]
        if isinstance(v, list):
            ints = [k for k in v if isinstance(k, int)]
            if len(ints) != len([k for k in v if k is not None]):
                return None  # non-int entries: cannot resolve
            return ints
        return None

    def _resolve_gate(rule_keys, key_list):
        """Resolve each gate int to its target rule object inside key_list.

        Returns a list of behavioral fingerprints, or None if any key has
        zero or multiple matches (unprovable semantics)."""
        index = defaultdict(list)
        for rr in key_list:
            if isinstance(rr, dict) and isinstance(rr.get('key'), int):
                index[rr['key']].append(rr)
        cores = []
        for k in sorted(set(rule_keys)):
            hits = index.get(k, [])
            if len(hits) != 1:
                return None
            cores.append(fingerprint(hits[0], app_id))
        return cores

    def gates_equivalent(r, kept_rule):
        """True / False / None(unverifiable) for preKeys gate semantics."""
        rk, kk = _gate_keys(r), _gate_keys(kept_rule)
        if rk is None or kk is None:
            return None
        if not rk and not kk:
            return True
        r_t = _resolve_gate(rk, src_rules)
        if r_t is None:
            return None
        if not kk:
            return False
        k_t = _resolve_gate(kk, dst_rules)
        if k_t is None:
            return None
        return sorted(r_t) == sorted(k_t)

    for r in src_rules:
        if not isinstance(r, dict):
            continue
        old = r.get('key')
        fp = fingerprint(r, app_id)
        kept_rule = existing_by_fp.get(fp)
        gate_state = gates_equivalent(r, kept_rule) if kept_rule is not None else None
        if kept_rule is not None and gate_state is not True:
            nr = dict(r)
            nr['key'] = next_key
            used.add(nr['key'])
            next_key += 1
            if isinstance(old, int):
                mapping[old] = nr['key']
            pending.append(nr)
            existing_by_fp[fp] = nr  # later copies now compare against this one
            DUPLICATE_REPORT['review'].append({
                'app': app_id,
                'groupA': group_name,
                'groupB': group_name,
                'rule': r.get('name'),
                'ruleA': kept_rule.get('name'),
                'ruleB': r.get('name'),
                'key': old,
                'keptRuleKey': kept_rule.get('key'),
                'candidateRuleKey': old,
                'rPreKeys': r.get('preKeys'),
                'keptPreKeys': kept_rule.get('preKeys'),
                'matches': r.get('matches'),
                'contextDiff': [],
                'behaviorDiff': [],
                'referrers': [],
                'category': 'dependency_difference',
                'reason': (
                    'duplicate rule retained because preKeys diverge from kept copy (same group merge)'
                    if gate_state is False else
                    'duplicate rule retained because preKeys gate could not be resolved uniquely (same group merge)'
                ),
            })
            STATS['remapPreKeysGuard' if gate_state is False else 'remapPreKeysUnverifiable'] += 1
            continue
        if kept_rule is not None:
            if isinstance(old, int) and isinstance(kept_rule.get('key'), int):
                mapping[old] = kept_rule.get('key')
            if merge_evidence(kept_rule, r):
                STATS['remapEvidenceMerged'] += 1
            if legacy_fingerprint(r) != legacy_fingerprint(kept_rule):
                STATS['remapDisplayDedupe'] += 1
            STATS['remapDuplicateSkipped'] += 1
            continue
        nr = dict(r)
        if isinstance(old, int):
            while next_key in used:
                next_key += 1
            mapping[old] = nr['key']
            nr['key'] = next_key
            used.add(next_key)
            next_key += 1
        pending.append(nr)
        existing_by_fp[fp] = nr

    for nr in pending:
        for field in RULE_REF_FIELDS:
            value = nr.get(field)
            if isinstance(value, list):
                nr[field] = [mapping.get(k, k) for k in value]
            elif isinstance(value, int):
                nr[field] = mapping.get(value, value)
        dst_rules.append(nr)
    return dst_rules, mapping


def merge_groups(dst_groups, src_groups, app_id=None):
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
            _, alias = remap_rules(dg['rules'], normalize_list(sg.get('rules')),
                                   app_id=app_id, group_name=name)
            for k, v in sg.items():
                if k not in dg and k != 'rules':
                    if k in GROUP_REF_FIELDS and isinstance(v, int):
                        dg[k] = alias.get(v, v)
                    else:
                        dg[k] = v
            continue
        ng = dict(sg)
        if isinstance(ng.get('key'), int):
            while next_key in used_keys:
                next_key += 1
            ng['key'] = next_key
            used_keys.add(next_key)
            next_key += 1
        # Rule keys are copied verbatim; repair_scope_keys_and_references later
        # makes them unique per app and fixes every reference by object identity.
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
            _, alias = remap_rules(dg['rules'], normalize_list(sg.get('rules')),
                                   app_id='globalGroups', group_name=name)
            for k, v in sg.items():
                if k not in dg and k != 'rules':
                    if k in GROUP_REF_FIELDS and isinstance(v, int):
                        dg[k] = alias.get(v, v)
                    else:
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


# ---------------------------------------------------------------------------
# Disabled-group audit (report only; NEVER auto-removed)
# ---------------------------------------------------------------------------

def audit_disabled_groups(app):
    aid = app.get('id')
    groups = app.get('groups') or []
    enabled_fp_to_group = {}
    for g in groups:
        if not isinstance(g, dict) or g.get('enable') is False:
            continue
        for r in ensure_rules_list(g):
            if isinstance(r, dict):
                enabled_fp_to_group.setdefault(fingerprint(r, aid), g.get('name'))
    for g in groups:
        if not isinstance(g, dict) or g.get('enable') is not False:
            continue
        rules = [r for r in ensure_rules_list(g) if isinstance(r, dict)]
        if not rules:
            continue
        covered_by = set()
        fully_covered = True
        for r in rules:
            src_group = enabled_fp_to_group.get(fingerprint(r, aid))
            if src_group is None:
                fully_covered = False
            else:
                covered_by.add(src_group)
        has_dependency = any(is_rule_key_referenced(groups, r.get('key'), ignore_rule=r) for r in rules)
        if fully_covered and not has_dependency:
            DUPLICATE_REPORT['disabledGroupAudit'].append({
                'app': aid,
                'group': g.get('name'),
                'groupKey': g.get('key'),
                'ruleCount': len(rules),
                'coveredBy': sorted(covered_by),
                'hasDependency': False,
                'userManualEnableRisk': (
                    'unverifiable: GKD persists per-group enable state; a user who manually '
                    'enabled this disabled group would lose behavior if it were removed'
                ),
                'action': 'retained-review-only',
            })
            STATS['disabledGroupCovered'] += 1


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_subscription(apps, global_groups, audited_dangling=None):
    """Post-build invariants:
       - rule keys unique per app / globalGroups; group keys unique per scope
       - every preKeys / actionCdKey / actionMaximumKey / group
         actionMaximumKey resolves to exactly one rule -- EXCEPT dangling
         references that were deliberately preserved verbatim upstream
         (audited_dangling: multiset of (scope, group, rule, field, key)
         filled from keptDanglingReference repair events). Each preserved
         reference must match exactly one audited entry; any OTHER dangling
         reference, or any audited entry that vanished from the output
         (e.g. removed by dedup), is an issue.
       - no ambiguity -> no dependency breakage from dedup
       - merged evidence lists contain no duplicate URLs"""
    audited = defaultdict(int)
    for sig, n in (audited_dangling or {}).items():
        audited[sig] += n
    consumed = defaultdict(int)

    def _consume(scope_label, group_name, rule_name, field, key):
        sig = (scope_label, group_name, rule_name, field, key)
        if audited.get(sig, 0) > consumed[sig]:
            consumed[sig] += 1
            return True
        return False

    issues = []
    scopes = [(a.get('id'), a.get('groups') or []) for a in apps]
    scopes.append(('globalGroups', global_groups))
    for scope_label, groups in scopes:
        gk = defaultdict(int)
        for g in groups:
            if isinstance(g, dict) and isinstance(g.get('key'), int):
                gk[g['key']] += 1
        for k, n in gk.items():
            if n > 1:
                issues.append({'scope': scope_label, 'type': 'duplicateGroupKey', 'key': k, 'count': n})
        index = collect_rule_key_index(groups)
        for k, holders in index.items():
            if len(holders) > 1:
                issues.append({'scope': scope_label, 'type': 'duplicateRuleKey', 'key': k,
                               'count': len(holders), 'groups': [g.get('name') for g, _r in holders][:5]})
        for group in groups:
            if not isinstance(group, dict):
                continue
            for field in GROUP_REF_FIELDS:
                v = group.get(field)
                if isinstance(v, int):
                    n = len(index.get(v, []))
                    if n == 0:
                        if not _consume(scope_label, group.get('name'), None, field, v):
                            issues.append({'scope': scope_label, 'type': 'danglingReference',
                                           'group': group.get('name'), 'rule': None, 'field': field, 'key': v})
                    elif n > 1:
                        issues.append({'scope': scope_label, 'type': 'ambiguousReference',
                                       'group': group.get('name'), 'rule': None, 'field': field, 'key': v, 'count': n})
            for rule in ensure_rules_list(group):
                if not isinstance(rule, dict):
                    continue
                for field in RULE_REF_FIELDS:
                    value = rule.get(field)
                    keys = [x for x in value if isinstance(x, int)] if isinstance(value, list) \
                        else ([value] if isinstance(value, int) else [])
                    for k in keys:
                        n = len(index.get(k, []))
                        if n == 0:
                            if not _consume(scope_label, group.get('name'), rule.get('name'), field, k):
                                issues.append({'scope': scope_label, 'type': 'danglingReference',
                                               'group': group.get('name'), 'rule': rule.get('name'),
                                               'field': field, 'key': k})
                        elif n > 1:
                            issues.append({'scope': scope_label, 'type': 'ambiguousReference',
                                           'group': group.get('name'), 'rule': rule.get('name'),
                                           'field': field, 'key': k, 'count': n})
                for fld in RULE_EVIDENCE_FIELDS:
                    v = rule.get(fld)
                    if isinstance(v, list) and len(v) != len(set(v)):
                        issues.append({'scope': scope_label, 'type': 'duplicateEvidenceUrl',
                                       'group': group.get('name'), 'rule': rule.get('name'), 'field': fld})
    # Audited dangling references that are expected in the output but no
    # longer present (e.g. a holder rule was removed) -> report honestly.
    for sig, n in audited.items():
        missing = n - consumed.get(sig, 0)
        if missing > 0:
            issues.append({'scope': sig[0], 'type': 'auditedDanglingReferenceLost',
                           'group': sig[1], 'rule': sig[2], 'field': sig[3], 'key': sig[4],
                           'count': missing})
    return issues


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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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
            merge_groups(apps_by_id[aid].setdefault('groups', []), a.get('groups'), app_id=aid)

for a in apps:
    a['groups'] = sorted(a.get('groups', []), key=lambda g: (g.get('key', 10**9), g.get('name', '')))
apps.sort(key=lambda a: a.get('id', ''))
result['globalGroups'] = sorted(result['globalGroups'], key=lambda g: (g.get('key', 10**9), g.get('name', '')))

# Display-only evidence URL cleanup (safe: dedup within a rule's own list only).
for a in apps:
    normalize_evidence_lists(a.get('groups') or [])
normalize_evidence_lists(result['globalGroups'])

# Phase 1: unique rule keys per app; references resolved to objects BEFORE
# renumbering so dedup decisions see unambiguous keys.
repair_events = []
for a in apps:
    repair_scope_keys_and_references(a.get('groups') or [], a.get('id'), repair_events)
repair_scope_keys_and_references(result['globalGroups'], 'globalGroups', repair_events)
for e in repair_events:
    if e['type'] in ('keptDanglingReference', 'ambiguousReferenceResolvedToFirst',
                     'ambiguousCrossGroupReferenceResolvedToFirst'):
        REPAIR_SUSPECT_GROUPS.add((e['scope'], e['group']))

# Dangling references deliberately preserved verbatim: exact multiset of
# (scope, group, rule, field, key) so validation can require them to still be
# present in the output (and nothing else may dangle). References whose
# preserved value became uniquely resolvable after key normalization are
# annotated and counted separately -- no longer dangling, never rewritten.
audited_dangling = defaultdict(int)
dangling_resolved_after_norm = 0
for e in repair_events:
    if e['type'] == 'keptDanglingReference':
        if e.get('resolvesAfterRenumbering'):
            dangling_resolved_after_norm += 1
        else:
            audited_dangling[(e['scope'], e['group'], e['rule'], e['field'], e['referencedKey'])] += 1

# Phase 2: behavior-safe duplicate removal (see dedupe docstring for gates).
for app in apps:
    dedupe_cross_group_rules(app)

# Disabled groups: audit only, never removed automatically.
for app in apps:
    audit_disabled_groups(app)

result['apps'] = apps

validation_issues = validate_subscription(apps, result['globalGroups'], audited_dangling)

global_rule_groups = len(result.get('globalGroups', []))
app_rule_groups = sum(
    len(a.get('groups', []))
    for a in result.get('apps', [])
    if isinstance(a, dict)
)
global_rule_objects = sum(
    len(ensure_rules_list(g))
    for g in result.get('globalGroups', [])
    if isinstance(g, dict)
)
app_rule_objects = sum(
    len(ensure_rules_list(g))
    for a in result.get('apps', [])
    if isinstance(a, dict)
    for g in a.get('groups', [])
    if isinstance(g, dict)
)
rule_objects = global_rule_objects + app_rule_objects

content_hash = canonical_hash({k: v for k, v in result.items() if k not in {'version', 'checkUpdateUrl'}})
version, meta = next_version(content_hash)
result['version'] = version

repair_counts = defaultdict(int)
for e in repair_events:
    repair_counts[e['type']] += 1

review_by_category = {}
for item in DUPLICATE_REPORT['review']:
    c = item.get('category', 'other')
    review_by_category[c] = review_by_category.get(c, 0) + 1
review_by_reason = {}
for item in DUPLICATE_REPORT['review']:
    reason = item.get('reason', 'unknown')
    review_by_reason[reason] = review_by_reason.get(reason, 0) + 1

removed_by = {}
for item in DUPLICATE_REPORT['safeRemoved']:
    e = item.get('enabledBy', 'unknown')
    removed_by[e] = removed_by.get(e, 0) + 1

disabled_group_count = sum(
    1 for a in apps for g in a.get('groups', [])
    if isinstance(g, dict) and g.get('enable') is False
)

optimization = {
    'remapDuplicateSkipped': STATS['remapDuplicateSkipped'],
    'remapEvidenceMerged': STATS['remapEvidenceMerged'],
    'remapDisplayDedupe': STATS['remapDisplayDedupe'],
    'remapPreKeysGuard': STATS['remapPreKeysGuard'],
    'remapPreKeysUnverifiable': STATS['remapPreKeysUnverifiable'],
    'danglingReferencesPreserved': sum(audited_dangling.values()),
    'danglingReferencesResolvedAfterRenumbering': dangling_resolved_after_norm,
    'safeRemovedTotal': len(DUPLICATE_REPORT['safeRemoved']),
    'safeRemovedEnabledBy': removed_by,
    'snapshotExampleOnlyRemovals': removed_by.get('evidenceFieldsOnly', 0) + STATS['remapEvidenceMerged'],
    'activityIdsNormalizationRemovals': removed_by.get('activityIdsNormalization', 0),
    'groupDisplayContextDedupe': STATS['groupDisplayContextDedupe'],
    'upstreamEvidenceUrlDedup': STATS['upstreamEvidenceUrlDedup'],
    'disabledGroupsRetained': disabled_group_count,
    'disabledGroupsFullyCoveredRetirementCandidates': len(DUPLICATE_REPORT['disabledGroupAudit']),
    'disabledGroupsAutoRetired': 0,
}

merge_status = {
    'ok': not validation_issues,
    'time': int(time.time()),
    'version': version,
    'contentHash': content_hash,
    'sources': STATUS,
    'apps': len(apps),
    'globalGroups': global_rule_groups,
    'appRuleGroups': app_rule_groups,
    'gkdDisplayedRuleCount': app_rule_groups,
    'globalRuleObjects': global_rule_objects,
    'appRuleObjects': app_rule_objects,
    'ruleObjects': rule_objects,
    'safeDuplicateRemovals': len(DUPLICATE_REPORT['safeRemoved']),
    'duplicateReviewItems': len(DUPLICATE_REPORT['review']),
    'duplicateReviewCategories': review_by_category,
    'duplicateReviewBreakdown': review_by_reason,
    'referenceRepairs': dict(repair_counts),
    'optimization': optimization,
    'validation': {
        'ok': not validation_issues,
        'issueCount': len(validation_issues),
        'issues': validation_issues[:50],
    },
}

repairs_by_type = defaultdict(list)
for e in repair_events:
    repairs_by_type[e['type']].append(e)

(OUT / 'duplicate-report.json').write_text(json.dumps({
    'safeRemovedCount': len(DUPLICATE_REPORT['safeRemoved']),
    'reviewCount': len(DUPLICATE_REPORT['review']),
    'reviewBreakdown': review_by_reason,
    'reviewCategories': review_by_category,
    'referenceRepairCounts': dict(repair_counts),
    'optimization': optimization,
    'safeRemoved': DUPLICATE_REPORT['safeRemoved'],
    'review': DUPLICATE_REPORT['review'],
    'referenceRepairsByType': dict(repairs_by_type),
    'referenceRepairsTotal': len(repair_events),
    'disabledGroupAudit': DUPLICATE_REPORT['disabledGroupAudit'],
}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(OUT / 'merge-status.json').write_text(json.dumps(merge_status, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

if validation_issues:
    print(f"VALIDATION FAILED: {len(validation_issues)} reference/key issues remain; gkd.json5 NOT updated.")
    for issue in validation_issues[:20]:
        print(json.dumps(issue, ensure_ascii=False))
    raise SystemExit(2)

(OUT / 'gkd.json5').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(OUT / 'gkd.version.json5').write_text(json.dumps({'version': version}) + '\n', encoding='utf-8')
meta['sourceVersions'] = {s['id']: d.get('version') for s, d in loaded}
(OUT / 'version-state.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(f"Generated {OUT/'gkd.json5'}: version {version}, {len(apps)} apps, {app_rule_groups} app rule groups, "
      f"{rule_objects} rule objects; safeRemoved={len(DUPLICATE_REPORT['safeRemoved'])}, "
      f"review={len(DUPLICATE_REPORT['review'])}, repairs={len(repair_events)}, validation ok")
