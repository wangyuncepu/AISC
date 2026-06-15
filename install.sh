#!/usr/bin/env bash
# ==============================================================================
# Claude Code + DeepSeek 一键安装引导脚本 (Linux / macOS)
# ==============================================================================
# 职责:
#   1. 检测操作系统和包管理器
#   2. 检测 Node.js >= 18，缺失则自动安装（支持中国大陆镜像）
#   3. 配置 npm 镜像源
#   4. 安装项目依赖并启动主脚本 (install.js)
#
# 用法:
#   ./install.sh              # 正常安装
#   ./install.sh --dry-run    # 仅检测环境，不执行任何安装
#   ./install.sh --cn         # 强制使用国内镜像
#   ./install.sh --no-cn      # 强制不使用国内镜像
# ==============================================================================

set -euo pipefail

# ---- 颜色定义 ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ---- 全局状态 ----
DRY_RUN=false
USE_CN_MIRROR=""
NODE_OK=false
NODE_VERSION=""
OS_TYPE=""
OS_DISTRO=""
OS_DISTRO_ID=""
OS_DISTRO_VERSION=""
PKG_MANAGER=""
NEED_INSTALL_NODE=false
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- 辅助函数 ----

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()  { echo -e "\n${CYAN}${BOLD}==>${NC} ${BOLD}$*${NC}"; }
dry_echo()  { if [ "$DRY_RUN" = true ]; then echo -e "      ${YELLOW}[DRY-RUN]${NC} $*"; fi; }

# ---- 参数解析 ----

parse_args() {
    for arg in "$@"; do
        case "$arg" in
            --dry-run)
                DRY_RUN=true
                log_info "运行模式: DRY-RUN（仅检测，不安装）"
                ;;
            --cn)
                USE_CN_MIRROR=true
                ;;
            --no-cn)
                USE_CN_MIRROR=false
                ;;
        esac
    done
}

# ---- 操作系统检测 ----

detect_os() {
    log_step "检测操作系统..."

    OS_TYPE="$(uname -s)"
    case "$OS_TYPE" in
        Linux)
            detect_linux_distro
            ;;
        Darwin)
            OS_DISTRO="macOS"
            OS_DISTRO_ID="macos"
            OS_DISTRO_VERSION="$(sw_vers -productVersion 2>/dev/null || echo 'unknown')"
            PKG_MANAGER="$(command -v brew >/dev/null 2>&1 && echo 'brew' || echo 'none')"
            log_ok "操作系统: macOS ${OS_DISTRO_VERSION}"
            log_info "包管理器: ${PKG_MANAGER}"
            ;;
        *)
            log_error "不支持的操作系统: ${OS_TYPE}"
            log_error "当前支持的平台: Linux (Debian/Ubuntu/Arch/Fedora/Alpine/openSUSE) 和 macOS"
            exit 1
            ;;
    esac
}

detect_linux_distro() {
    if [ -f /etc/os-release ]; then
        # shellcheck source=/dev/null
        . /etc/os-release
        OS_DISTRO_ID="${ID:-unknown}"
        OS_DISTRO_VERSION="${VERSION_ID:-unknown}"
        OS_DISTRO="${NAME:-unknown}"
    elif [ -f /etc/arch-release ]; then
        OS_DISTRO_ID="arch"
        OS_DISTRO="Arch Linux"
        OS_DISTRO_VERSION="rolling"
    elif [ -f /etc/alpine-release ]; then
        OS_DISTRO_ID="alpine"
        OS_DISTRO="Alpine Linux"
        OS_DISTRO_VERSION="$(cat /etc/alpine-release)"
    else
        OS_DISTRO_ID="unknown"
        OS_DISTRO="Unknown Linux"
        OS_DISTRO_VERSION="unknown"
    fi

    # 检测包管理器
    if command -v apt-get >/dev/null 2>&1; then
        PKG_MANAGER="apt"
    elif command -v pacman >/dev/null 2>&1; then
        PKG_MANAGER="pacman"
    elif command -v dnf >/dev/null 2>&1; then
        PKG_MANAGER="dnf"
    elif command -v yum >/dev/null 2>&1; then
        PKG_MANAGER="yum"
    elif command -v apk >/dev/null 2>&1; then
        PKG_MANAGER="apk"
    elif command -v zypper >/dev/null 2>&1; then
        PKG_MANAGER="zypper"
    else
        PKG_MANAGER="unknown"
    fi

    log_ok "操作系统: ${OS_DISTRO} (${OS_DISTRO_ID}) ${OS_DISTRO_VERSION}"
    log_info "包管理器: ${PKG_MANAGER}"
}

