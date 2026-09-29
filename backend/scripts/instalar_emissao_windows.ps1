# Execute uma vez no PowerShell com o Python do ambiente virtual do projeto.
param([string] $PythonExecutable = "")
$ErrorActionPreference = "Stop"
$backend = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $PythonExecutable) {
    $virtualenv = Join-Path $backend ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $virtualenv -PathType Leaf) {
        $PythonExecutable = $virtualenv
    } else {
        $PythonExecutable = (Get-Command python -ErrorAction Stop).Source
    }
}
if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw "Python nao encontrado. Informe -PythonExecutable com o caminho completo do python.exe."
}
$PythonExecutable = (Resolve-Path -LiteralPath $PythonExecutable).Path
$manage = Join-Path $backend "manage.py"
& $PythonExecutable -c "import django, rest_framework"
if ($LASTEXITCODE -ne 0) {
    throw "O Python escolhido nao possui as dependencias do projeto. Instale requirements.txt nele."
}
& $PythonExecutable $manage check
if ($LASTEXITCODE -ne 0) { throw "A verificacao do Django falhou. Corrija antes de instalar a tarefa." }
& $PythonExecutable $manage migrate --check
if ($LASTEXITCODE -ne 0) { throw "Existem migracoes pendentes. Execute python manage.py migrate antes da instalacao." }

$runner = Join-Path $PSScriptRoot "executar_rotina_windows.ps1"
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) { throw "Script de execucao nao encontrado: $runner" }
$taskName = "GymInsight - Rotina diaria"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument (
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $runner + '" -PythonExecutable "' + $PythonExecutable + '"'
) -WorkingDirectory $backend
$trigger = New-ScheduledTaskTrigger -Daily -At "06:00"
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
# A versao anterior criava uma tarefa separada apenas para mensalidades.
$old = Get-ScheduledTask -TaskName "GymInsight - Mensalidades" -ErrorAction SilentlyContinue
if ($old) {
    $oldAction = @($old.Actions)[0]
    if ($oldAction.Arguments -notmatch 'manage\.py.*emitir_mensalidades') {
        throw "A tarefa GymInsight - Mensalidades foi personalizada. Desative-a antes de instalar a rotina completa para evitar execucao dupla."
    }
}
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Encerra matriculas vencidas e emite cobrancas devidas uma vez ao dia" -Force | Out-Null
if ($old) {
    Unregister-ScheduledTask -TaskName "GymInsight - Mensalidades" -Confirm:$false
    Write-Host "Tarefa antiga de mensalidades substituida pela rotina completa."
}
Write-Host "Tarefa $taskName instalada para as 06:00 (horario local do Windows)."
Write-Host "Python: $PythonExecutable"
Write-Host "Backend: $backend"
Write-Host "Para testar: Start-ScheduledTask -TaskName '$taskName'"
Write-Host 'Para conferir: powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\verificar_rotina_windows.ps1"'
