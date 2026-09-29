
### Faturamento consolidado das unidades

Na seção **Financeiro**, a tabela **Faturamento consolidado por unidade** mostra todas as unidades ativas às quais o gerente tem acesso, destaca a unidade selecionada e apresenta uma linha **Total da rede autorizada**. Para cada unidade, exibe matrículas atualmente ativas cujo período atravessa a competência, matrículas sem cobrança válida emitida naquele mês, número de cobranças, faturamento previsto, recebido, em aberto e vencido. `GET /api/pagamentos/consolidado/?competencia=AAAA-MM` fornece os mesmos valores. Atendentes não acessam o relatório. A consulta não altera pagamentos nem emite cobranças.

Os valores são somados a partir de cobranças efetivamente emitidas para as matrículas dos alunos da unidade na competência; cobranças canceladas não contam. **Matrículas sem cobrança não entram no faturamento previsto**. Matrículas posteriormente canceladas ou encerradas podem manter cobranças históricas já emitidas; por isso sua contagem de matrículas vigentes hoje pode diferir da quantidade de cobranças daquela competência. O consolidado é por competência, enquanto o indicador de entrada no caixa da visão individual continua sendo uma métrica distinta.

### Agendamento e conferência no Windows

Na pasta `backend`, após `python manage.py migrate`, execute `powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\instalar_emissao_windows.ps1"`. A tarefa **GymInsight - Rotina diaria** executa `python manage.py rotina_diaria` às 06:00 no horário do Windows: encerra matrículas vencidas, atualiza alunos, renova os contratos quitados e emite somente as cobranças devidas. Teste com `Start-ScheduledTask -TaskName "GymInsight - Rotina diaria"` e, depois que terminar, execute `powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\verificar_rotina_windows.ps1"`. O histórico fica em `backend\logs\rotina-diaria.log`. Consulte o README principal para instruções de troca de pasta, Python e sessão do Windows.

### Quitação manual por Pix e cartão

Depois de `python manage.py migrate` (migração `0015`), o gerente marca a cobrança como **paga** na aba **Financeiro** e escolhe Pix ou cartão. O sistema registra data, responsável e valor integral; não processa transações nem armazena dados do cartão. A forma escolhida aparece ao lado da cobrança e os relatórios separam os valores recebidos por método. Registros antigos quitados sem forma cadastrada permanecem identificados como históricos sem informação.