# ---- 网络环境检测 ----

detect_network() {
    # 如果用户已通过参数指定，则跳过自动检测
    if [ -n "$USE_CN_MIRROR" ]; then
        if [ "$USE_CN_MIRROR" = true ]; then
            log_info "网络环境: 中国大陆镜像 (由参数指定)"
        else
            log_info "网络环境: 国际网络 (由参数指定)"
        fi
        return
    fi

    log_step "检测网络环境..."

    # 快速检测是否能访问 Google（3秒超时）
    local can_access_google
    if curl -s --connect-timeout 3 --max-time 3 https://www.google.com > /dev/null 2>&1; then
        can_access_google=true
    else
        can_access_google=false
    fi

    # 检测是否能访问 npmmirror（国内镜像）
    local can_access_npmmirror
    if curl -s --connect-timeout 3 --max-time 3 https://registry.npmmirror.com > /dev/null 2>&1; then
        can_access_npmmirror=true
    else
        can_access_npmmirror=false
    fi

    if [ "$can_access_google" = true ] && [ "$can_access_npmmirror" = false ]; then
        USE_CN_MIRROR=false
        log_ok "网络环境: 国际网络（可访问 Google）"
    elif [ "$can_access_npmmirror" = true ]; then
        USE_CN_MIRROR=true
        log_ok "网络环境: 中国大陆（使用国内镜像加速）"
    else
        log_warn "无法确定网络环境，默认尝试国内镜像"
        USE_CN_MIRROR=true
    fi
}

# ---- Node.js 版本检测 ----

check_node() {
    log_step "检测 Node.js..."

    if command -v node >/dev/null 2>&1; then
        NODE_VERSION="$(node -v 2>/dev/null | sed 's/^v//')"
        local major_version
        major_version="$(echo "$NODE_VERSION" | cut -d. -f1)"

        if [ "$major_version" -ge 18 ] 2>/dev/null; then
            NODE_OK=true
            log_ok "Node.js 版本: v${NODE_VERSION} (符合要求 >= 18)"
        else
            NODE_OK=false
            log_warn "Node.js 版本: v${NODE_VERSION} (需要 >= 18)"
            NEED_INSTALL_NODE=true
        fi
    else
        NODE_OK=false
        log_warn "Node.js 未安装"
        NEED_INSTALL_NODE=true
    fi

    # 检查 npm
    if command -v npm >/dev/null 2>&1; then
        local npm_version
        npm_version="$(npm -v 2>/dev/null)"
        log_ok "npm 版本: v${npm_version}"
    elif [ "$NODE_OK" = true ]; then
        log_warn "npm 未找到（但 Node.js 已安装，这不太正常）"
    fi
}

# ---- Node.js 安装策略 ----

