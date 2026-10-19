# Shared, project-relative PowerShell 7 build environment. Dot-source from scripts/.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:ProjectRoot = Split-Path -Parent $PSScriptRoot

function Initialize-ProjectEnvironment([string] $Task) {
    if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 (pwsh) is required.' }
    $work = Join-Path $script:ProjectRoot ('.work/' + $Task)
    $temporary = Join-Path $work 'tmp'
    New-Item -ItemType Directory -Path $temporary -Force | Out-Null
    $env:TEMP = $temporary
    $env:TMP = $temporary
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:UV_CACHE_DIR = Join-Path $script:ProjectRoot '.tools/uv-cache'
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $work 'pyinstaller-cache'
    $command = Get-Command uv -ErrorAction SilentlyContinue
    $script:Uv = if ($command) { $command.Source } else { Join-Path $script:ProjectRoot '.tools/uv-bootstrap/bin/uv.exe' }
    if (-not (Test-Path -LiteralPath $script:Uv -PathType Leaf)) {
        throw 'uv was not found. Install uv or put its bootstrap at .tools/uv-bootstrap/bin/uv.exe; run uv sync --locked first.'
    }
    return $work
}

function Invoke-Uv([string[]] $Arguments) {
    & $script:Uv @Arguments
    if ($LASTEXITCODE -ne 0) { throw "uv failed with exit code $LASTEXITCODE" }
}
