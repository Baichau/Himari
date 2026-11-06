import json, os, copy, sys
from pathlib import Path
APP_DIR=Path(os.environ.get("HIMARI_HOME", Path.home()/".himari"))
CFG=APP_DIR/"config.json"
RESOURCE_DIR=Path(getattr(sys,"_MEIPASS",Path(__file__).parent.parent))
DEFAULT=json.loads((RESOURCE_DIR/"config.example.json").read_text(encoding="utf-8"))
def _merge(base, override):
    for k,v in override.items():
        if isinstance(v,dict) and isinstance(base.get(k),dict): _merge(base[k],v)
        else: base[k]=v
    return base
def load():
    APP_DIR.mkdir(parents=True,exist_ok=True)
    if not CFG.exists(): CFG.write_text(json.dumps(DEFAULT,indent=2),encoding="utf-8")
    try: user=json.loads(CFG.read_text(encoding="utf-8"))
    except Exception: user={}
    return _merge(copy.deepcopy(DEFAULT),user)
def save(cfg):
    APP_DIR.mkdir(parents=True,exist_ok=True)
    CFG.write_text(json.dumps(cfg,indent=2),encoding="utf-8")
def get(*keys, default=None):
    c=load()
    for k in keys:
        if not isinstance(c,dict) or k not in c: return default
        c=c[k]
    return c
def set_value(keys,value):
    c=load(); d=c
    for k in keys[:-1]: d=d.setdefault(k,{})
    d[keys[-1]]=value; save(c)