install_node_via_nvm() {
    log_info "使用 nvm 安装 Node.js (LTS)..."

    local nvm_install_script
    local node_mirror_export=""

    if [ "$USE_CN_MIRROR" = true ]; then
        # Gitee nvm 镜像
        nvm_install_script="https://gitee.com/mirrors/nvm/raw/master/install.sh"
        node_mirror_export="export NVM_NODEJS_ORG_MIRROR=https://npmmirror.com/mirrors/node"
        log_info "nvm 安装脚本来源: Gitee 镜像"
    else
        nvm_install_script="https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh"
    fi

    dry_echo "curl -o- ${nvm_install_script} | bash"
    dry_echo "${node_mirror_export}"
    dry_echo "nvm install --lts"

    if [ "$DRY_RUN" = false ]; then
        export NVM_DIR="${HOME}/.nvm"
        curl -o- "$nvm_install_script" | bash

        # shellcheck source=/dev/null
        [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

        if [ "$USE_CN_MIRROR" = true ]; then
            export NVM_NODEJS_ORG_MIRROR="https://npmmirror.com/mirrors/node"
        fi

        nvm install --lts
        nvm use --lts
    fi
}

install_node_linux() {
    log_step "自动安装 Node.js (Linux)..."

    case "$PKG_MANAGER" in
        apt)
            if [ "$USE_CN_MIRROR" = true ]; then
                log_info "配置 apt 阿里云镜像源..."
                dry_echo "sed -i 's|http://archive.ubuntu.com|https://mirrors.aliyun.com|g' /etc/apt/sources.list"
                if [ "$DRY_RUN" = false ]; then
                    sudo sed -i 's|http://archive.ubuntu.com|https://mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true
                    sudo sed -i 's|http://security.ubuntu.com|https://mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true
                fi
            fi
            log_info "通过 apt 安装 Node.js..."
            dry_echo "sudo apt-get update && sudo apt-get install -y nodejs npm"
            if [ "$DRY_RUN" = false ]; then
                sudo apt-get update -qq
                sudo apt-get install -y nodejs npm || {
                    log_warn "apt 默认源 Node.js 版本可能过旧，尝试 NodeSource..."
                    if [ "$USE_CN_MIRROR" = true ]; then
                        curl -fsSL https://mirrors.aliyun.com/nodesource/setup_20.x | sudo -E bash -
                    else
                        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
                    fi
                    sudo apt-get install -y nodejs
                }
            fi
            ;;

        pacman)
            if [ "$USE_CN_MIRROR" = true ]; then
                log_info "配置 pacman 中科大镜像源..."
                dry_echo "echo 'Server = https://mirrors.ustc.edu.cn/archlinux/\$repo/os/\$arch' >> /etc/pacman.d/mirrorlist"
                if [ "$DRY_RUN" = false ]; then
                    sudo sed -i '1iServer = https://mirrors.ustc.edu.cn/archlinux/$repo/os/$arch' /etc/pacman.d/mirrorlist 2>/dev/null || true
                fi
            fi
            log_info "通过 pacman 安装 Node.js..."
            dry_echo "sudo pacman -Syu --noconfirm nodejs npm"
            if [ "$DRY_RUN" = false ]; then
                sudo pacman -Syu --noconfirm nodejs npm
            fi
            ;;

        dnf|yum)
            if [ "$USE_CN_MIRROR" = true ]; then
                log_info "配置 dnf 阿里云镜像源..."
                dry_echo "sed -i 's|^metalink=|#metalink=|g' /etc/yum.repos.d/*.repo"
            fi
            log_info "通过 ${PKG_MANAGER} 安装 Node.js..."
            dry_echo "sudo ${PKG_MANAGER} install -y nodejs npm"
            if [ "$DRY_RUN" = false ]; then
                sudo "$PKG_MANAGER" install -y nodejs npm
            fi
            ;;

        apk)
            log_info "通过 apk 安装 Node.js..."
            dry_echo "sudo apk add --no-cache nodejs npm"
            if [ "$DRY_RUN" = false ]; then
                sudo apk add --no-cache nodejs npm
            fi
            ;;

        zypper)
            log_info "通过 zypper 安装 Node.js..."
            dry_echo "sudo zypper install -y nodejs npm"
            if [ "$DRY_RUN" = false ]; then
                sudo zypper install -y nodejs npm
            fi
            ;;

        *)
            log_warn "未找到支持的包管理器，回退到 nvm 安装"
            install_node_via_nvm
            ;;
    esac

    if [ "$DRY_RUN" = false ]; then
        # 验证安装
        if command -v node >/dev/null 2>&1; then
            NODE_OK=true
            NODE_VERSION="$(node -v | sed 's/^v//')"
            log_ok "Node.js 安装成功: v${NODE_VERSION}"
        else
            log_error "Node.js 安装失败，请手动安装 Node.js >= 18"
            exit 1
        fi
    fi
}

