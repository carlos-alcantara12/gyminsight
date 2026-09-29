# Modelagem do banco de dados — GymInsight

Esta é a modelagem **lógica e física da implementação atual**. O banco configurado em `backend/config/settings.py` é SQLite, criado pelas migrações Django `core/0001` a `core/0009` e pelas migrações nativas de autenticação. O [DER](DER.md) mostra as cardinalidades. A migração Django é a fonte de verdade para criar ou alterar o banco; não aplique SQL manualmente em instalações existentes.

## Convenções

- Todas as nove tabelas operacionais `core_*` têm `id` como chave primária gerada pelo Django (`BigAutoField` no modelo; SQLite armazena a chave como `INTEGER PRIMARY KEY`).
- As chaves `*_id` são `ForeignKey`, exceto `funcionario.usuario_id`, que é `OneToOneField` e também único. Campos FK sem `NULL` são obrigatórios.
- `Vazio` na tabela significa string vazia aceita, **não** `NULL`. `NULL` identifica uma coluna opcional de fato.
- `DateTimeField` usa o fuso do Django (`USE_TZ=True`), com apresentação no fuso configurado `America/Manaus`.

## Dicionário das tabelas

| Tabela | Campo | Tipo no modelo | Obrigatoriedade e finalidade |
| --- | --- | --- | --- |
| `core_unidade` | `nome` | `CharField(150)` | Obrigatório; identificação da unidade. |
|  | `endereco` | `CharField(255)` | Vazio permitido. |
|  | `ativa` | `BooleanField` | Obrigatório; padrão `True`. |
|  | `categoria` | `CharField(12)` | Tradicional, Premium ou Diamante; padrão Tradicional. |
|  | `abre_domingo`, `abre_feriado` | `BooleanField` | Padrão `False`. |
|  | `domingo_inicio`, `domingo_fim`, `feriado_inicio`, `feriado_fim` | `TimeField` | Obrigatórios em pares quando há abertura na data especial. |
| `core_feriado` | `unidade_id`, `data` | `ForeignKey`, `DateField` | Par único por unidade e data; calendário cadastrado manualmente. |
|  | `nome`, `abre`, `inicio`, `fim` | `CharField`, `BooleanField`, `TimeField` | Abertura e horário excepcionais; `NULL` usa o padrão da unidade. |
| `core_funcionario` | `usuario_id` | `OneToOneField(auth_user)` | Opcional e único; só gerente e atendente podem ter conta. |
|  | `unidade_id` | `ForeignKey(core_unidade)` | Obrigatório; define a lotação e o acesso à unidade. |
|  | `nome`, `email` | `CharField(150)`, `EmailField` | Nome obrigatório; e-mail opcional. |
|  | `cargo` | `CharField(12)` | Gerente, atendente, professor, faxineiro ou outro. |
|  | `ativo` | `BooleanField` | Funcionário ativo ou inativo. |
| `core_funcionario_unidades_acesso` | `funcionario_id`, `unidade_id` | `ManyToManyField` | Unidades adicionais autorizadas a um gerente. |
| `core_aluno` | `unidade_id` | `ForeignKey(core_unidade)` | Obrigatório. |
|  | `nome` | `CharField(150)` | Obrigatório. |
|  | `email` | `EmailField(254)` | Vazio permitido. |
|  | `telefone` | `CharField(25)` | Vazio permitido. |
|  | `data_nascimento` | `DateField` | `NULL` permitido. |
|  | `cadastrado_em` | `DateTimeField` | Obrigatório; definido no cadastro. |
|  | `status` | `CharField(10)` | `ativo`, `inativo` ou `cancelado`; padrão `inativo`. |
| `core_plano` | `unidade_id` | `ForeignKey(core_unidade)` | Obrigatório. |
|  | `nome` | `CharField(100)` | Obrigatório; único dentro da unidade. |
|  | `categoria`, `acesso_tradicional_rede` | `CharField(12)`, `BooleanField` | Categoria do plano e opção contratual Tradicional para outras unidades da mesma categoria. |
|  | `duracao_dias` | `PositiveIntegerField` | Obrigatório; mínimo funcional de 1 dia. |
|  | `preco` | `DecimalField(10,2)` | Obrigatório; mínimo funcional de zero. |
|  | `ativo` | `BooleanField` | Obrigatório; padrão `True`. |
| `core_matricula` | `aluno_id` | `ForeignKey(core_aluno)` | Obrigatório. |
|  | `plano_id` | `ForeignKey(core_plano)` | Obrigatório. |
|  | `valor_contratado` | `DecimalField(10,2)` | Preço fixado na contratação; `NULL` apenas em contratos históricos ainda não conferidos. |
|  | `matricula_anterior_id` | `OneToOneField(core_matricula)` | Vínculo opcional e único de renovação. |
|  | `categoria_acesso`, `acesso_tradicional_rede` | `CharField(12)`, `BooleanField` | Direitos de acesso preservados na matrícula. |
|  | `inicio`, `fim` | `DateField` | Obrigatórios; último dia é inclusivo. |
|  | `status` | `CharField(10)` | `ativa`, `encerrada` ou `cancelada`; padrão `ativa`. |
|  | `motivo_cancelamento` | `TextField` | Vazio permitido no banco; exigido na operação de cancelamento. |
|  | `criada_em` | `DateTimeField` | Obrigatório; definido no cadastro. |
| `core_frequencia` | `matricula_id` | `ForeignKey(core_matricula)` | Obrigatório; uma linha por entrada. |
|  | `unidade_id` | `ForeignKey(core_unidade)` | Local da entrada; opcional no banco para compatibilidade legada. |
|  | `entrada_em` | `DateTimeField` | Obrigatório; instante da entrada. |
|  | `registrada_por_id` | `ForeignKey(auth_user)` | `NULL` permitido; usuário responsável quando disponível. |
| `core_pagamento` | `matricula_id` | `ForeignKey(core_matricula)` | Obrigatório. |
|  | `valor` | `DecimalField(10,2)` | Obrigatório; mínimo funcional de zero. |
|  | `vencimento` | `DateField` | Obrigatório. |
|  | `pago_em` | `DateTimeField` | `NULL` permitido; exigido ao marcar como pago. |
|  | `status` | `CharField(10)` | `pendente`, `pago` ou `cancelado`; padrão `pendente`. |
| `core_logauditoria` | `unidade_id` | `ForeignKey(core_unidade)` | Obrigatório. |
|  | `usuario_id` | `ForeignKey(auth_user)` | `NULL` permitido. |
|  | `ocorrido_em` | `DateTimeField` | Obrigatório; definido na criação. |
|  | `acao` | `CharField(12)` | Operação auditada, por exemplo `criado`, `alterado`, `excluido`, `exportado`. |
|  | `entidade`, `objeto_id` | `CharField(60)`, `CharField(40)` | Identificação textual do objeto auditado, sem FK polimórfica. |
|  | `campos_alterados` | `JSONField` | Lista de nomes de campos; padrão lista vazia. |

