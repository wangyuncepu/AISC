/** CDP 页内取证探针（手测排障用，2026-09-10 P1 手测 r4 首用）。
 *
 *  用途：手测反馈「界面行为与预期不符」时，绕过肉眼直接问 LIVE 页面——
 *  1) 模块新鲜度：页面内 import SFC 的 ?raw 源码，核对热更新是否真的
 *     把最新组件送进了 WebView（P1 r4 实战：定位输入框 CSS 三轮不生效）；
 *  2) IPC 链路：页面内直接 import ipc.ts 调真实 command，看返回/报错
 *     （P1 r4 实战：确认 revealId 链在 Rust 层丢字段——serde 静默剥 api_key）。
 *
 *  用法：
 *    1. 带远程调试口起 dev Workbench（WebView2 注入
 *       --remote-debugging-port=9222，如
 *       WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222）；
 *    2. node workbench/scripts/cdp-probe.cjs
 *    （可按需改下方 Runtime.evaluate 的探针表达式；端口固定 127.0.0.1:9222。）
 *
 *  依赖：ws（workbench/package.json devDependencies，仅本脚本使用，
 *  不进运行时产物）。 */
const WebSocket = require("ws");
const http = require("http");

function get(p) {
  return new Promise((res, rej) => {
    http.get({ host: "127.0.0.1", port: 9222, path: p }, (r) => {
      let d = "";
      r.on("data", (c) => (d += c));
      r.on("end", () => res(JSON.parse(d)));
    }).on("error", rej);
  });
}

(async () => {
  const pages = await get("/json/list");
  const ws = new WebSocket(pages[0].webSocketDebuggerUrl);
  let seq = 0;
  const pending = new Map();
  ws.on("message", (raw) => {
    const m = JSON.parse(raw);
    if (m.id && pending.has(m.id)) {
      pending.get(m.id)(m);
      pending.delete(m.id);
    }
  });
  const call = (method, params = {}) =>
    new Promise((res) => {
      const id = ++seq;
      pending.set(id, res);
      ws.send(JSON.stringify({ id, method, params }));
    });
  await new Promise((r) => ws.on("open", r));

  const probe = await call("Runtime.evaluate", {
    expression:
      "(async () => {" +
      "  const mod = await import('/src/features/ccswitch/ProviderEditPage.vue?raw');" +
      "  const src = String(mod.default);" +
      "  return JSON.stringify({ raw_len: src.length," +
      "    revealBtn: src.includes('revealApiKey')," +
      "    alignedStyle: src.includes('padding-right: 42px') });" +
      "})()",
    awaitPromise: true,
    returnByValue: true,
  });
  console.log("module-in-page:", JSON.stringify(probe.result).slice(0, 300));

  const ipc = await call("Runtime.evaluate", {
    expression:
      "(async () => {" +
      "  const ipc = await import('/src/lib/ipc.ts');" +
      "  try {" +
      "    const r = await ipc.ccSwitchProviders(" +
      "      'C:\\\\Users\\\\VE111\\\\Downloads\\\\artifacts-flood-test'," +
      "      'probe-nonexistent', 'claude', 'x');" +
      "    return JSON.stringify({ ok: true, n: r.providers.length });" +
      "  } catch (e) { return JSON.stringify({ ok: false, err: String(e).slice(0, 220) }); }" +
      "})()",
    awaitPromise: true,
    returnByValue: true,
  });
  console.log("ipc-probe:", JSON.stringify(ipc.result).slice(0, 400));
  ws.close();
  process.exit(0);
})().catch((e) => {
  console.log("ERR", e.message);
  process.exit(1);
});
