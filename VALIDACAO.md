# Validação técnica do GymInsight

## Unidades e horários especiais — 25/09/2026

A migração `0009` inclui categorias Tradicional/Premium/Diamante, horários especiais por unidade, calendário manual de feriados e associações adicionais para gerentes. O gerente administra unidades autorizadas, consulta indicadores por unidade e usa o seletor para trabalhar nos demais módulos; o atendente permanece na unidade de lotação. A consulta de funcionamento dá prioridade ao feriado cadastrado sobre domingo, e o serviço de presença rejeita unidades fechadas e horários especiais fora da faixa.

## Equipe e acesso — 25/09/2026

A migração `0008` substitui Professor e PerfilUsuario por Funcionario (Gerente, Atendente, Professor, Faxineiro, Outro), migrando vínculos existentes. O endpoint de funcionários usa limites por unidade; somente gerentes alteram o cadastro. Contas com cargo Professor ou Faxineiro não recebem acesso operacional. A avaliação física permanece removida da aplicação e eventual tabela histórica é um arquivo isolado.

## Escopo de gestão — 25/09/2026

- `python manage.py test core`: 61 testes passaram; incluem isolamento por unidade, papéis de acesso, CSRF, cadastro, matrículas, entradas, relatórios e ausência do endpoint de avaliação física.
- `python manage.py check` e `python manage.py makemigrations --check --dry-run`: sem problemas ou migrações pendentes.
- `node --check ../frontend/js/app.js`: sintaxe válida.
- Banco de demonstração: migração `0009` aplicada, apenas dois grupos, 10 alunos, 10 matrículas, 10 entradas, um funcionário técnico e arquivo clínico vazio; `PRAGMA integrity_check` retornou `ok`, sem falhas em `foreign_key_check`.

A migração conserva dados clínicos anteriores em tabela de arquivo fora do aplicativo. A visão financeira agregada, as regras de acesso dos três planos e as mensalidades por competência são etapas pendentes. Testes locais não substituem validação em ambiente de produção.

## Preço contratado e renovação — 25/09/2026

A migração `0012` adiciona o valor contratado fixo e o vínculo com a matrícula anterior. Matrículas iniciadas emitem uma cobrança com vencimento no início do seu período; as futuras aguardam a rotina diária, inclusive quando a data do fim cai no mês seguinte. Renovações após o término criam outro contrato com preço vigente e cobrança própria. O gerente confirma valores históricos ausentes sem deduzi-los do preço atual; atendentes não podem confirmar preços.

Migração testada sobre **cópia temporária** do banco demonstrativo na `0009`: 10 matrículas antigas mantiveram valor histórico desconhecido, e 10 entradas antigas preservaram a unidade sede. O banco original não foi alterado. Verificação completa: `python manage.py check`, `makemigrations --check --dry-run` e testes da aplicação.

## Emissão automática das mensalidades — 26/09/2026

O comando `emitir_mensalidades` busca contratos iniciados até a data local. Testes cobrem recuperação de cobrança ausente em período encerrado, reexecução sem duplicação, espera de contrato futuro, mês seguinte de um contrato de 30 dias, pagamento legado sem competência, preço histórico sem confirmação e comando executado duas vezes. O banco possui índice único parcial para `(matricula, competencia)`, e a API recusa criar outra cobrança para contrato que já possui pagamentos. O instalador PowerShell agenda execução diária às 06:00 na sessão interativa do Windows; sua execução real no Windows deve ser verificada no Agendador de Tarefas após instalar.
