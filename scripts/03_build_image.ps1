# scripts/03_build_image.ps1 — 镜像检测 + 构建菜单 → state(IMAGE, DO_RUN)
#   DO_RUN=1 运行(默认) / 0 构建后选"不运行" → 04 跳过 docker run
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
. "$PSScriptRoot\_state.ps1"
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$Image = Get-State -Key 'IMAGE'
if (-not $Image) { $Image = 'super-claude:latest' }

Write-Host '📦 [3/4] 镜像构建...'

function Build-Image {
    if (-not (Test-Path "$ProjectRoot\image\Dockerfile")) {
        Write-Host "[错误] 未找到 Dockerfile: $ProjectRoot\image\Dockerfile" -ForegroundColor Red
        exit 1
    }
    $cacheFlag = ''
    $mirrorArg = 'USE_CN_MIRROR=1'
    $nodeArg = 'NODE_IMAGE=docker.m.daocloud.io/library/node:20-slim'
    $uc = Read-Host '构建是否使用缓存? [Y/n]（n=--no-cache 全新构建）'
    if ($uc -match '^[nN]') { $cacheFlag = '--no-cache' }
    $um = Read-Host '是否使用国内镜像源(基础镜像daocloud/apt清华/npm淘宝)? [Y/n]'
    if ($um -match '^[nN]') { $mirrorArg = 'USE_CN_MIRROR=0'; $nodeArg = 'NODE_IMAGE=node:20-slim' }
    Write-Host "📦 正在构建镜像: $Image  ($mirrorArg) $cacheFlag ..."
    $buildArgs = @('build')
    if ($cacheFlag) { $buildArgs += $cacheFlag }
    $buildArgs += @('-f', "$ProjectRoot\image\Dockerfile", '--build-arg', $mirrorArg, '--build-arg', $nodeArg, '-t', $Image, "$ProjectRoot\image")
    & docker @buildArgs
    if ($LASTEXITCODE -ne 0) { Write-Host '[错误] 构建失败。' -ForegroundColor Red; exit 1 }
    Write-Host "✅ 构建完成: $Image"
    $ab = Read-Host '构建成功，是否立即运行容器? [Y/n]（n=退出）'
    if ($ab -match '^[nN]') { Set-State -Key 'DO_RUN' -Val '0'; Write-Host '👋 已退出，未启动容器。' }
}

docker image inspect $Image 2>$null | Out-Null
$imgExists = ($LASTEXITCODE -eq 0)

if (-not $imgExists) {
    Write-Host "🔍 未找到镜像 $Image，开始构建..."
    Build-Image
} else {
    Write-Host "⚠️  已存在同名镜像: $Image"
    Write-Host '   [1] 直接运行现有镜像（默认）'
    Write-Host '   [2] 删除旧镜像并重新构建（避免悬空 <none> 镜像）'
    Write-Host '   [3] 用新镜像名构建运行（保留旧镜像）'
    $choice = Read-Host '请选择 [1/2/3，默认 1]'
    switch ($choice) {
        '2' { Write-Host "🗑️  删除旧镜像 $Image ..."; docker rmi -f $Image 2>$null | Out-Null; Build-Image }
        '3' { $ni = Read-Host '输入新镜像名 (如 super-claude:v2)'; if ($ni) { $Image = $ni }; Build-Image }
        default { Write-Host '▶️  使用现有镜像。' }
    }
}

Set-State -Key 'IMAGE' -Val $Image
exit 0
