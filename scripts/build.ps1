[CmdletBinding()]
param(
    [ValidatePattern('^[0-9A-Za-z][0-9A-Za-z._-]*$')][string] $Version = '',
    [string] $OutputRoot = 'dist',
    [switch] $SkipVerify
)
. (Join-Path $PSScriptRoot '../packaging/common.ps1')
$bundleName = 'ArknightsUnpacker'
try {
    if (-not $IsWindows) { throw 'The Windows portable bundle must be built on Windows x64.' }
    $taskId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    $work = Initialize-ProjectEnvironment ('build/' + $taskId)
    Push-Location $script:ProjectRoot
    try {
        if (-not $Version) {
            $Version = (& $script:Uv run --locked --no-sync python -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])').Trim()
            if ($LASTEXITCODE -ne 0 -or $Version -notmatch '^[0-9A-Za-z][0-9A-Za-z._-]*$') { throw 'Cannot read project version.' }
        }
        $output = [IO.Path]::GetFullPath((Join-Path $script:ProjectRoot $OutputRoot))
        $versionRoot = Join-Path $output $Version
        if (Test-Path -LiteralPath $versionRoot) { throw "Output already exists; retain it and use a new version or OutputRoot: $versionRoot" }
        if (-not $SkipVerify) {
            & (Join-Path $PSScriptRoot 'verify.ps1')
            if ($LASTEXITCODE -ne 0) { throw "Verification failed: $LASTEXITCODE" }
            # verify.ps1 has its own workspace; restore this build's cache and TEMP.
            $null = Initialize-ProjectEnvironment ('build/' + $taskId)
        }
        $sourceSnapshot = Join-Path $work 'source-files.json'
        Invoke-Uv @('run', '--locked', '--no-sync', 'python', '-X', 'utf8', 'packaging/release_manifest.py', '--capture-source', $sourceSnapshot)
        Invoke-Uv @('run', '--locked', '--no-sync', 'python', '-X', 'utf8', '-m', 'PyInstaller', '--noconfirm', '--distpath', (Join-Path $work 'dist'), '--workpath', (Join-Path $work 'pyinstaller'), 'packaging/ArknightsUnpacker.spec')
        $bundle = Join-Path $work "dist/$bundleName"
        if (-not (Test-Path -LiteralPath (Join-Path $bundle "$bundleName.exe") -PathType Leaf)) { throw 'PyInstaller did not produce the expected executable.' }
        Copy-Item -LiteralPath (Join-Path $script:ProjectRoot 'packaging/PORTABLE_README.txt') -Destination (Join-Path $bundle '开始使用.txt')
        Copy-Item -LiteralPath (Join-Path $script:ProjectRoot 'docs/USER_GUIDE.md') -Destination (Join-Path $bundle '使用指南.md')
        Copy-Item -LiteralPath (Join-Path $script:ProjectRoot 'docs/THIRD_PARTY_NOTICES.md') -Destination (Join-Path $bundle '第三方说明.md')
        Invoke-Uv @('run', '--locked', '--no-sync', 'python', '-X', 'utf8', 'packaging/release_manifest.py', '--bundle', $bundle, '--version', $Version, '--task-id', $taskId, '--source-snapshot', $sourceSnapshot)
        New-Item -ItemType Directory -Path $versionRoot | Out-Null
        Move-Item -LiteralPath $bundle -Destination (Join-Path $versionRoot $bundleName)
        Write-Host "Built bundle (runtime acceptance remains required): $versionRoot/$bundleName"
    } finally { Pop-Location }
} catch { Write-Error $_ -ErrorAction Continue; exit 1 }
