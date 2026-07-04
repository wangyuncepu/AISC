# launcher.ps1 — Super Claude AI 工作站启动器（中文 UI）
# cmd 的 .bat 对中文有 DBCS 解析缺陷，中文引导统一在此（PowerShell 原生 Unicode）。
# 由 一键启动_AI工作站.bat（ASCII 包装，chcp 65001）调用。
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$Image = 'super-claude:latest'
$ScriptDir = $PSScriptRoot
$Name = "super-claude-station-$(Get-Random)"

Write-Host ''
Write-Host '=========================================='
Write-Host '   Super Claude AI 工作站'
Write-Host '   cs 后端切换 · 插件内置 · 容器内 TUN 代理'
Write-Host '=========================================='
Write-Host ''
Write-Host '提示：容器内用  cs ark / cs deepseek / cs show  切换模型后端'
Write-Host ''

# 清理已退出的旧工作站容器（保留运行中的，支持多开并行）
docker ps -aq -f 'name=super-claude-station' -f 'status=exited' 2>$null | ForEach-Object { docker rm $_ 2>$null | Out-Null }

function Build-Image {
    if (-not (Test-Path "$ScriptDir\Dockerfile")) {
        Write-Host "[错误] 在 $ScriptDir 未找到 Dockerfile。" -ForegroundColor Red
        exit 1
    }
    $cacheFlag = ''
    $mirrorArg = 'USE_CN_MIRROR=1'
    $nodeArg = 'NODE_IMAGE=docker.m.daocloud.io/library/node:20-slim'
    $uc = Read-Host '构建是否使用缓存? [Y/n]（n=--no-cache 全新构建）'
    if ($uc -match '^[nN]') { $cacheFlag = '--no-cache' }
    $um = Read-Host '是否使用国内镜像源(基础镜像daocloud/apt清华/npm淘宝)? [Y/n]'
    if ($um -match '^[nN]') { $mirrorArg = 'USE_CN_MIRROR=0'; $nodeArg = 'NODE_IMAGE=node:20-slim' }
    Write-Host "正在构建镜像: $Image  ($mirrorArg) $cacheFlag ..."
    $buildArgs = @('build')
    if ($cacheFlag) { $buildArgs += $cacheFlag }
    $buildArgs += @('--build-arg', $mirrorArg, '--build-arg', $nodeArg, '-t', $Image, $ScriptDir)
    & docker @buildArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[错误] 构建失败，退出码 $LASTEXITCODE。中止。" -ForegroundColor Red
        exit 1
    }
    Write-Host "构建完成: $Image"
}

function Ask-RunNow {
    $ab = Read-Host '构建成功，是否立即运行容器? [Y/n]（n=退出）'
    if ($ab -match '^[nN]') { exit 0 }
}

# 镜像检测
docker image inspect $Image 2>$null | Out-Null
$imgExists = ($LASTEXITCODE -eq 0)

if (-not $imgExists) {
    Write-Host "未找到镜像 $Image，开始构建..."
    Build-Image
    Ask-RunNow
} else {
    Write-Host "已存在同名镜像: $Image"
    Write-Host '   [1] 直接运行现有镜像（默认）'
    Write-Host '   [2] 删除旧镜像并重新构建（避免悬空 <none> 镜像）'
    Write-Host '   [3] 用新镜像名构建运行（保留旧镜像）'
    $choice = Read-Host '请选择 [1/2/3，默认 1]'
    switch ($choice) {
        '2' { Write-Host "删除旧镜像 $Image ..."; docker rmi -f $Image 2>$null | Out-Null; Build-Image; Ask-RunNow }
        '3' { $ni = Read-Host '输入新镜像名 (如 super-claude:v2)'; if ($ni) { $Image = $ni }; Build-Image; Ask-RunNow }
        default { Write-Host '使用现有镜像。' }
    }
}

# 代理网络配置（容器内建 Mihomo TUN）
$ProxyEnabled = $false
Write-Host ''
Write-Host '------------------------------------------'
Write-Host ' 代理网络配置（容器内 Mihomo TUN）'
Write-Host '------------------------------------------'
$pc = Read-Host '是否需要配置代理网络以访问国际网络(如 Anthropic API)? [y/N]'
if ($pc -match '^[yY]') {
    Write-Host '  1) 本地文件 — 输入本地配置文件绝对路径'
    Write-Host '  2) 网络链接 — 输入订阅链接 / 配置直链 URL'
    $mode = Read-Host '选择 [1/2，默认 2]'
    if (-not $mode) { $mode = '2' }
    $mihomoDir = "$ScriptDir\.claude\mihomo"
    $cfg = "$mihomoDir\config.yaml"
    New-Item -ItemType Directory -Force -Path $mihomoDir | Out-Null
    if ($mode -eq '1') {
        $src = Read-Host '本地配置文件绝对路径'
        if (-not (Test-Path $src)) {
            Write-Host "[错误] 文件不存在: $src" -ForegroundColor Red
        } else {
            Copy-Item $src $cfg -Force
            $ProxyEnabled = $true
        }
    } else {
        $url = Read-Host '配置 URL'
        if (-not $url) {
            Write-Host '[错误] URL 为空' -ForegroundColor Red
        } else {
            Write-Host '下载配置中...'
            & curl.exe -fsSL $url -o $cfg 2>$null
            if ($LASTEXITCODE -ne 0 -or -not (Test-Path $cfg) -or (Get-Item $cfg).Length -eq 0) {
                Write-Host 'curl 失败，改用 PowerShell 重试...'
                try { Invoke-WebRequest -Uri $url -OutFile $cfg -UseBasicParsing } catch {
                    Write-Host "[错误] 下载失败: $($_.Exception.Message)" -ForegroundColor Red
                }
            }
            if ((Test-Path $cfg) -and (Get-Item $cfg).Length -gt 0) {
                $ProxyEnabled = $true
            } else {
                Write-Host '[错误] 下载失败或内容为空' -ForegroundColor Red
            }
        }
    }
    if ($ProxyEnabled) { Write-Host "代理配置已就绪: $cfg（格式由容器内自动识别/转换）" }
} else {
    Write-Host '跳过代理，容器直连网络。'
}

# 启动容器
Write-Host ''
Write-Host '正在启动容器...'
$runArgs = @('run', '-it', '--rm', '-e', 'TERM=xterm-256color', '--name', $Name, '-v', "$($PWD):/home/AISC/app")
if ($ProxyEnabled) {
    Write-Host '已启用容器内 TUN 透明代理（NET_ADMIN + /dev/net/tun）...'
    $runArgs += @('--cap-add=NET_ADMIN', '--device=/dev/net/tun', '-v', "$ScriptDir\.claude\mihomo\config.yaml:/etc/mihomo/config.yaml:ro")
}
$runArgs += $Image
& docker @runArgs
