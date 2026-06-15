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
 * 同步执行命令，返回 stdout（出错时抛异常）
 */
function exec(cmd, opts = {}) {
  const isWin = OS === "win32";
  // Windows 需要用 cmd /c 包装
  const finalCmd = isWin && !cmd.startsWith("cmd /c") ? `cmd /c ${cmd}` : cmd;
  return execSync(finalCmd, {
    stdio: opts.silent ? "pipe" : "inherit",
    encoding: "utf-8",
    ...opts,
  });
}

/**
 * 带 spinner 的 exec
 */
function execWithSpinner(cmd, label, opts = {}) {
  const spin = spinner();
  spin.start(label);
  try {
    const result = execSync(cmd, {
      stdio: "pipe",
      encoding: "utf-8",
      ...opts,
    });
    spin.stop(pc.green("✓ 完成"));
    return result;
  } catch (err) {
    spin.stop(pc.red("✗ 失败"));
    throw err;
  }
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
// 环境变量文件生成
// =============================================================================

/**
 * 生成所有平台的环境变量配置并写入文件
 * @param {string} apiKey - 用户的 DeepSeek API Key
 */
function writeEnvFiles(apiKey) {
  ensureDir(CLAUDE_DIR);

  const results = [];

  // --- bash / zsh (export 语法) ---
  const bashLines = [
    "# ============================================================",
    "# Claude Code + DeepSeek 环境变量",
    `# 生成时间: ${new Date().toISOString()}`,
    "# 用法: source ~/.claude/env.sh",
    "# ============================================================",
    "",
    `export ${AUTH_TOKEN_KEY}='${apiKey}'`,
  ];
  for (const [key, val] of HIDDEN_ENV_VARS) {
    bashLines.push(`export ${key}='${val}'`);
  }
  bashLines.push("");

  const bashPath = join(CLAUDE_DIR, "env.sh");
  writeFileSync(bashPath, bashLines.join("\n") + "\n");
  chmodSync(bashPath, 0o644);
  results.push({ shell: "bash/zsh", path: bashPath });

  // --- fish (set -gx 语法) ---
  const fishLines = [
    "# ============================================================",
    "# Claude Code + DeepSeek 环境变量 (Fish Shell)",
    `# 生成时间: ${new Date().toISOString()}`,
    "# 用法: source ~/.claude/env.fish",
    "# ============================================================",
    "",
    `set -gx ${AUTH_TOKEN_KEY} '${apiKey}'`,
  ];
  for (const [key, val] of HIDDEN_ENV_VARS) {
    fishLines.push(`set -gx ${key} '${val}'`);
  }
  fishLines.push("");

  const fishPath = join(CLAUDE_DIR, "env.fish");
  writeFileSync(fishPath, fishLines.join("\n") + "\n");
  chmodSync(fishPath, 0o644);
  results.push({ shell: "fish", path: fishPath });

  // --- PowerShell ---
  if (OS === "win32") {
    const psLines = [
      "# ============================================================",
      "# Claude Code + DeepSeek 环境变量 (PowerShell)",
      `# 生成时间: ${new Date().toISOString()}`,
      "# 用法: . $HOME\\.claude\\env.ps1",
      "# ============================================================",
      "",
      `$env:${AUTH_TOKEN_KEY}='${apiKey}'`,
    ];
    for (const [key, val] of HIDDEN_ENV_VARS) {
      psLines.push(`$env:${key}='${val}'`);
    }
    psLines.push("");

    const psPath = join(CLAUDE_DIR, "env.ps1");
    writeFileSync(psPath, psLines.join("\n") + "\n");
    results.push({ shell: "powershell", path: psPath });
  }

  return results;
}

/**
 * 将环境变量注入当前进程（子进程将继承）
 */
function injectEnvToProcess(apiKey) {
  process.env[AUTH_TOKEN_KEY] = apiKey;
  for (const [key, val] of HIDDEN_ENV_VARS) {
    process.env[key] = val;
  }
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
// Claude Code 安装
// =============================================================================

function installClaudeCode() {
  const label = "正在安装 @anthropic-ai/claude-code (全局)...";
  return execWithSpinner("npm install -g @anthropic-ai/claude-code", label);
}

// =============================================================================
// Claude 自动配置执行
// =============================================================================

async function runClaudeAutoConfig(apiKey, useCN) {
  const prompt = buildAutoConfigPrompt(apiKey, useCN);

  // 将 Prompt 写入临时文件（避免 shell 转义问题）
  const promptFile = join(tmpdir(), "cc-auto-config-prompt.txt");
  writeFileSync(promptFile, prompt, "utf-8");
  const promptContent = prompt;

  const spin = spinner();
  spin.start("正在通过 Claude Code 自动配置 Skills/MCP (约需 1-2 分钟)...");

  return new Promise((resolve) => {
    // Windows 用 cmd /c 包装
    const cmd = OS === "win32" ? "cmd" : "claude";
    const args =
      OS === "win32"
        ? ["/c", "claude", "--print", promptContent, "--dangerously-skip-permissions", "--output-format", "text"]
        : ["--print", promptContent, "--dangerously-skip-permissions", "--output-format", "text"];

    const child = spawn(cmd, args, {
      cwd: HOME,
      env: { ...process.env, ...Object.fromEntries(HIDDEN_ENV_VARS), [AUTH_TOKEN_KEY]: apiKey },
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

function verifyClaudeCode() {
  try {
    const version = execSync("claude --version", {
      stdio: "pipe",
      encoding: "utf-8",
    }).trim();
    return { ok: true, version };
  } catch {
    return { ok: false, version: null };
  }
}

// =============================================================================
// 安装汇总
// =============================================================================

function printSummary(apiKey, envFiles, autoConfigResult) {
  const maskedKey =
    apiKey.length > 8
      ? apiKey.slice(0, 4) + "****" + apiKey.slice(-4)
      : "****";

  // 检测并建议正确的 source 命令
  const currentShell = detectShell();
  let sourceCmd = `source ${join(CLAUDE_DIR, "env.sh")}`;
  if (currentShell === "fish") {
    sourceCmd = `source ${join(CLAUDE_DIR, "env.fish")}`;
  }

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

  // ---- API Key ----
  console.log(`  ${pc.bold("API Key:")}     ${maskedKey} (已写入环境变量)`);

  // ---- 环境变量文件 ----
  console.log(`  ${pc.bold("环境变量文件:")}`);
  for (const f of envFiles) {
    console.log(
      `    ${pc.green("✓")} ${f.path}  ${pc.dim(`(${f.shell})`)}`,
    );
  }

  // ---- Skills / MCP 状态 ----
  console.log(`  ${pc.bold("Skills / MCP 配置:")}`);
  if (autoConfigResult && autoConfigResult.success) {
    for (const [name, skill] of Object.entries(SKILLS_CONFIG)) {
      console.log(
        `    ${pc.green("✓")} ${name}  ${pc.dim(`— ${skill.description.split("—")[0].trim()}`)}`,
      );
    }
  } else {
    console.log(
      `    ${pc.yellow("⚠")} Claude Code 自动配置未完全成功，请手动执行以下命令：`,
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

  // ---- 启动命令 ----
  console.log("");
  console.log(`  ${pc.bold("启动 Claude Code:")}`);
  console.log("");
  currentShell === "fish"
    ? console.log(
        `    ${pc.green(`source ~/.claude/env.fish  # 添加到 ~/.config/fish/config.fish 中`)}`,
      )
    : console.log(
        `    ${pc.green(`echo 'source ~/.claude/env.sh' >> ~/.${currentShell}rc`)}`,
      );
  console.log(`    ${pc.green("claude")}`);
  console.log("");

  // ---- GCP 凭据提醒 ----
  const gstack = SKILLS_CONFIG["gstack"];
  if (gstack && gstack.requiredEnv.length > 0) {
    console.log(`  ${pc.yellow(pc.bold("⚠ 提醒:"))} ${gstack.name} 需要额外配置:`);
    console.log(`    ${pc.yellow(`export ${gstack.requiredEnv[0]}=/path/to/gcp-key.json`)}`);
    console.log(`    ${pc.dim(gstack.envNote)}`);
    console.log("");
  }
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
    try {
      execSync("npm config set registry https://registry.npmmirror.com", {
        stdio: "pipe",
      });
      execSync(
        "npm config set disturl https://npmmirror.com/mirrors/node",
        { stdio: "pipe" },
      );
      console.log(pc.dim("  npm 镜像源 → https://registry.npmmirror.com"));
    } catch {
      // 非关键，继续
    }
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

  // 验证安装
  const ccVerification = verifyClaudeCode();
  if (!ccVerification.ok) {
    console.error(pc.red("\nClaude Code 安装后无法执行 claude --version"));
    console.error(pc.yellow("请检查 PATH 环境变量或重新打开终端"));
    process.exit(1);
  }
  console.log(`  ${pc.green("✓")} Claude Code 安装成功: ${ccVerification.version}`);

  // ---- Step 4: 写入环境变量 ----
  console.log("");
  const spinEnv = spinner();
  spinEnv.start("正在写入环境变量配置文件...");
  const envFiles = writeEnvFiles(apiKey);
  injectEnvToProcess(apiKey);
  spinEnv.stop(
    pc.green(`✓ 环境变量已写入 ${envFiles.length} 个配置文件`),
  );

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
  if (autoConfirm) {
    autoConfigResult = await runClaudeAutoConfig(apiKey, useCNMirror);
  }

  // ---- Step 6: 打印汇总 ----
  printSummary(apiKey, envFiles, autoConfigResult);

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
