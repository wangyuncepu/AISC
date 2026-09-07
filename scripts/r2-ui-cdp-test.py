#!/usr/bin/env python3
"""R2 UI-plane automated test: drive the REAL Windows Workbench over CDP.

Chain under test (all inside the real app process): invoke('target_set')
-> invoke('open_session') with a Channel -> the Remote (serve PTY over ssh)
path in session.rs -> PtyEvent stream back through the channel ->
write_session / resize_session / close_session.
"""
import json, time, urllib.request, uuid

import websocket

CDP = "http://localhost:9223"
WSL_RUNTIME_ID = None  # injected via env
import os
RUNTIME_ID = os.environ["RTID"]

def pages():
    with urllib.request.urlopen(CDP + "/json") as r:
        return json.load(r)

page = next(p for p in pages() if p.get("type") == "page" and "9000" in (p.get("url") or ""))
print("page:", page["url"][:60], flush=True)
ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30)
_mid = [0]

def call(expr, await_promise=True):
    _mid[0] += 1
    mid = _mid[0]
    ws.send(json.dumps({"id": mid, "method": "Runtime.evaluate",
                        "params": {"expression": expr, "awaitPromise": await_promise,
                                   "returnByValue": True}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == mid:
            if "error" in msg:
                raise RuntimeError(msg["error"])
            res = msg["result"]
            if "exceptionDetails" in res:
                d=res["exceptionDetails"]; raise RuntimeError(str(d.get("exception",{}).get("description") or d.get("text")))
            return res.get("result", {}).get("value")

# 1. dynamic-import the REAL app API from the vite dev server
boot = call(
    "(async () => {"
    "  const core = await import('/@id/@tauri-apps/api/core');"
    "  window.__inv = core.invoke; window.__Chan = core.Channel;"
    "  return 'booted';"
    "})()")
print("boot:", boot, flush=True)

# 2. target: local -> wsl (remote)
print("target_get:", call("window.__inv('target_get')"), flush=True)
print("target_set:", call("window.__inv('target_set', { name: 'wsl' })"), flush=True)

# 3. open a remote bash session with a Channel for PtyEvents
sid = str(uuid.uuid4())
call(
    "(async () => {"
    f"  window.__evts = [];"
    f"  const ch = new window.__Chan();"
    f"  ch.onmessage = (m) => window.__evts.push(m);"
    f"  const r = await window.__inv('open_session', {{"
    f"    runtimeId: {json.dumps(RUNTIME_ID)}, sessionId: {json.dumps(sid)},"
    f"    agent: 'bash', workspace: 'C:/Users/VE111/Documents/AISC', onEvent: ch }});"
    f"  window.__snap = r; return 'opened';"
    "})().catch(e => { throw new Error(JSON.stringify(e)); })")
print("open_session ok, snapshot state:", call("window.__snap && window.__snap.state"), flush=True)

# 4. wait for the prompt in the event stream
deadline = time.time() + 45
while time.time() < deadline:
    n = call("window.__evts.length", await_promise=False)
    if n and n > 0:
        head = call("JSON.stringify(window.__evts.slice(0,2))", await_promise=False)
        print("events:", head[:160], flush=True)
        break
    time.sleep(1)
else:
    raise SystemExit("no PtyEvent within 45s")

# 5. type a command via the REAL write_session command
time.sleep(3)  # let bash readline settle
payload = list(b"echo UI-CDP-MARKER\r")
call(f"window.__inv('write_session', {{ sessionId: {json.dumps(sid)}, bytes: {json.dumps(payload)} }}).catch(e => {{ throw new Error(JSON.stringify(e)); }})")
# 6. resize via the REAL resize_session command (G1: in-band frame)
call(f"window.__inv('resize_session', {{ sessionId: {json.dumps(sid)}, cols: 100, rows: 30 }}).catch(e => {{ throw new Error(JSON.stringify(e)); }})")

# 7. collect: contiguous executed-output marker must arrive
import base64 as b64
deadline = time.time() + 30
ok = False
data_all = b""
while time.time() < deadline:
    segs = call("window.__evts.map(e => e.bytes || '')", await_promise=False) or []
    data_all = b"".join(b64.b64decode(sg + "===") for sg in segs)
    if b"UI-CDP-MARKER" in data_all:
        ok = True
        print("command output CONFIRMED via channel:", data_all[-120:], flush=True)
        break
    time.sleep(1)
if not ok:
    import base64 as b64
    print("events:", call("window.__evts.length", await_promise=False), "decoded-tail:", data_all[-200:], flush=True)
    raise SystemExit("no contiguous marker in channel stream")

# 8. close via the REAL close_session command; expect an exit event
call(f"window.__inv('close_session', {{ sessionId: {json.dumps(sid)} }}).catch(e => {{ throw new Error(JSON.stringify(e)); }})")
deadline = time.time() + 30
while time.time() < deadline:
    exited = call(
        "window.__evts.some(e => e.type === 'exit')", await_promise=False)
    if exited:
        print("exit event CONFIRMED", flush=True)
        break
    time.sleep(1)
assert exited, "no exit event after close_session"

# 9. restore local target
print("target_clear:", call("window.__inv('target_clear')"), flush=True)
print("UI-CDP FULL PASS", flush=True)
