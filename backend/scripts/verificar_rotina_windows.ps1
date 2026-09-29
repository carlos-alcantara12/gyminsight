# Mostra agendamento, resultado da ultima execucao e registro do Django.
$ErrorActionPreference = "Stop"
$taskName = "GymInsight - Rotina diaria"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
$info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction Stop
$backend = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$log = Join-Path $backend "logs\rotina-diaria.log"
Write-Host "Tarefa: $taskName"
Write-Host "Estado: $($task.State)"
Write-Host "Ultima execucao: $($info.LastRunTime)"
Write-Host "Proxima execucao: $($info.NextRunTime)"
Write-Host "Codigo de saida: $($info.LastTaskResult)"
if ($task.State -eq "Disabled") { throw "A tarefa esta desativada." }
if ($task.State -eq "Running") { throw "A tarefa ainda esta em execucao; confira novamente quando terminar." }
if ($info.LastRunTime.Year -lt 2000) { throw "A tarefa ainda nao foi executada. Teste-a com Start-ScheduledTask." }
if ($info.LastTaskResult -ne 0) { throw "A ultima execucao falhou. Consulte o registro em $log." }
if (-not (Test-Path -LiteralPath $log -PathType Leaf)) { throw "Nao foi encontrado o registro da execucao em $log." }
$ultima = (Get-Content -LiteralPath $log -Tail 1).Trim()
if ($ultima -notmatch '^FIM=(\S+) STATUS=SUCESSO$') { throw "O registro nao confirma o sucesso da ultima execucao: $ultima" }
$termino = [DateTimeOffset]::Parse($Matches[1]).LocalDateTime
if (($termino - $info.LastRunTime).TotalMinutes -lt -2) {
    throw "O registro e anterior a ultima execucao do Agendador; confira novamente."
}
if (((Get-Date) - $termino).TotalHours -gt 36) { throw "A ultima execucao confirmada ocorreu ha mais de 36 horas." }
Write-Host "Confirmado: $ultima"
Write-Host "Registro: $log"
