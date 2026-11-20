[CmdletBinding()]
param([switch] $Force)

$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$frontend = Join-Path $project 'frontend'
$assets = Join-Path $project 'resources/workbench'
$outputNames = @('index.html', 'workbench.js', 'workbench.css', 'licenses.txt')
$outputs = @($outputNames | ForEach-Object {
    Get-Item -LiteralPath (Join-Path $assets $_) -ErrorAction SilentlyContinue
})
$inputs = @(Get-ChildItem -LiteralPath (Join-Path $frontend 'src') -File -Recurse)
$inputs += Get-ChildItem -LiteralPath (Join-Path $frontend 'public') -File -Recurse
$inputs += Get-ChildItem -LiteralPath $frontend -File | Where-Object Name -ne '.gitignore'
$licenseScript = Join-Path $project 'packaging/frontend_licenses.mjs'
$inputs += Get-Item -LiteralPath $licenseScript
if (-not $Force -and $outputs.Count -eq $outputNames.Count) {
    $builtAt = (Get-Item -LiteralPath (Join-Path $assets 'licenses.txt')).LastWriteTimeUtc
    if (-not ($inputs | Where-Object LastWriteTimeUtc -gt $builtAt)) { return }
}

$npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $npm) {
    throw '构建 Vue 工作台需要 Node.js 和 npm。运行已构建的 Windows 版时不需要 Node.js。'
}
$cache = Join-Path $project '.work/npm-cache'
$lock = Get-Item -LiteralPath (Join-Path $frontend 'package-lock.json')
$installed = Get-Item -LiteralPath (Join-Path $frontend 'node_modules/.package-lock.json') -ErrorAction SilentlyContinue
if (-not $installed -or $installed.LastWriteTimeUtc -lt $lock.LastWriteTimeUtc) {
    & $npm --prefix $frontend --cache $cache ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "安装锁定的 Vue 依赖失败，退出码 $LASTEXITCODE。" }
}
& $npm --prefix $frontend --cache $cache run build
if ($LASTEXITCODE -ne 0) { throw "构建 Vue 工作台失败，退出码 $LASTEXITCODE。" }
& node.exe $licenseScript $frontend (Join-Path $assets 'licenses.txt')
if ($LASTEXITCODE -ne 0) { throw "生成前端第三方许可证清单失败，退出码 $LASTEXITCODE。" }
