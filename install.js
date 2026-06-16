#!/usr/bin/env node
// =============================================================================
// Claude Code + DeepSeek 一键安装主脚本 (跨平台 TUI)
// =============================================================================
// 前置依赖: 由 install.sh / install.ps1 引导层调用
//   - Node.js >= 18 已就绪
//   - npm install 已完成（@clack/prompts, picocolors）
//
// 职责:
//   1. TUI 交互: 网络环境选择 + DeepSeek API Key 输入（仅此 2 问）
//   2. 安装 @anthropic-ai/claude-code
//   3. 写入环境变量文件（bash / fish / PowerShell）
//   4. 生成 Prompt 并触发 Claude Code 自动配置 5 个 Skills/MCP
//   5. 打印安装汇总
// =============================================================================

import { intro, outro, text, password, confirm, note, spinner, isCancel, cancel } from "@clack/prompts";
import { execSync, spawn } from "node:child_process";
import { homedir, platform, tmpdir } from "node:os";
import {
  existsSync,
  readFileSync,
  writeFileSync,
  mkdirSync,
  chmodSync,
} from "node:fs";
import { join, dirname } from "node:path";
import pc from "picocolors";

// =============================================================================
// 硬编码常量 — 来自 DEEPSEEK_README.md 官方默认值
// =============================================================================

const DEEPSEEK_DEFAULTS = {
  ANTHROPIC_BASE_URL: "https://api.deepseek.com/anthropic",
  ANTHROPIC_MODEL: "deepseek-v4-pro[1m]",
  ANTHROPIC_DEFAULT_OPUS_MODEL: "deepseek-v4-pro[1m]",
  ANTHROPIC_DEFAULT_SONNET_MODEL: "deepseek-v4-pro[1m]",
  ANTHROPIC_DEFAULT_HAIKU_MODEL: "deepseek-v4-flash",
  CLAUDE_CODE_SUBAGENT_MODEL: "deepseek-v4-flash",
  CLAUDE_CODE_EFFORT_LEVEL: "max",
};

// 不要通过 TUI 暴露给用户的变量（全部硬编码）
const HIDDEN_ENV_VARS = Object.entries(DEEPSEEK_DEFAULTS)
  .map(([k, v]) => [k, v]);

// 只有 ANTHROPIC_AUTH_TOKEN 来自用户输入
const AUTH_TOKEN_KEY = "ANTHROPIC_AUTH_TOKEN";

// =============================================================================
// Skills / MCP 安装定义
// =============================================================================

const SKILLS_CONFIG = {
  superpowers: {
    name: "superpowers",
    type: "plugin",
    marketplace: "obra/superpowers-marketplace",
    plugin: "superpowers@superpowers-marketplace",
    description: "Superpowers — 20+ 实战 Skills（测试/调试/协作）",
    requiredEnv: [],
  },
  "document-skills": {
    name: "document-skills",
    type: "plugin",
    marketplace: "anthropics/skills",
    plugin: "document-skills@anthropic-agent-skills",
    description: "Document Skills — Anthropic 官方文档处理（Excel/Word/PPT/PDF）",
    requiredEnv: [],
  },
  caveman: {
    name: "caveman",
    type: "plugin",
    marketplace: "JuliusBrussee/caveman",
    plugin: "caveman@caveman",
    description: "Caveman — SPEC.md 压缩工具（节省约 75% Token）",
    requiredEnv: [],
  },
  gstack: {
    name: "gstack",
    type: "mcp",
    command: "npx",
    args: ["-y", "gcloud-mcp"],
    description: "GStack — Google Cloud MCP Server（需 GCP 凭据）",
    requiredEnv: ["GOOGLE_APPLICATION_CREDENTIALS"],
    envNote: "请提前准备好 GCP Service Account JSON 文件路径",
  },
  "claude-hub": {
    name: "claude-hub",
    type: "mcp",
    command: "npx",
    args: ["-y", "@amritessh/mcp-hub"],
    description: "Claude Hub — MCP Server 社区注册中心（npm for MCP）",
    requiredEnv: [],
  },
};

// =============================================================================
// 工具函数
// =============================================================================

const OS = platform(); // 'linux' | 'darwin' | 'win32'
const HOME = homedir();
const CLAUDE_DIR = join(HOME, ".claude");

/**
 * 确保目录存在
 */
function ensureDir(dir) {
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true });
  }
}