## Restrições efetivamente impostas pelo banco

| Restrição | Definição |
| --- | --- |
| Chaves primárias e estrangeiras | IDs únicos por tabela; vínculos obrigatórios apontam para registros existentes quando as FKs do SQLite estão habilitadas pelo Django. |
| Feriado por unidade e data | `UNIQUE (unidade_id, data)` em `core_feriado`. |
| Conta por funcionário | `core_funcionario.usuario_id` é `UNIQUE`. |
| Nome do plano por unidade | Restrição `UNIQUE (unidade_id, nome)` em `core_plano`. |
| Uma matrícula ativa por aluno | Índice único parcial `uma_matricula_ativa_por_aluno`: `UNIQUE(aluno_id) WHERE status = 'ativa'`. |
| Duração não negativa | A coluna SQLite `duracao_dias` tem `CHECK (duracao_dias >= 0)` por ser `PositiveIntegerField`; o mínimo de **1** só é aplicado na validação da aplicação. |

As chaves estrangeiras ganham índices padrão do Django; há índices em `unidade_id`, `aluno_id`, `plano_id`, `matricula_id` e nos vínculos com usuário conforme cada tabela. `core_funcionario.usuario_id` e `(core_plano.unidade_id, core_plano.nome)` têm índices de unicidade; o índice parcial também acelera a consulta da matrícula ativa. Não há índices adicionais de período em `entrada_em`, de modo que relatórios de frequência com volume alto devem ser medidos antes de otimizar.

## Regras garantidas pela aplicação, não pelo esquema

- Cadastrar um aluno junto de sua primeira matrícula; o banco permite aluno sem matrícula quando criado diretamente.
- Escolher plano ativo da **mesma unidade** do aluno; o banco garante somente que cada FK aponta para um registro existente.
- Calcular `fim = inicio + duracao_dias - 1`, impedir data final anterior ao início e rejeitar contratação já vencida.
- Exigir motivo no cancelamento, proibir alterações indevidas de status e sincronizar o status do aluno com matrículas válidas.
- Exigir matrícula ativa e dentro da validade no instante de cada entrada; impedir entradas em domingos e feriados fechados ou fora do horário especial; definir operador e horário no serviço de registro.
- Exigir `pago_em` quando o pagamento estiver `pago`; validar preço e valor não negativos e duração mínima de um dia.
- Restringir leitura e escrita à unidade e às permissões do usuário na API. Isso **não** é isolamento físico entre bancos ou esquemas.

Código que grave diretamente por SQL, `QuerySet.update()` ou `objects.create()` sem passar pelos serviços e `full_clean()` pode contornar parte dessas regras e da auditoria. Integrações devem usar os serviços do projeto.

## Autenticação, migração e operação

As contas e permissões residem nas tabelas nativas do Django (`auth_user`, `auth_group`, `auth_permission` e suas associações). `auth_user` inclui outros campos além dos resumidos no DER, como hash de senha. O projeto não mantém senhas em tabelas `core_*`.

Para criar o banco: `python manage.py migrate` e depois `python manage.py configurar_grupos`. Para verificar alterações de modelos sem migração: `python manage.py makemigrations --check --dry-run`. O projeto usa SQLite atualmente; antes de um banco de produção, planeje migração de dados, concorrência, testes de integridade, controle de acesso e rotina de backup específica. Consulte [backup e restauração](README.md#backup-e-recuperação-do-sqlite) e [proteção de dados](LGPD.md).

A migração `0007` remove a avaliação física do modelo ativo e preserva a tabela antiga sob o nome `core_avaliacaofisica_arquivo`; ela não faz parte do esquema operacional.

A migração `0008` copia professores e vínculos de perfis de usuário para `core_funcionario` antes de retirar as duas tabelas antigas. O modelo de funcionário tem cinco cargos, porém apenas Gerente e Atendente podem ter login.

A migração `0009` acrescenta a categoria da unidade, horários especiais, o calendário de feriados e a associação de unidades adicionais a gerentes. A unidade original do funcionário permanece como lotação e acesso inicial.