install_node_macos() {
    log_step "自动安装 Node.js (macOS)..."

    if [ "$PKG_MANAGER" = "brew" ]; then
        if [ "$USE_CN_MIRROR" = true ]; then
            log_info "配置 Homebrew 中科大镜像源..."
            dry_echo "export HOMEBREW_BREW_GIT_REMOTE=https://mirrors.ustc.edu.cn/brew.git"
            dry_echo "export HOMEBREW_CORE_GIT_REMOTE=https://mirrors.ustc.edu.cn/homebrew-core.git"
            if [ "$DRY_RUN" = false ]; then
                export HOMEBREW_BREW_GIT_REMOTE="https://mirrors.ustc.edu.cn/brew.git"
                export HOMEBREW_CORE_GIT_REMOTE="https://mirrors.ustc.edu.cn/homebrew-core.git"
            fi
        fi
        log_info "通过 Homebrew 安装 Node.js..."
        dry_echo "brew install node"
        if [ "$DRY_RUN" = false ]; then
            brew install node
        fi
    else
        log_warn "Homebrew 未安装，尝试直接下载 Node.js pkg..."
        local download_url
        if [ "$USE_CN_MIRROR" = true ]; then
            download_url="https://npmmirror.com/mirrors/node/v20.19.0/node-v20.19.0.pkg"
        else
            download_url="https://nodejs.org/dist/v20.19.0/node-v20.19.0.pkg"
        fi
        dry_echo "curl -fsSL ${download_url} -o /tmp/node-install.pkg && sudo installer -pkg /tmp/node-install.pkg -target /"
        if [ "$DRY_RUN" = false ]; then
            curl -fsSL "$download_url" -o /tmp/node-install.pkg
            sudo installer -pkg /tmp/node-install.pkg -target /
            rm -f /tmp/node-install.pkg
        fi
    fi

    if [ "$DRY_RUN" = false ]; then
        if command -v node >/dev/null 2>&1; then
            NODE_OK=true
            NODE_VERSION="$(node -v | sed 's/^v//')"
            log_ok "Node.js 安装成功: v${NODE_VERSION}"
        else
            log_error "Node.js 安装失败，请手动安装 Node.js >= 18"
            exit 1
        fi
    fi
}

configure_npm_mirror() {
    log_step "配置 npm 镜像源..."

    if [ "$USE_CN_MIRROR" = true ]; then
        log_info "设置 npm registry 为 https://registry.npmmirror.com"
        dry_echo "npm config set registry https://registry.npmmirror.com"
        dry_echo "npm config set disturl https://npmmirror.com/mirrors/node"
        if [ "$DRY_RUN" = false ]; then
            npm config set registry https://registry.npmmirror.com
            npm config set disturl https://npmmirror.com/mirrors/node
        fi
        log_ok "npm 镜像源已配置为 npmmirror"
    else
        log_info "使用 npm 官方源"
        log_info "如需手动切换国内源: npm config set registry https://registry.npmmirror.com"
    fi
}

# ---- 安装项目依赖 ----

install_project_deps() {
    log_step "安装项目依赖..."

    if [ -f "${SCRIPT_DIR}/package.json" ]; then
        dry_echo "cd ${SCRIPT_DIR} && npm install"
        if [ "$DRY_RUN" = false ]; then
            cd "$SCRIPT_DIR"
            npm install --silent
        fi
        log_ok "项目依赖安装完成 (${SCRIPT_DIR}/node_modules)"
    else
        log_warn "未找到 package.json，跳过依赖安装"
    fi
}