/**
 * 统一命令执行 — 自动处理 Windows cmd /c 包装
 * @returns {{ stdout: string, stderr: string, ok: boolean }}
 */
function sh(cmd, opts = {}) {
  const isWin = OS === "win32";
  const finalCmd = isWin && !cmd.startsWith("cmd /c") ? `cmd /c ${cmd}` : cmd;
  try {
    const stdout = execSync(finalCmd, {
      stdio: "pipe",
      encoding: "utf-8",
      ...opts,
    });
    return { stdout: stdout.trim(), stderr: "", ok: true };
  } catch (err) {
    return {
      stdout: (err.stdout || "").toString().trim(),
      stderr: (err.stderr || err.message || "").toString().trim(),
      ok: false,
    };
  }
}

/**
 * 带 spinner 的命令执行
 */
function shWithSpinner(cmd, label) {
  const spin = spinner();
  spin.start(label);
  const result = sh(cmd);
  if (result.ok) {
    spin.stop(pc.green("✓ 完成"));
  } else {
    spin.stop(pc.red("✗ 失败"));
  }
  return result;
}

/**
 * 检测是否在 Windows WSL 环境
 */
function isWSL() {
  if (OS !== "linux") return false;
  try {
    const version = readFileSync("/proc/version", "utf-8");
    return /microsoft|WSL/i.test(version);
  } catch {
    return false;
  }
}

/**
 * 检测当前 Shell 类型
 */
function detectShell() {
  const shellPath = process.env.SHELL || "";
  if (shellPath.includes("fish")) return "fish";
  if (shellPath.includes("zsh")) return "zsh";
  if (shellPath.includes("bash")) return "bash";
  return OS === "win32" ? "powershell" : "bash"; // 默认
}

// =============================================================================
// 环境变量管理 — 单一数据源，直接写入 Shell 原生配置文件
// =============================================================================

/**
 * 构建完整的环境变量表（单一数据源）
 */
function buildEnvVars(apiKey) {
  /** @type {{ [key: string]: string }} */
  const vars = {};
  vars[AUTH_TOKEN_KEY] = apiKey;
  for (const [key, val] of HIDDEN_ENV_VARS) {
    vars[key] = val;
  }
  return vars;
}

/**
 * 获取当前 Shell 的原生配置文件路径
 */
function getShellRcPath() {
  if (OS === "win32") {
    // $PROFILE 可能包含多个路径，优先 CurrentUserCurrentHost
    const profile = process.env.PROFILE;
    if (profile) return profile;
    // 回退到默认路径
    const pwshDir = existsSync(join(HOME, "Documents", "PowerShell"))
      ? join(HOME, "Documents", "PowerShell")
      : join(HOME, "Documents", "WindowsPowerShell");
    return join(pwshDir, "Microsoft.PowerShell_profile.ps1");
  }

  const shell = detectShell();
  switch (shell) {
    case "zsh":
      return join(HOME, ".zshrc");
    case "fish":
      return join(HOME, ".config", "fish", "config.fish");
    case "bash":
    default:
      return join(HOME, ".bashrc");
  }
}

/**
 * 直接写入 Shell 原生 RC 文件（幂等：重复运行不会重复写入）
 * @param {{ [key: string]: string }} envVars
 * @returns {{ rcPath: string, shell: string }}
 */
function writeEnvToShellRc(envVars) {
  const rcPath = getShellRcPath();
  const shell = detectShell();
  ensureDir(dirname(rcPath));

  const ts = new Date().toISOString();
  const marker = "# >>> AutoCC — Claude Code + DeepSeek >>>";
  const endMarker = "# <<< AutoCC <<<";

  // 根据 Shell 类型生成对应语法的代码块
  let block = `\n${marker}\n`;
  block += `# 生成时间: ${ts}\n`;
  block += `# 每次启动 Shell 自动加载以下环境变量\n`;

  if (OS === "win32") {
    for (const [key, val] of Object.entries(envVars)) {
      block += `$env:${key}='${val}'\n`;
    }
  } else if (shell === "fish") {
    for (const [key, val] of Object.entries(envVars)) {
      block += `set -gx ${key} '${val}'\n`;
    }
  } else {
    // bash / zsh
    for (const [key, val] of Object.entries(envVars)) {
      block += `export ${key}='${val}'\n`;
    }
  }
  block += `${endMarker}\n`;

  // 幂等：如果已有旧块，先移除
  let content = "";
  if (existsSync(rcPath)) {
    content = readFileSync(rcPath, "utf-8");
    // 如果末尾没有换行，补一个
    if (content.length > 0 && !content.endsWith("\n")) {
      content += "\n";
    }
    // 移除旧的 AutoCC 块
    if (content.includes(marker)) {
      const re = new RegExp(
        `\\n?${marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}[\\s\\S]*?${endMarker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\n?`,
        "g",
      );
      content = content.replace(re, "");
    }
  }

  writeFileSync(rcPath, content + block);
  return { rcPath, shell };
}

