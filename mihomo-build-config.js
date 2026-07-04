#!/usr/bin/env node
// mihomo-build-config.js — 容器内：原始订阅 → mihomo 可用配置
//   读 src（ro 挂载的用户原始配置/订阅），写 dst（可写副本）。
//   1) 格式识别：clash-yaml / base64订阅 / URI直链 / JSON(SIP008)。
//      非 yaml 自动转最小 Clash 配置（proxies + url-test自动选最快 + select + MATCH,PROXY）。
//      支持 ss / vmess / trojan / vless / hysteria2(hy2)。
//   2) 强制注入 TUN：剥离已有 tun:/dns: 顶层块 → 追加规范 tun:（+ 缺失时补 dns:）。
//   退出码：0=成功产出配置；1=硬失败（空 / 识别为订阅但 0 节点 / 读取失败）。
//   用法：node mihomo-build-config.js [src] [dst]
//     默认 src=/etc/mihomo/config.yaml  dst=/home/AISC/.mihomo/config.yaml
const fs = require('fs');
const SRC = process.argv[2] || '/etc/mihomo/config.yaml';
const DST = process.argv[3] || '/home/AISC/.mihomo/config.yaml';

// ==================== YAML 输出 ====================
function isPlainStr(s) {
  return typeof s === 'string' && s !== '' && s === s.trim() &&
         !/[:#\[\]{},&*?|<>=!%@`"\n]/.test(s);
}
function scalar(v) {
  if (v === true || v === false) return v ? 'true' : 'false';
  if (typeof v === 'number') return String(v);
  if (typeof v === 'string') return isPlainStr(v) ? v : JSON.stringify(v);
  return JSON.stringify(String(v));
}
function emitObj(obj, indent) {
  const pad = ' '.repeat(indent);
  return Object.entries(obj).map(([k, v]) => {
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      return `${pad}${k}:\n` + emitObj(v, indent + 2);
    }
    return `${pad}${k}: ${scalar(v)}`;
  }).join('\n');
}
function emitProxy(p) {
  return Object.entries(p).map(([k, v], i) => {
    const prefix = i === 0 ? '  - ' : '    ';
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      return `${prefix}${k}:\n` + emitObj(v, 6);
    }
    return `${prefix}${k}: ${scalar(v)}`;
  }).join('\n');
}
function buildConfig(proxies) {
  if (!proxies || !proxies.length) throw new Error('未解析到任何代理节点');
  const names = proxies.map(p => p.name);
  let y = 'proxies:\n' + proxies.map(emitProxy).join('\n') + '\n';
  y += 'proxy-groups:\n';
  y += '  - name: PROXY\n    type: url-test\n    url: http://www.gstatic.com/generate_204\n    interval: 300\n    tolerance: 50\n    proxies:\n';
  y += names.map(n => '      - ' + scalar(n)).join('\n') + '\n';
  y += '  - name: SELECT\n    type: select\n    proxies:\n';
  y += ['      - PROXY'].concat(names.map(n => '      - ' + scalar(n))).join('\n') + '\n';
  y += 'rules:\n  - MATCH,PROXY\n';
  return y;
}

