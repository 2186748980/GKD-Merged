import json
import time
import urllib.request
from pathlib import Path

SOURCES = [
    {"id": "linarm", "name": "Lin-arm", "priority": 100, "url": "https://raw.githubusercontent.com/Lin-arm/GKD_subscription/main/dist/gkd.json5"},
    {"id": "ganlinte", "name": "ganlinte", "priority": 90, "url": "https://raw.githubusercontent.com/ganlinte/GKD-subscription/main/dist/ganlin_gkd.json5"},
    {"id": "aisouler", "name": "AIsouler（历史）", "priority": 50, "url": "https://raw.githubusercontent.com/q595002599/AIsouler_GKD_subscription/main/dist/AIsouler_gkd.json5"},
    {"id": "adpro", "name": "Adpro（历史）", "priority": 40, "url": "https://raw.githubusercontent.com/Adpro-Team/GKD_subscription/main/dist/Adpro_gkd.json5"},
]
CACHE = Path('cache/sources'); OUT = Path('gkd')
CACHE.mkdir(parents=True, exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
import json5
STATUS = []

def load_source(src):
    cache = CACHE / f"{src['id']}.json5"
    try:
        req = urllib.request.Request(src['url'], headers={'User-Agent': 'GKD-Merged/2.0'})
        with urllib.request.urlopen(req, timeout=60) as r: data = r.read()
        cache.write_bytes(data)
        STATUS.append({'id':src['id'],'name':src['name'],'download':'ok','bytes':len(data)})
    except Exception as e:
        if not cache.exists():
            STATUS.append({'id':src['id'],'name':src['name'],'download':'failed','error':repr(e)}); return None
        STATUS.append({'id':src['id'],'name':src['name'],'download':'cache','error':repr(e)})
    try:
        d=json5.loads(cache.read_text(encoding='utf-8'))
        if not isinstance(d,dict): raise TypeError(f'root is {type(d).__name__}')
        STATUS[-1]['parse']='ok'; STATUS[-1]['sourceVersion']=d.get('version'); return d
    except Exception as e:
        STATUS[-1]['parse']='failed'; STATUS[-1]['parseError']=repr(e); return None

def norm(v): return [] if v is None else (v if isinstance(v,list) else [v])
def ensure_rules(g):
    r=g.get('rules'); g['rules']=[] if r is None else ([r] if isinstance(r,dict) else (r if isinstance(r,list) else [])); return g['rules']
def fp(o):
    if not isinstance(o,dict): return json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return json.dumps({k:v for k,v in o.items() if k not in {'key','preKeys'}},ensure_ascii=False,sort_keys=True,separators=(',',':'))
def append_rules(dst, src):
    used={r.get('key') for r in dst if isinstance(r,dict) and isinstance(r.get('key'),int)}
    existing={fp(r):r.get('key') for r in dst}; nk=max(used,default=-1)+1; mapping={}
    for r in src:
        if not isinstance(r,dict): continue
        f=fp(r); old=r.get('key')
        if f in existing:
            if isinstance(old,int): mapping[old]=existing[f]
            continue
        nr=dict(r)
        if isinstance(old,int):
            while nk in used: nk+=1
            mapping[old]=nk; nr['key']=nk; used.add(nk); nk+=1
        if isinstance(nr.get('preKeys'),list): nr['preKeys']=[mapping.get(k,k) for k in nr['preKeys']]
        elif isinstance(nr.get('preKeys'),int): nr['preKeys']=mapping.get(nr['preKeys'],nr['preKeys'])
        dst.append(nr); existing[f]=nr.get('key')

def merge_groups(dst, src):
    by={g.get('name'):g for g in dst if isinstance(g,dict) and g.get('name') is not None}
    used={g.get('key') for g in dst if isinstance(g,dict) and isinstance(g.get('key'),int)}; nk=max(used,default=-1)+1
    for sg in norm(src):
        if not isinstance(sg,dict): continue
        name=sg.get('name')
        if name in by:
            dg=by[name]; ensure_rules(dg); append_rules(dg['rules'],norm(sg.get('rules')))
            for k,v in sg.items():
                if k not in dg and k!='rules': dg[k]=v
            continue
        ng=dict(sg)
        if isinstance(ng.get('key'),int):
            while nk in used: nk+=1
            ng['key']=nk; used.add(nk); nk+=1
        ng['rules']=[dict(r) for r in norm(ng.get('rules')) if isinstance(r,dict)]
        dst.append(ng)
        if name is not None: by[name]=ng

def merge_global(dst,src): merge_groups(dst,src)

loaded=[]
for s in SOURCES:
    d=load_source(s)
    if isinstance(d,dict): loaded.append((s,d))
if not loaded:
    (OUT/'merge-status.json').write_text(json.dumps({'ok':False,'time':int(time.time()),'sources':STATUS},ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); raise SystemExit(0)

result={'id':2186748980,'name':'GKD-Merged 综合订阅','version':int(time.time()),'author':'2186748980 + upstream contributors','description':'自动整合 Lin-arm、ganlinte、AIsouler、Adpro；高优先级来源优先，低优先级来源补充缺失规则。','checkUpdateUrl':'./gkd.version.json5','supportUri':'https://github.com/2186748980/GKD-Merged'}
cats=[]; cn=set()
for _,d in loaded:
    for c in norm(d.get('categories')):
        if isinstance(c,dict) and c.get('name') not in cn: cats.append(dict(c)); cn.add(c.get('name'))
result['categories']=cats; result['globalGroups']=[]
for _,d in loaded: merge_global(result['globalGroups'],d.get('globalGroups'))
apps_by={}; apps=[]
for _,d in loaded:
    for a in norm(d.get('apps')):
        if not isinstance(a,dict) or not a.get('id'): continue
        aid=a['id']
        if aid not in apps_by:
            na=dict(a); na['groups']=[dict(g) for g in norm(a.get('groups')) if isinstance(g,dict)]
            for g in na['groups']: ensure_rules(g)
            apps_by[aid]=na; apps.append(na)
        else: merge_groups(apps_by[aid].setdefault('groups',[]),a.get('groups'))
for a in apps: a['groups']=sorted(a.get('groups',[]),key=lambda g:(g.get('key',10**9),g.get('name','')))
apps.sort(key=lambda a:a.get('id','')); result['apps']=apps
(OUT/'gkd.json5').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(OUT/'gkd.version.json5').write_text(json.dumps({'version':result['version']})+'\n',encoding='utf-8')
(OUT/'merge-status.json').write_text(json.dumps({'ok':True,'time':int(time.time()),'sources':STATUS,'apps':len(apps),'globalGroups':len(result['globalGroups'])},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f"Generated {OUT/'gkd.json5'}: {len(apps)} apps, {len(result['globalGroups'])} global groups")