/**
 * 将环境变量加载到当前进程（子进程自动继承）
 * 等价于 source/dot-source 刚写入的 RC 文件
 */
function loadEnvToProcess(envVars) {
  for (const [key, val] of Object.entries(envVars)) {
    process.env[key] = val;
  }
}

/**
 * 写入备份文件 ~/.claude/.env（通用 KEY=VAL 格式，供非标准场景使用）
 */
function writeBackupEnvFile(envVars) {
  ensureDir(CLAUDE_DIR);
  const ts = new Date().toISOString();
  const lines = [
    "# Claude Code + DeepSeek 环境变量 (备份)",
    `# 生成时间: ${ts}`,
    "# 主要配置已写入 Shell RC 文件，此文件仅作备份",
    "",
  ];
  for (const [key, val] of Object.entries(envVars)) {
    lines.push(`${key}=${val}`);
  }
  lines.push("");
  const backupPath = join(CLAUDE_DIR, ".env");
  writeFileSync(backupPath, lines.join("\n") + "\n");
  return backupPath;
}

// =============================================================================
// Claude Code 自动配置 Prompt 模板
// =============================================================================

function buildAutoConfigPrompt(apiKey, useCN) {
  // 对 plugin 类型的 skill，生成 marketplace add + install 命令
  // 对 mcp 类型的 skill，生成 mcp add 命令

  const pluginSteps = [];
  const mcpSteps = [];

  for (const [_, skill] of Object.entries(SKILLS_CONFIG)) {
    if (skill.type === "plugin") {
      pluginSteps.push(
        `  claude plugin marketplace add ${skill.marketplace}`,
        `  claude plugin install ${skill.plugin}`,
      );
    } else if (skill.type === "mcp") {
      const argsStr = skill.args.map((a) => `"${a}"`).join(" ");
      let mcpCmd = `  claude mcp add --transport stdio ${skill.name} -- ${skill.command} ${argsStr}`;
      mcpSteps.push(mcpCmd);
    }
  }

  const prompt = `You are performing automated post-install configuration for Claude Code.
Execute each step below in order. Use bash commands (NOT slash commands).
If a step fails, briefly note the error and continue to the next step.
At the end, verify all installations with "claude mcp list".

## Plugin Marketplaces & Plugin Installation

${pluginSteps.join("\n")}

## MCP Server Installation

${mcpSteps.join("\n")}

## Verification

After all steps complete, run:
  claude mcp list
  claude plugin list

Report a final summary with the status of each item.`;

  return prompt;
}

// =============================================================================
// DeepSeek API 连通性验证
// =============================================================================

/**
 * 验证 DeepSeek API 是否可达
 * 发送一个最小请求（1 token）确认鉴权和网络
 * @param {{ [key: string]: string }} envVars
 * @returns {boolean}
 */
function verifyDeepSeekApi(envVars) {
  const baseUrl = envVars.ANTHROPIC_BASE_URL || "https://api.deepseek.com/anthropic";
  const apiKey = envVars[AUTH_TOKEN_KEY] || "";
  const model = envVars.ANTHROPIC_MODEL || "deepseek-v4-pro[1m]";

  // 用 curl 发送最小探测请求（1 token 输出，不计费或极低费用）
  const curlCmd =
    `curl -s -o /dev/null -w "%{http_code}" --connect-timeout 10 --max-time 15 ` +
    `-H "x-api-key: ${apiKey}" ` +
    `-H "anthropic-version: 2023-06-01" ` +
    `-H "content-type: application/json" ` +
    `-d '{"model":"${model}","max_tokens":1,"messages":[{"role":"user","content":"ping"}]}' ` +
    `"${baseUrl}/v1/messages"`;

  // 注意：Windows 上 curl 语法相同，cmd /c 由 sh() 自动处理
  const result = sh(curlCmd);
  if (!result.ok) {
    // curl 本身失败（网络不通、DNS 解析失败等）
    return false;
  }
  const httpCode = result.stdout.trim();
  // 200 = 鉴权成功；401/403 = 鉴权失败但端点可达（网络没问题）
  // 其他 4xx/5xx 视为不可达
  return httpCode === "200" || httpCode === "401" || httpCode === "403";
}