// ==================== URI 解析 ====================
function parseSS(uri) {
  let b = uri.slice(5);
  let name = ''; const h = b.indexOf('#');
  if (h >= 0) { name = decodeURIComponent(b.slice(h + 1)); b = b.slice(0, h); }
  const q = b.indexOf('?'); if (q >= 0) b = b.slice(0, q);
  let method, password, host, port;
  if (b.includes('@')) {
    const at = b.lastIndexOf('@');
    let userinfo = b.slice(0, at); const hostport = b.slice(at + 1);
    if (!userinfo.includes(':')) {
      try { userinfo = Buffer.from(userinfo.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8'); } catch (e) {}
    } else { userinfo = decodeURIComponent(userinfo); }
    const c = userinfo.indexOf(':'); method = userinfo.slice(0, c); password = userinfo.slice(c + 1);
    const hp = hostport.split(':'); host = hp[0]; port = hp[1];
  } else {
    let dec; try { dec = Buffer.from(b.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8'); } catch (e) { return null; }
    const at = dec.lastIndexOf('@'); const mp = dec.slice(0, at); const hp = dec.slice(at + 1);
    const c = mp.indexOf(':'); method = mp.slice(0, c); password = mp.slice(c + 1);
    const hpa = hp.split(':'); host = hpa[0]; port = hpa[1];
  }
  if (!host || !port) return null;
  return { name: name || `ss-${host}:${port}`, type: 'ss', server: host, port: Number(port), cipher: method, password };
}
function parseVmess(uri) {
  let b = uri.slice(8); let dec;
  try { dec = Buffer.from(b, 'base64').toString('utf8'); } catch (e) { return null; }
  let o; try { o = JSON.parse(dec); } catch (e) { return null; }
  const p = { name: o.ps || `vmess-${o.add}:${o.port}`, type: 'vmess', server: o.add, port: Number(o.port), uuid: o.id, alterId: Number(o.aid || 0), cipher: o.scy || 'auto', network: o.net || 'tcp' };
  if (o.net === 'ws') { p['ws-opts'] = {}; if (o.path) p['ws-opts'].path = o.path; if (o.host) p['ws-opts'].headers = { Host: o.host }; }
  if (o.net === 'grpc') { p['grpc-opts'] = { 'grpc-service-name': o.path || '' }; }
  if (o.tls === 'tls') { p.tls = true; if (o.sni || o.host) p.servername = o.sni || o.host; }
  return p;
}
function parseTrojan(uri) {
  let b = uri.slice(9);
  let name = ''; const h = b.indexOf('#'); if (h >= 0) { name = decodeURIComponent(b.slice(h + 1)); b = b.slice(0, h); }
  let query = ''; const q = b.indexOf('?'); if (q >= 0) { query = b.slice(q + 1); b = b.slice(0, q); }
  const at = b.lastIndexOf('@'); if (at < 0) return null;
  const password = decodeURIComponent(b.slice(0, at)); const hp = b.slice(at + 1).replace(/\/.*$/, '');
  const [host, port] = hp.split(':'); if (!host || !port) return null;
  const pr = Object.fromEntries(new URLSearchParams(query));
  const p = { name: name || `trojan-${host}:${port}`, type: 'trojan', server: host, port: Number(port), password };
  if (pr.sni) p.sni = pr.sni; else if (pr.peer) p.sni = pr.peer;
  if (pr.allowIn === '1' || pr.allowIn === 'true') p['skip-cert-verify'] = true;
  if (pr.type === 'ws') { p.network = 'ws'; p['ws-opts'] = {}; if (pr.path) p['ws-opts'].path = pr.path; if (pr.host) p['ws-opts'].headers = { Host: pr.host }; }
  if (pr.type === 'grpc') { p.network = 'grpc'; p['grpc-opts'] = { 'grpc-service-name': pr.serviceName || '' }; }
  return p;
}
function parseVless(uri) {
  let b = uri.slice(8);
  let name = ''; const h = b.indexOf('#'); if (h >= 0) { name = decodeURIComponent(b.slice(h + 1)); b = b.slice(0, h); }
  let query = ''; const q = b.indexOf('?'); if (q >= 0) { query = b.slice(q + 1); b = b.slice(0, q); }
  const at = b.lastIndexOf('@'); if (at < 0) return null;
  const uuid = b.slice(0, at); const hp = b.slice(at + 1).replace(/\/.*$/, '');
  const [host, port] = hp.split(':'); if (!host || !port) return null;
  const pr = Object.fromEntries(new URLSearchParams(query));
  const p = { name: name || `vless-${host}:${port}`, type: 'vless', server: host, port: Number(port), uuid, network: pr.type || 'tcp' };
  if (pr.security === 'tls') { p.tls = true; if (pr.sni) p.servername = pr.sni; if (pr.fp) p['client-fingerprint'] = pr.fp; }
  else if (pr.security === 'reality') { p.tls = true; p['reality-opts'] = {}; if (pr.pbk) p['reality-opts']['public-key'] = pr.pbk; if (pr.sid) p['reality-opts']['short-id'] = pr.sid; if (pr.sni) p.servername = pr.sni; if (pr.fp) p['client-fingerprint'] = pr.fp; }
  if (pr.flow) p.flow = pr.flow;
  if (pr.type === 'ws') { p.network = 'ws'; p['ws-opts'] = {}; if (pr.path) p['ws-opts'].path = pr.path; if (pr.host) p['ws-opts'].headers = { Host: pr.host }; }
  if (pr.type === 'grpc') { p.network = 'grpc'; p['grpc-opts'] = { 'grpc-service-name': pr.serviceName || '' }; }
  return p;
}
function parseHysteria2(uri) {
  let b = uri.replace(/^hysteria2:\/\//, '').replace(/^hy2:\/\//, '');
  let name = ''; const h = b.indexOf('#'); if (h >= 0) { name = decodeURIComponent(b.slice(h + 1)); b = b.slice(0, h); }
  let query = ''; const q = b.indexOf('?'); if (q >= 0) { query = b.slice(q + 1); b = b.slice(0, q); }
  b = b.replace(/^\//, '');
  const at = b.lastIndexOf('@'); let auth = '', hostport = b;
  if (at >= 0) { auth = decodeURIComponent(b.slice(0, at)); hostport = b.slice(at + 1); }
  hostport = hostport.replace(/\/.*$/, '');
  let host, port;
  if (hostport.startsWith('[')) { const m = hostport.match(/^\[(.+)\]:(\d+)$/); host = m ? m[1] : hostport.replace(/[\[\]]/g, ''); port = m ? m[2] : '443'; }
  else { const lc = hostport.lastIndexOf(':'); host = lc >= 0 ? hostport.slice(0, lc) : hostport; port = lc >= 0 ? hostport.slice(lc + 1) : '443'; }
  if (!host) return null;
  const pr = Object.fromEntries(new URLSearchParams(query));
  const p = { name: name || `hy2-${host}:${port}`, type: 'hysteria2', server: host, port: Number(port) };
  if (auth) p.password = auth;
  if (pr.sni) p.sni = pr.sni;
  if (pr.insecure === '1' || pr.insecure === 'true') p['skip-cert-verify'] = true;
  if (pr.obfs) { p.obfs = pr.obfs; if (pr['obfs-password']) p['obfs-password'] = pr['obfs-password']; }
  return p;
}
function parseUri(line) {
  line = line.trim();
  if (line.startsWith('ss://')) return parseSS(line);
  if (line.startsWith('vmess://')) return parseVmess(line);
  if (line.startsWith('trojan://')) return parseTrojan(line);
  if (line.startsWith('vless://')) return parseVless(line);
  if (line.startsWith('hysteria2://') || line.startsWith('hy2://')) return parseHysteria2(line);
  return null;
}

// ==================== 格式识别 + 转换 ====================
// 返回 {text, fmt, nodes}；nodes=代理数（转换格式时），clash-yaml/unknown 时为 null
function convert(raw) {
  const t = raw.trim();
  if (!t) return { text: '', fmt: 'empty', nodes: 0 };
  if (/^(proxies|proxy-groups|mixed-port|port|socks-port|rules|dns|tun)\s*:/m.test(t)) {
    return { text: raw, fmt: 'clash-yaml', nodes: null };
  }
  if (t.startsWith('{') || t.startsWith('[')) {
    try { const o = JSON.parse(t); if (Array.isArray(o.servers || o)) {
      const arr = (o.servers || o).map(s => {
        const p = { name: s.name || s.remarks || `ss-${s.server}:${s.server_port}`, type: 'ss', server: s.server, port: Number(s.server_port), cipher: s.method, password: s.password };
        if (s.plugin) { p.plugin = s.plugin; if (s.plugin_opts) p['plugin-opts'] = s.plugin_opts; }
        return p;
      });
      return { text: buildConfig(arr), fmt: 'sip008', nodes: arr.length };
    }} catch (e) {}
  }
  if (!/\s/.test(t) && /^[A-Za-z0-9+/=_-]+$/.test(t) && t.length > 20) {
    try {
      const d = Buffer.from(t.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8');
      if (/:\/\//.test(d)) { const arr = d.split('\n').map(parseUri).filter(Boolean); return { text: buildConfig(arr), fmt: 'base64-sub', nodes: arr.length }; }
    } catch (e) {}
  }
  if (/[a-z0-9]+:\/\//.test(t)) {
    try { const arr = t.split('\n').map(parseUri).filter(Boolean); return { text: buildConfig(arr), fmt: 'uri-list', nodes: arr.length }; } catch (e) {}
  }
  return { text: raw, fmt: 'unknown', nodes: null };
}

// ==================== TUN/DNS 强制注入 ====================
function stripTopBlock(lines, key) {
  const out = []; let inBlock = false;
  for (const raw of lines) {
    if (/^\s*#/.test(raw)) { if (!inBlock) out.push(raw); continue; }
    if (/^[^\s]/.test(raw)) { inBlock = new RegExp('^' + key + ':').test(raw); if (!inBlock) out.push(raw); continue; }
    if (!inBlock) out.push(raw);
  }
  return out.join('\n');
}
const TUN = ['# === AISC forced TUN (auto-patched) ===','tun:','  enable: true','  stack: system','  dns-hijack:','    - any:53','  auto-route: true','  auto-detect-interface: true'].join('\n');
const DNS = ['# === AISC fallback DNS (auto-patched, only if absent) ===','dns:','  enable: true','  listen: 0.0.0.0:1053','  enhanced-mode: fake-ip','  nameserver:','    - 223.5.5.5','    - 119.29.29.29','  fallback:','    - 8.8.8.8','    - 1.1.1.1'].join('\n');

// ==================== main ====================
let raw;
try { raw = fs.readFileSync(SRC, 'utf8').replace(/\r\n?/g, '\n'); }
catch (e) { console.error('❌ 读取配置失败: ' + SRC + ' (' + e.message + ')'); process.exit(1); }

const r = convert(raw);
if (r.fmt === 'empty') { console.error('❌ 配置内容为空'); process.exit(1); }
if ((r.fmt === 'base64-sub' || r.fmt === 'uri-list' || r.fmt === 'sip008') && r.nodes === 0) {
  console.error('❌ 识别为订阅但解析到 0 个节点（可能协议不支持，目前支持 ss/vmess/trojan/vless/hysteria2）');
  process.exit(1);
}

// 状态日志（stdout → 终端可见）
if (r.nodes !== null) {
  console.log(`📦 订阅格式: ${r.fmt} → 已转换为 ${r.nodes} 个节点的 Clash 配置`);
} else if (r.fmt === 'clash-yaml') {
  console.log('📦 订阅格式: clash-yaml（原样使用）');
} else {
  console.log('📦 订阅格式: 未识别（按 yaml 原样尝试，若失败请改用 yaml 直链）');
}

// TUN/DNS 注入（在转换后的文本上）
let p = stripTopBlock(r.text.split('\n'), 'tun');
p = p.replace(/\s+$/, '\n') + '\n' + TUN + '\n';
if (!/^dns:/m.test(p)) p += '\n' + DNS + '\n';

fs.mkdirSync(require('path').dirname(DST), { recursive: true });
fs.writeFileSync(DST, p, 'utf8');
console.log('✅ TUN 配置已注入: ' + DST);