# ---- 启动主脚本 ----

launch_main_script() {
    log_step "启动主安装脚本..."

    local main_script="${SCRIPT_DIR}/install.js"

    if [ ! -f "$main_script" ]; then
        log_error "未找到主脚本: ${main_script}"
        log_error "请确认 install.js 文件存在"
        exit 1
    fi

    dry_echo "node ${main_script}"

    if [ "$DRY_RUN" = false ]; then
        # 将网络环境参数传递给 Node.js 脚本
        if [ "$USE_CN_MIRROR" = true ]; then
            export CC_INSTALL_USE_CN=true
        else
            export CC_INSTALL_USE_CN=false
        fi
        node "$main_script"
    fi
}

# ---- 打印运行摘要 ----

print_summary() {
    echo ""
    echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}${BOLD}║${NC}       ${BOLD}Claude Code 安装引导层 — 环境检测报告${NC}          ${CYAN}${BOLD}║${NC}"
    echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${BOLD}操作系统:${NC}       ${OS_DISTRO} (${OS_DISTRO_ID}) ${OS_DISTRO_VERSION}"
    echo -e "  ${BOLD}包管理器:${NC}       ${PKG_MANAGER:-none}"
    echo -e "  ${BOLD}Node.js 状态:${NC}   $([ "$NODE_OK" = true ] && echo -e "${GREEN}✓ 已安装${NC}" || echo -e "${RED}✗ 需安装${NC}")"
    if [ -n "$NODE_VERSION" ] && [ "$NODE_OK" = true ]; then
        echo -e "  ${BOLD}Node.js 版本:${NC}   v${NODE_VERSION}"
    fi
    echo -e "  ${BOLD}国内镜像:${NC}       $([ "$USE_CN_MIRROR" = true ] && echo '是 (npmmirror / 阿里云 / 中科大)' || echo '否 (官方源)')"
    echo -e "  ${BOLD}运行模式:${NC}       $([ "$DRY_RUN" = true ] && echo 'DRY-RUN (仅检测)' || echo '正常安装')"
    echo -e "  ${BOLD}脚本目录:${NC}       ${SCRIPT_DIR}"
    echo ""

    if [ "$DRY_RUN" = true ]; then
        echo -e "  ${YELLOW}${BOLD}DRY-RUN 模式: 以上为检测结果，未执行任何实际安装操作。${NC}"
        echo -e "  ${YELLOW}移除 --dry-run 参数即可正常安装。${NC}"
    fi
    echo ""
}

# ---- 主流程 ----

main() {
    echo ""
    echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}${BOLD}║${NC}     ${BOLD}Claude Code + DeepSeek 一键安装引导层${NC}              ${CYAN}${BOLD}║${NC}"
    echo -e "${CYAN}${BOLD}║${NC}     ${NC}Linux / macOS Bootstrap${NC}                            ${CYAN}${BOLD}║${NC}"
    echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""

    parse_args "$@"
    detect_os
    detect_network
    check_node

    if [ "$NEED_INSTALL_NODE" = true ]; then
        if [ "$OS_TYPE" = "Darwin" ]; then
            install_node_macos
        else
            install_node_linux
        fi

        # 重新检测 Node.js
        check_node
    fi

    # DRY-RUN 模式下也走到 print_summary，但跳过后续安装
    if [ "$DRY_RUN" = true ]; then
        print_summary
        echo -e "${GREEN}${BOLD}✓ 引导层 dry-run 测试完成，环境检测一切正常。${NC}"
        echo ""
        exit 0
    fi

    if [ "$NODE_OK" = false ]; then
        log_error "Node.js 环境未就绪，请手动安装 Node.js >= 18 后重试"
        log_error "手动安装指引: https://nodejs.org/zh-cn/download/"
        exit 1
    fi

    configure_npm_mirror
    install_project_deps
    print_summary
    launch_main_script
}

# ---- 执行 ----
main "$@"
