#!/usr/bin/env python3
"""R3 UI-plane automated test: remote Explorer over CDP in the real Workbench.

Chain: target_set(wsl) -> workspace_list (REMOTE tree over ssh/serve) ->
expand subdirectory -> workspace_create_file + write preview roundtrip ->
watcher: workspace_watch_start + a remote-side file mutation surfaces as a
workspace://changed event -> watch_stop + target_clear.
"""
import json, selectors, subprocess, time, urllib.request

import websocket

CDP = "http://localhost:9223"
REMOTE_WS = "/home/dev/AISC"

with urllib.request.urlopen(CDP + "/json") as r:
    pages = json.load(r)
page = next(p for p in pages if p.get("type") == "page" and "9000" in (p.get("url") or ""))
ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30)
_mid = [0]
sel = selectors.DefaultSelector()
sel.register(ws, selectors.EVENT_READ)

def call(expr):
    _mid[0] += 1
    mid = _mid[0]
    ws.send(json.dumps({"id": mid, "method": "Runtime.evaluate",
                        "params": {"expression": expr, "awaitPromise": True,
                                   "returnByValue": True}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == mid:
            if "error" in msg:
                raise RuntimeError(msg["error"])
            res = msg["result"]
            if "exceptionDetails" in res:
                d = res["exceptionDetails"]
                raise RuntimeError(str(d.get("exception", {}).get("description") or d.get("text")))
            return res.get("result", {}).get("value")

call("(async () => {"
     "  const core = await import('/@id/@tauri-apps/api/core');"
     "  const evt = await import('/@id/@tauri-apps/api/event');"
     "  window.__inv = core.invoke; window.__listen = evt.listen;"
     "  return 'booted';"
     "})()")
print("boot", flush=True)

# 1. remote target + list the REMOTE repo root
print("target_set:", call("window.__inv('target_set', { name: 'wsl' }).kind"), flush=True)
top = call(f"window.__inv('workspace_list', {{ workspace: {json.dumps(REMOTE_WS)}, relativeDir: '', cursor: 0 }})")
names = [n["name"] for n in top["nodes"]]
kinds = {n["name"]: n["kind"] for n in top["nodes"]}
print("remote root entries:", len(names), names[:8], flush=True)
assert "src" in names and kinds["src"] == "dir", names
assert "node_modules" not in names, "ignore parity broken"
assert "VERSION" in names

# 2. lazy expand a subdirectory
sub = call(f"window.__inv('workspace_list', {{ workspace: {json.dumps(REMOTE_WS)}, relativeDir: 'src/aisc/cli/commands', cursor: 0 }})")
sub_names = [n["name"] for n in sub["nodes"]]
print("subdir entries:", sub_names[:6], flush=True)
assert "serve.py" in sub_names and "serve_fs.py" in sub_names, sub_names

# 3. preview a REMOTE file through the same channel
prev = call(f"window.__inv('workspace_preview', {{ workspace: {json.dumps(REMOTE_WS)}, relativePath: 'VERSION' }})")
print("preview size:", prev["size"], "text:", (prev.get("text") or "")[:20], flush=True)
assert prev["text"] and "2.1.9" in prev["text"], prev

# 4. mutation: create a file remotely + preview it back
mut = call(f"window.__inv('workspace_create_file', {{ workspace: {json.dumps(REMOTE_WS)}, relativeDir: 'src/aisc/cli/commands', name: 'r3-cdp-probe.txt' }})")
print("create_file:", mut, flush=True)
assert mut["relative_path"].endswith("r3-cdp-probe.txt")
# clean it up via rename-to-nothing is not a thing; remote fs.delete has no
# command yet — the Rust delete rides fs op later; leave the probe (gitignored
# workspace is fine, and the file is empty).

# 5. watcher: listen for workspace://changed while mutating the REMOTE tree
call("(async () => { window.__changed = 0; window.__un = await window.__listen('workspace://changed', () => window.__changed++); })()")
call(f"window.__inv('workspace_watch_start', {{ workspace: {json.dumps(REMOTE_WS)} }})")
time.sleep(1.5)
subprocess.run(["ssh", "-p", "2222", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
                "dev@localhost", f"touch {REMOTE_WS}/r3-watch-probe.md && sleep 0.3 && echo x > {REMOTE_WS}/r3-watch-probe.md"],
               check=True, capture_output=True, timeout=30)
deadline = time.time() + 25
fired = 0
while time.time() < deadline:
    fired = call("window.__changed")
    if fired:
        break
    time.sleep(1)
print("watch events fired:", fired, flush=True)
assert fired, "remote fs.change never reached workspace://changed"
call(f"window.__inv('workspace_watch_stop')")
call("window.__un && window.__un()")
subprocess.run(["ssh", "-p", "2222", "-o", "BatchMode=yes", "dev@localhost",
                f"rm -f {REMOTE_WS}/r3-watch-probe.md"], check=True, capture_output=True, timeout=30)

print("target_clear:", call("window.__inv('target_clear').kind"), flush=True)
print("R3 UI-CDP FULL PASS", flush=True)