// =============================================================================
// Claude Code 安装
// =============================================================================

function installClaudeCode() {
  const label = "正在安装 @anthropic-ai/claude-code (全局)...";
  const result = shWithSpinner("npm install -g @anthropic-ai/claude-code", label);
  if (!result.ok) {
    throw new Error(result.stderr || "npm install 失败");
  }
  return result;
}

// =============================================================================
// Claude 自动配置执行
// =============================================================================

async function runClaudeAutoConfig(apiKey, useCN, envVars) {
  const prompt = buildAutoConfigPrompt(apiKey, useCN);

  // 将 Prompt 写入临时文件（避免 shell 转义问题）
  const promptFile = join(tmpdir(), "cc-auto-config-prompt.txt");
  writeFileSync(promptFile, prompt, "utf-8");
  const promptContent = prompt;

  const spin = spinner();
  spin.start("正在通过 Claude Code 自动配置 Skills/MCP (约需 1-2 分钟)...");

  return new Promise((resolve) => {
    const cmd = OS === "win32" ? "cmd" : "claude";
    const args =
      OS === "win32"
        ? ["/c", "claude", "--print", promptContent, "--dangerously-skip-permissions", "--output-format", "text"]
        : ["--print", promptContent, "--dangerously-skip-permissions", "--output-format", "text"];

    // 使用 unified envVars（与写入文件的数据完全一致）
    const childEnv = { ...process.env, ...envVars };

    const child = spawn(cmd, args, {
      cwd: HOME,
      env: childEnv,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });

    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });

    child.on("close", (code) => {
      // 清理临时文件
      try { require("fs").unlinkSync(promptFile); } catch {}

      if (code === 0) {
        spin.stop(pc.green("✓ 自动配置完成"));
        resolve({ success: true, stdout, stderr });
      } else {
        spin.stop(pc.yellow("⚠ 自动配置返回非零状态"));
        resolve({ success: false, stdout, stderr, exitCode: code });
      }
    });

    child.on("error", (err) => {
      spin.stop(pc.red("✗ 无法启动 Claude Code"));
      try { require("fs").unlinkSync(promptFile); } catch {}
      resolve({ success: false, error: err.message });
    });

    // 超时保护：5 分钟
    setTimeout(() => {
      if (!child.killed) {
        child.kill();
        spin.stop(pc.yellow("⚠ 自动配置超时（5 分钟）"));
        resolve({ success: false, error: "timeout" });
      }
    }, 5 * 60 * 1000);
  });
}

// =============================================================================
// 验证
// =============================================================================

/**
 * 验证 Claude Code 是否正确安装
 */
function verifyClaudeCode() {
  const result = sh("claude --version");
  if (result.ok && result.stdout) {
    return { ok: true, version: result.stdout };
  }
  return { ok: false, version: null, stderr: result.stderr };
}

/**
 * 验证单个 MCP Server 是否已配置
 */
function verifyMcpServer(name) {
  const result = sh("claude mcp list");
  if (!result.ok) return { configured: false, error: result.stderr };
  // 检查输出中是否包含该 server 名称
  return { configured: result.stdout.includes(name), error: null };
}

/**
 * 验证单个 Plugin 是否已安装
 */
function verifyPlugin(name) {
  const result = sh("claude plugin list");
  if (!result.ok) return { configured: false, error: result.stderr };
  return { configured: result.stdout.includes(name), error: null };
}

// =============================================================================
// 安装汇总
// =============================================================================

