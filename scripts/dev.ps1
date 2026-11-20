[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]] $AppArguments = @())
. (Join-Path $PSScriptRoot '../packaging/common.ps1')
try {
    $null = Initialize-ProjectEnvironment ('dev/' + [guid]::NewGuid().ToString('N'))
    Push-Location $script:ProjectRoot
    try {
        if ('--version' -notin $AppArguments -and
            '--smoke-test' -notin $AppArguments -and '--headless-verify' -notin $AppArguments) {
            & (Join-Path $PSScriptRoot 'build-frontend.ps1')
        }
        Invoke-Uv (@('run', '--locked', '--no-sync', 'python', '-X', 'utf8', '-m', 'arknights_unpacker') + $AppArguments)
    }
    finally { Pop-Location }
} catch { Write-Error $_ -ErrorAction Continue; exit 1 }
