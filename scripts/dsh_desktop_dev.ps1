# DSH Desktop 开发启动器（BNOS 侧）——一键拉起桌面客户端

# 用途：把 DSH Desktop 的开发启动环境固化，避免每次手敲 chcp + 环境变量。
# 解决的三个环境问题：
#   1. yarn 4 在中文路径下 bin 执行乱码     -> 启动前 chcp 65001
#   2. corepack 缓存目录被沙箱拦截          -> COREPACK_HOME 重定向到 ~/.cache
#   3. DSH 的 ~/.dsh 与 %APPDATA%\DSH Desktop 被沙箱拦截 -> DSH_HOME / userData 重定向

param(
  # 默认走 `corepack yarn dev`（全量构建 + 启动）；加 -Quick 直接跑已构建好的 lib/bin.js
  [switch]$Quick,
  # 代理地址（HTTP/HTTPS）。留空表示沿用当前环境已有的 HTTP_PROXY/HTTPS_PROXY，不额外设置
  [string]$Proxy
)

$ErrorActionPreference = 'Stop'
$dshDesktop = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'dsh_desktop'

if (-not (Test-Path (Join-Path $dshDesktop 'package.json'))) {
  throw "未找到 dsh_desktop（$dshDesktop），请先 clone anywhere-labs/deepseek-harness-desktop 到该目录"
}

# --- 环境变量注入 ---
if ($Proxy) {
  $env:HTTP_PROXY  = $Proxy
  $env:HTTPS_PROXY = $Proxy
}
if (-not $env:COREPACK_HOME) {
  $env:COREPACK_HOME = Join-Path $env:USERPROFILE '.cache\node\corepack'
}
if (-not $env:DSH_HOME) {
  $env:DSH_HOME = Join-Path $env:USERPROFILE '.cache\dsh-home'
}
if (-not $env:DSH_DESKTOP_USER_DATA_DIR) {
  $env:DSH_DESKTOP_USER_DATA_DIR = Join-Path $env:USERPROFILE '.cache\dsh-desktop-data'
}

# --- 中文路径 bug：yarn 生成的 .cmd shim 用 UTF-8 存、cmd 按 GBK 解码 ---
chcp 65001 | Out-Null

Set-Location $dshDesktop
Write-Host "[dsh-desktop] DSH_HOME=$env:DSH_HOME"
Write-Host "[dsh-desktop] userData=$env:DSH_DESKTOP_USER_DATA_DIR"

# --- 本地 userData 补丁：dsh_desktop 是 pinned 上游，此改动不进上游 git ---
#    在非 -Quick 模式下跑 yarn dev 会重编译 lib/bin.js，需保证补丁已打在
#    src/bin.ts，否则重编译会丢 userData 支持。补丁内容与 scripts/dsh_desktop_userdata.patch 一致。
$binTsSource = Join-Path $dshDesktop 'dsh-plugin-desktop\src\bin.ts'
$hasUserDataPatch = (Select-String -Path $binTsSource -Pattern 'DSH_DESKTOP_USER_DATA_DIR' -ErrorAction SilentlyContinue) -ne $null
if (-not $hasUserDataPatch) {
  $patchFile = Join-Path $PSScriptRoot 'dsh_desktop_userdata.patch'
  if (Test-Path $patchFile) {
    Write-Host "[dsh-desktop] 应用本地 userData 补丁到 src/bin.ts"
    git -C $dshDesktop apply --whitespace=nowarn $patchFile
    if ($LASTEXITCODE -ne 0) { throw "userData 补丁应用失败（可能已手动改动 src/bin.ts，请手动核对）" }
  }
}

if ($Quick) {
  node (Join-Path $dshDesktop 'dsh-plugin-desktop\lib\bin.js')
} else {
  corepack yarn dev
}
