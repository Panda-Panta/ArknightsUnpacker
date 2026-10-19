[CmdletBinding()]
param([switch] $IncludeLocal, [string[]] $TestPath = @('tests'))
. (Join-Path $PSScriptRoot '../packaging/common.ps1')
try {
    $id = 'verify/' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    $work = Initialize-ProjectEnvironment $id
    Push-Location $script:ProjectRoot
    try {
        Invoke-Uv @('run', '--locked', '--no-sync', 'python', '-X', 'utf8', '-m', 'compileall', '-q', 'src', 'packaging/entrypoint.py')
        $arguments = @('run', '--locked', '--no-sync', 'python', '-X', 'utf8', '-m', 'pytest', '-ra', '--basetemp', (Join-Path $work 'pytest'))
        if (-not $IncludeLocal) { $arguments += @('-m', 'not local') }
        Invoke-Uv ($arguments + $TestPath)
        Write-Host "Verification passed. Temporary evidence: $work"
    } finally { Pop-Location }
} catch { Write-Error $_ -ErrorAction Continue; exit 1 }