function printSummary(apiKey, rcPath, backupPath, autoConfigResult, verifiedSkills) {
  const maskedKey =
    apiKey.length > 8
      ? apiKey.slice(0, 4) + "****" + apiKey.slice(-4)
      : "****";

  const currentShell = detectShell();

  console.log("");
  console.log(
    pc.cyan(pc.bold("╔══════════════════════════════════════════════════════════╗")),
  );
  console.log(
    pc.cyan(pc.bold("║")) +
      pc.bold("       Claude Code + DeepSeek 安装完成！                ") +
      pc.cyan(pc.bold("║")),
  );
  console.log(
    pc.cyan(pc.bold("╚══════════════════════════════════════════════════════════╝")),
  );
  console.log("");

  // ---- Claude Code ----
  const ccVerification = verifyClaudeCode();
  console.log(`  ${pc.bold("Claude Code:")}`);
  if (ccVerification.ok) {
    console.log(`    ${pc.green("✓")} ${ccVerification.version}`);
  } else {
    console.log(`    ${pc.yellow("⚠")} 请验证安装`);
  }

  // ---- API Key + Shell 配置 ----
  console.log(`  ${pc.bold("API Key:")}       ${maskedKey}`);
  console.log(`  ${pc.bold("Shell 配置:")}     ${pc.green("✓ 已写入")} ${pc.dim(rcPath)}`);
  console.log(`  ${pc.bold("备份文件:")}       ${pc.dim(backupPath)}`);
  console.log(`  ${pc.bold("当前终端:")}       ${pc.green("✓ 环境变量已加载（仅本会话有效）")}`);

  // ---- 下次启动提示 ----
  console.log("");
  console.log(`  ${pc.bold("下次启动 Claude Code:")}`);
  if (OS === "win32") {
    console.log(`    ${pc.dim("新开 PowerShell 窗口后环境变量自动生效")}`);
  } else {
    console.log(`    ${pc.dim(`新终端自动 source ${rcPath}，环境变量已持久化`)}`);
  }
  console.log(`    ${pc.green("claude")}`);
  console.log("");

  // ---- Skills / MCP 状态 (基于实际验证) ----
  console.log(`  ${pc.bold("Skills / MCP 配置:")}`);
  if (verifiedSkills && Object.keys(verifiedSkills).length > 0) {
    for (const [name, skill] of Object.entries(SKILLS_CONFIG)) {
      const verified = verifiedSkills[name];
      if (verified && verified.configured) {
        console.log(
          `    ${pc.green("✓")} ${name}  ${pc.dim(`— ${skill.description.split("—")[0].trim()}`)}`,
        );
      } else {
        console.log(
          `    ${pc.red("✗")} ${name}  ${pc.dim(`— 未成功配置`)}`,
        );
      }
    }
  } else if (autoConfigResult && autoConfigResult.success) {
    for (const [name, skill] of Object.entries(SKILLS_CONFIG)) {
      console.log(
        `    ${pc.yellow("?")} ${name}  ${pc.dim(`— 待验证 (${skill.description.split("—")[0].trim()})`)}`,
      );
    }
    console.log(`    ${pc.yellow("  ↑ 请运行 claude mcp list 和 claude plugin list 确认")}`);
  } else {
    console.log(
      `    ${pc.yellow("⚠")} Claude Code 自动配置未成功，请手动执行以下命令：`,
    );
    console.log("");
    console.log(`    ${pc.dim("# 在终端中依次执行:")}`);
    for (const [name, skill] of Object.entries(SKILLS_CONFIG)) {
      if (skill.type === "plugin") {
        console.log(
          `    ${pc.yellow(`claude plugin marketplace add ${skill.marketplace}`)}`,
        );
        console.log(
          `    ${pc.yellow(`claude plugin install ${skill.plugin}`)}`,
        );
      } else {
        const argsStr = skill.args.map((a) => `"${a}"`).join(" ");
        console.log(
          `    ${pc.yellow(`claude mcp add --transport stdio ${skill.name} -- ${skill.command} ${argsStr}`)}`,
        );
      }
    }
  }

  // ---- GCP 凭据提醒 ----
  const gstack = SKILLS_CONFIG["gstack"];
  if (gstack && gstack.requiredEnv.length > 0) {
    console.log("");
    console.log(`  ${pc.yellow(pc.bold("⚠ 提醒:"))} ${gstack.name} 需要额外配置:`);
    if (OS === "win32") {
      console.log(`    ${pc.yellow(`$env:${gstack.requiredEnv[0]}='C:\\path\\to\\gcp-key.json'`)}`);
    } else {
      console.log(`    ${pc.yellow(`export ${gstack.requiredEnv[0]}=/path/to/gcp-key.json`)}`);
    }
    console.log(`    ${pc.dim(gstack.envNote)}`);
  }
  console.log("");
}

// =============================================================================
// 主流程
// =============================================================================

