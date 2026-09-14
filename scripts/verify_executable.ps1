[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$executablePath = Join-Path $projectRoot 'dist/PDFModder/PDFModder.exe'
$expectedHash = (Get-FileHash -LiteralPath $executablePath -Algorithm SHA256).Hash.ToLowerInvariant()
$runs = @(
    @{ Name = 'extended'; Flag = '--smoke-extended' },
    @{ Name = 'tagged'; Flag = '--smoke-tagged' },
    @{ Name = 'clipped'; Flag = '--smoke-clipped' },
    @{ Name = 'v08'; Flag = '--smoke-v08' }
)
foreach ($run in $runs) {
    $relativeReport = 'output/packaged-' + $run.Name + '-smoke.json'
    $reportPath = Join-Path $projectRoot $relativeReport
    $started = [DateTime]::UtcNow
    $process = Start-Process -FilePath $executablePath -ArgumentList @($run.Flag, $relativeReport) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(60000)) {
        throw ('El recorrido ' + $run.Name + ' no terminó en 60 segundos. PID: ' + $process.Id)
    }
    if ($process.ExitCode -ne 0) {
        throw ('El ejecutable falló en ' + $run.Name + ' con código ' + $process.ExitCode + '. Consulte ' + $relativeReport)
    }
    $reportFile = Get-Item -LiteralPath $reportPath
    if ($reportFile.LastWriteTimeUtc -lt $started) { throw ('El informe no es de esta ejecución: ' + $relativeReport) }
    $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
    if (-not $report.ok -or -not $report.frozen -or $report.stage -ne 'complete' -or $report.exe_sha256 -ne $expectedHash) {
        throw ('Informe no válido: ' + $relativeReport)
    }
    [PSCustomObject]@{ Recorrido=$run.Name; Pasos=$report.steps.Count; Segundos=$report.elapsed_seconds; Version=$report.app_version; SHA256=$report.exe_sha256 } | ConvertTo-Json -Compress
}
if ((Get-FileHash -LiteralPath $executablePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
    throw 'El ejecutable cambió durante las comprobaciones.'
}
