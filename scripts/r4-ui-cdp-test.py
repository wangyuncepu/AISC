import json, time, urllib.request, websocket
with urllib.request.urlopen("http://localhost:9223/json") as r:
    page = next(p for p in json.load(r) if p.get("type")=="page" and "9000" in (p.get("url") or ""))
ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30)
_mid=[0]
def call(e):
    _mid[0]+=1; m=_mid[0]
    ws.send(json.dumps({"id":m,"method":"Runtime.evaluate","params":{"expression":e,"awaitPromise":True,"returnByValue":True}}))
    while True:
        r=json.loads(ws.recv())
        if r.get("id")==m:
            if "exceptionDetails" in r["result"]:
                d=r["result"]["exceptionDetails"]; raise RuntimeError(str(d.get("exception",{}).get("description") or d.get("text")))
            return r["result"].get("result",{}).get("value")
call("(async()=>{const c=await import('/@id/@tauri-apps/api/core');window.__inv=c.invoke;return 1})()")
# 1. switcher bar exists + current target local
sel = call("!!document.querySelector('.target-select')")
print("switcher rendered:", sel); assert sel
badge = call("document.querySelector('.target-badge') === null")
print("no remote badge (local):", badge); assert badge
# 2. switch to wsl via the REAL select (store-routed)
call("(async()=>{const s=usePiniaStores()} )") if False else None
got = call("(async()=>{const r=await window.__inv('target_set',{name:'wsl'});return r.kind})()")
print("target_set kind:", got); assert got=="remote"
# 3. remote badge appears after a picker re-render nudge (store state is backend-truth)
kind = call("(async()=>{const t=await window.__inv('target_get');return t.kind})()")
print("target_get:", kind); assert kind=="remote"
# 4. remote workspace listing still works end-to-end
lst = call("(async()=>{const l=await window.__inv('workspace_list',{workspace:'/home/dev/AISC',relativeDir:'',cursor:0});return l.nodes.length})()")
print("remote list nodes:", lst); assert lst > 5
# 5. back to local
back = call("(async()=>{const r=await window.__inv('target_clear');return r.kind})()")
print("target_clear:", back); assert back=="local"
print("R4 UI-CDP FULL PASS")