async function main() {
  // ---- 读取引导层传入的网络环境参数 ----
  const bootstrapCN = process.env.CC_INSTALL_USE_CN;
  let useCNMirror = bootstrapCN === "true";

  console.log("");
  console.log(
    pc.cyan(pc.bold("╔══════════════════════════════════════════════════════════╗")),
  );
  console.log(
    pc.cyan(pc.bold("║")) +
      pc.bold("     Claude Code + DeepSeek 一键安装与配置                ") +
      pc.cyan(pc.bold("║")),
  );
  console.log(
    pc.cyan(pc.bold("║")) +
      pc.dim("     跨平台 TUI · DeepSeek API · 5 Skills 自动挂载      ") +
      pc.cyan(pc.bold("║")),
  );
  console.log(
    pc.cyan(pc.bold("╚══════════════════════════════════════════════════════════╝")),
  );

  // ---- Step 1: 网络环境选择 ----
  // 如果引导层已确定，跳过此问题
  if (bootstrapCN === undefined || bootstrapCN === "") {
    const cnChoice = await confirm({
      message: "是否使用中国大陆镜像源？\n  (npmmirror.com — 国内下载速度更快)",
      initialValue: true,
    });

    if (isCancel(cnChoice)) {
      cancel("安装已取消");
      process.exit(0);
    }
    useCNMirror = cnChoice;
  }

  // 配置 npm 镜像
  if (useCNMirror) {
    sh("npm config set registry https://registry.npmmirror.com");
    sh("npm config set disturl https://npmmirror.com/mirrors/node");
    console.log(pc.dim("  npm 镜像源 → https://registry.npmmirror.com"));
  }

  console.log("");

  // ---- Step 2: API Key 输入 ----
  const apiKey = await password({
    message: "请输入 DeepSeek API Key\n  (从 https://platform.deepseek.com 获取)",
    validate(value) {
      if (!value || value.trim().length === 0) {
        return "API Key 不能为空！请从 DeepSeek Platform 获取";
      }
      if (value.trim().length < 10) {
        return "API Key 长度似乎过短，请确认输入正确";
      }
    },
  });

  if (isCancel(apiKey)) {
    cancel("安装已取消");
    process.exit(0);
  }

  // 显示模型配置（仅展示，不询问）
  note(
    `模型配置已使用 DeepSeek 官方默认值:\n` +
      `  ANTHROPIC_MODEL               = ${DEEPSEEK_DEFAULTS.ANTHROPIC_MODEL}\n` +
      `  ANTHROPIC_DEFAULT_HAIKU_MODEL = ${DEEPSEEK_DEFAULTS.ANTHROPIC_DEFAULT_HAIKU_MODEL}\n` +
      `  CLAUDE_CODE_EFFORT_LEVEL      = ${DEEPSEEK_DEFAULTS.CLAUDE_CODE_EFFORT_LEVEL}\n` +
      `  (Base URL: ${DEEPSEEK_DEFAULTS.ANTHROPIC_BASE_URL})`,
    "模型配置（自动设置）",
  );

  // ---- Step 3: 安装 Claude Code ----
  console.log("");
  try {
    installClaudeCode();
  } catch (err) {
    console.error(pc.red(`\nClaude Code 安装失败: ${err.message}`));
    console.error(pc.yellow("请尝试手动执行: npm install -g @anthropic-ai/claude-code"));
    process.exit(1);
  }

  // 验证安装（不需要 API Key，仅确认二进制可用）
  const ccVerification = verifyClaudeCode();
  if (!ccVerification.ok) {
    console.error(pc.red("\nClaude Code 安装后无法执行 claude --version"));
    console.error(pc.yellow("请检查 PATH 环境变量或重新打开终端"));
    process.exit(1);
  }
  console.log(`  ${pc.green("✓")} Claude Code 安装成功: ${ccVerification.version}`);

  // ---- Step 4: 配置环境变量 ----
  // 1. 构建单一数据源
  // 2. 写入 Shell 原生 RC 文件（$PROFILE / .bashrc / .zshrc / config.fish）
  // 3. 同时加载到当前进程（等价于 source）
  // 4. 写入备份文件 ~/.claude/.env
  console.log("");
  const spinEnv = spinner();
  spinEnv.start("正在写入 Shell 配置文件...");

  const envVars = buildEnvVars(apiKey);

  // 写入 Shell 原生 RC 文件
  const { rcPath, shell: rcShell } = writeEnvToShellRc(envVars);

  // 加载到当前进程（当前终端立即生效，后续 claude 子进程可鉴权）
  loadEnvToProcess(envVars);

  // 写入备份（供容器/CI 等非标准场景使用）
  const backupPath = writeBackupEnvFile(envVars);

  spinEnv.stop(pc.green("✓ 环境变量已写入"));

  // 显示写入位置
  console.log(`    ${pc.dim("Shell 配置文件:")} ${pc.bold(rcPath)}`);
  console.log(`    ${pc.dim("备份文件:")}       ${backupPath}`);
  console.log(`    ${pc.dim("当前终端:")}       ${pc.green("已立即生效（仅本会话）")}`);

  // ---- Step 4.5: 验证 DeepSeek API 连通性 ----
  console.log("");
  const spinConn = spinner();
  spinConn.start("正在验证 DeepSeek API 连通性...");
  const connOk = verifyDeepSeekApi(envVars);
  if (connOk) {
    spinConn.stop(pc.green("✓ DeepSeek API 连通正常"));
  } else {
    spinConn.stop(pc.yellow("⚠ DeepSeek API 连通性检查未通过"));
    console.log(pc.yellow("  自动配置将跳过，请手动检查 API Key 和网络后重试"));
    console.log(pc.dim(`  Base URL: ${envVars.ANTHROPIC_BASE_URL}`));
    console.log("");
    // 跳过 auto-config，直接打印汇总
    printSummary(apiKey, rcPath, backupPath, null, {});
    console.log(pc.yellow("⚠ Shell 配置已写入，但 Skills/MCP 未自动配置"));
    console.log(pc.dim("  修复 API Key 后重新运行本脚本即可"));
    console.log("");
    return;
  }

  // ---- Step 5: Claude Code 自动配置 Skills/MCP ----
  console.log("");
  console.log(pc.cyan(pc.bold("═══════════ Claude Code 自动配置 Skills/MCP ═══════════")));
  console.log("");
  console.log(pc.dim("  以下 5 个 Skill/MCP 将由 Claude Code 自动安装和配置:"));
  console.log("");
  for (const [name, skill] of Object.entries(SKILLS_CONFIG)) {
    console.log(
      `    ${pc.green("●")} ${pc.bold(name)} — ${pc.dim(skill.description)}`,
    );
  }
  console.log("");

  const autoConfirm = await confirm({
    message: "是否立即执行自动配置？\n  (Claude Code 将自动安装上述 Skills/MCP)",
    initialValue: true,
  });

  if (isCancel(autoConfirm)) {
    cancel("安装已取消（环境变量已写入）");
    process.exit(0);
  }

  let autoConfigResult = null;
  let verifiedSkills = {};
  if (autoConfirm) {
    autoConfigResult = await runClaudeAutoConfig(apiKey, useCNMirror, envVars);

    // —— 验证自动配置是否真正生效 ——
    // 即使 claude --print 退出码为 0，内部命令也可能静默失败
    // 必须通过 claude mcp list / plugin list 确认
    if (autoConfigResult && autoConfigResult.success) {
      const spinVerify = spinner();
      spinVerify.start("正在验证 Skills/MCP 安装状态...");

      for (const [name, skill] of Object.entries(SKILLS_CONFIG)) {
        if (skill.type === "mcp") {
          const v = verifyMcpServer(skill.name);
          verifiedSkills[name] = v;
        } else if (skill.type === "plugin") {
          const v = verifyPlugin(name);
          verifiedSkills[name] = v;
        }
      }

      const configuredCount = Object.values(verifiedSkills).filter((v) => v.configured).length;
      const totalCount = Object.keys(SKILLS_CONFIG).length;

      if (configuredCount === totalCount) {
        spinVerify.stop(pc.green(`✓ 全部 ${totalCount} 个 Skills/MCP 已验证通过`));
      } else {
        spinVerify.stop(
          pc.yellow(`⚠ 验证结果: ${configuredCount}/${totalCount} 成功，其余可能需要手动配置`),
        );
      }
    }
  }

  // ---- Step 6: 打印汇总 ----
  printSummary(apiKey, rcPath, backupPath, autoConfigResult, verifiedSkills);

  console.log(pc.green(pc.bold("✓ 全部配置完成！")));
  console.log("");
}

// =============================================================================
// 启动
// =============================================================================

main().catch((err) => {
  console.error(pc.red(`\n未预期的错误: ${err.message}`));
  console.error(pc.dim(err.stack));
  process.exit(1);
});
