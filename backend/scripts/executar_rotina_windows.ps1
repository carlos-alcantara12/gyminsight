# Chamado pelo Agendador de Tarefas; preserva um histórico local com saída e falhas.
param([Parameter(Mandatory = $true)][string] $PythonExecutable)
$ErrorActionPreference = "Stop"
$backend = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logs = Join-Path $backend "logs"
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$log = Join-Path $logs "rotina-diaria.log"
$dataInicio = (Get-Date).ToString("o")
$saida = @()
$status = "FALHA"
try {
    if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
        throw "Python configurado na tarefa nao foi encontrado: $PythonExecutable"
    }
    $manage = Join-Path $backend "manage.py"
    # O codigo de saida do Python e propagado ao Agendador. Executar novamente e seguro.
    $saida = & $PythonExecutable $manage rotina_diaria 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "A rotina Django terminou com codigo $LASTEXITCODE."
    }
    $status = "SUCESSO"
} catch {
    $saida += $_.ToString()
} finally {
    $linhas = @("INICIO=$dataInicio") + @($saida | ForEach-Object { $_.ToString() }) + @(
        "FIM=$((Get-Date).ToString('o')) STATUS=$status")
    Add-Content -LiteralPath $log -Value $linhas -Encoding UTF8
}
if ($status -eq "SUCESSO") { exit 0 }
exit 1
