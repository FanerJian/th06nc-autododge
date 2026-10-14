<#
.SYNOPSIS
  打发布包：PyInstaller onedir → 使用说明 → zip → SHA256SUMS.txt

.DESCRIPTION
  产物：dist\v<版本>\th06nc-autododge-v<版本>-win64.zip
  包里是文件夹版（onedir）：解压双击 exe 即用，不需要装 Python。
  用文件夹版而不是单文件：启动不必解压到临时目录，杀软误报也少得多。

  依赖：numpy（运行必需）、capstone（游戏更新后自动重定位地址用）、PyInstaller（打包用）。
  本地建议用虚拟环境，别装进全局 Python：

    py -3 -m venv --system-site-packages _tmp\buildenv
    _tmp\buildenv\Scripts\python.exe -m pip install pyinstaller
    powershell -ExecutionPolicy Bypass -File tools\build_release.ps1 `
        -PythonExe _tmp\buildenv\Scripts\python.exe -Version 0.1.0

.EXAMPLE
  powershell -File tools\build_release.ps1 -Version 0.1.0
#>
param(
    [string]$Version = '0.1.0',
    [string]$OutRoot = '',
    [string]$PythonExe = '',
    [switch]$NoZip
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$toolsDir = Join-Path $repoRoot 'tools'
$entry = Join-Path $toolsDir 'app_main.py'
$assets = Join-Path $toolsDir 'assets'
$cache = Join-Path $toolsDir 'addr_cache.json'
$appName = 'th06nc-autododge'
$ico = Join-Path $assets 'th06nc.ico'

if ($Version.StartsWith('v')) { $Version = $Version.Substring(1) }
if (-not $OutRoot) { $OutRoot = Join-Path $repoRoot "dist\v$Version" }
$OutRoot = [IO.Path]::GetFullPath($OutRoot)
$workDir = Join-Path $repoRoot '_tmp\pyinstaller'

foreach ($f in @($entry, $ico, $cache)) {
    if (-not (Test-Path -LiteralPath $f)) { throw "缺少必需文件：$f" }
}
if ((Test-Path -LiteralPath $OutRoot) -and (Get-ChildItem -LiteralPath $OutRoot -Force)) {
    throw "输出目录不是空的：$OutRoot（换个 -Version，或先手工删除）"
}

# ---- 定位解释器：优先显式参数，其次 py -3 解析出的真实路径 ----
if (-not $PythonExe) {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $PythonExe = (& py -3 -c "import sys; print(sys.executable)").Trim()
    } else {
        $PythonExe = (Get-Command python -ErrorAction Stop).Source
    }
}
if (-not (Test-Path -LiteralPath $PythonExe)) { throw "解释器不存在：$PythonExe" }
Write-Host "解释器：$PythonExe"

foreach ($mod in @('numpy', 'capstone', 'PyInstaller')) {
    & $PythonExe -c "import $mod" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "缺少模块 $mod —— 先装：`"$PythonExe`" -m pip install $mod"
    }
}

# ---- PyInstaller 构建 ----
# 只把运行期资源显式带进包（图标 + 基线地址表）；诊断工具与项目文档不进包，
# 依赖树由 app_main.py 的 import 关系决定。
New-Item -ItemType Directory -Path $OutRoot -Force | Out-Null
$pyArgs = @(
    '-m', 'PyInstaller',
    '--noconfirm', '--clean',
    '--onedir', '--windowed',
    '--name', $appName,
    '--icon', $ico,
    '--add-data', "$assets;tools/assets",
    '--add-data', "$cache;tools",
    '--distpath', $OutRoot,
    '--workpath', $workDir,
    '--specpath', $workDir,
    $entry
)
& $PythonExe @pyArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败（退出码 $LASTEXITCODE）" }

$pkgDir = Join-Path $OutRoot $appName
$exe = Join-Path $pkgDir "$appName.exe"
if (-not (Test-Path -LiteralPath $exe)) { throw "构建产物缺 exe：$exe" }

# ---- 随包文档 ----
foreach ($doc in @('README.md', 'LICENSE')) {
    $src = Join-Path $repoRoot $doc
    if (Test-Path -LiteralPath $src) { Copy-Item -LiteralPath $src -Destination $pkgDir }
}
$howto = Join-Path $repoRoot '发布\使用说明.txt'
if (Test-Path -LiteralPath $howto) { Copy-Item -LiteralPath $howto -Destination $pkgDir }

# ---- 冒烟：exe 必须能跑起来并给出自检结果（无控制台，结果写 launcher.log）----
# TH06NC_NO_ALERT：自检结果只写日志 —— 弹窗会等人点确定，把构建卡死
$env:TH06NC_NO_ALERT = '1'
$smoke = Start-Process -FilePath $exe -ArgumentList '--check' -PassThru -Wait -WindowStyle Hidden
Remove-Item Env:\TH06NC_NO_ALERT
$logFile = Join-Path $pkgDir 'launcher.log'
if (-not (Test-Path -LiteralPath $logFile)) { throw "冒烟失败：exe 没写出 launcher.log" }
$logText = Get-Content -LiteralPath $logFile -Raw -Encoding UTF8
if ($logText -notmatch '环境自检') { throw "冒烟失败：launcher.log 里没有自检结果`n$logText" }
Write-Host '冒烟通过：exe 可执行，环境自检已写入 launcher.log'
Remove-Item -LiteralPath $logFile -Force

if ($NoZip) { Write-Host "发布目录：$pkgDir"; exit 0 }

# ---- zip（.NET ZipFile：条目名按 UTF-8 写，中文文件名在解压工具里不乱码）----
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = Join-Path $OutRoot "$appName-v$Version-win64.zip"
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
[IO.Compression.ZipFile]::CreateFromDirectory(
    $pkgDir, $zip, [IO.Compression.CompressionLevel]::Optimal, $true)

$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
$sums = Join-Path $OutRoot 'SHA256SUMS.txt'
"$hash *$(Split-Path $zip -Leaf)" | Set-Content -LiteralPath $sums -Encoding ascii

Write-Host ''
Write-Host "发布包：$zip"
Write-Host "校验和：$sums"
Write-Host ("体积：{0:N1} MB" -f ((Get-Item -LiteralPath $zip).Length / 1MB))
# 显式退出码：PyInstaller 把 INFO 日志写 stderr，调用方一旦 `2>&1 | ...` 会被判成失败
exit 0
