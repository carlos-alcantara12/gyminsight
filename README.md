# GymInsight — Django + Django REST Framework

## Rede demonstrativa com 50 alunos (2026)

Uma instalação **nova e vazia** pode ser preparada com `python manage.py migrate`,
`python manage.py configurar_grupos` e `python manage.py criar_rede_demo`, nesta ordem,
dentro de `backend`. O comando cria cinco unidades (Zona Norte, Sul, Oeste,
Centro-Oeste e Sudeste), dez alunos `aluno01` a `aluno50` em cada uma, e os três
planos Tradicional, Premium e Diamante em todas as unidades. Os planos da rede
usam registros locais sincronizados: alterar preço, duração ou disponibilidade
de um deles propaga a alteração às cinco unidades e às futuras unidades;
os contratos anteriores preservam o preço e o prazo acordados. Outros planos
históricos são mantidos e ficam inativos. Não execute esse comando em uma
instalação que contenha dados reais: ele recusa bancos com outras unidades.

Em cada unidade, há três cobranças atrasadas, três matrículas futuras com
cobranças a vencer, duas matrículas canceladas e duas cobranças quitadas.
As matrículas futuras não dão acesso à academia antes da data inicial.
O comando é repetível sem duplicar alunos ou cobranças. O operador técnico
criado para registrar os dados não possui senha e não pode fazer login.

As unidades funcionam de segunda a sexta das 05:00 às 23:00, sábado das
05:00 às 18:00 e nos dez feriados cadastrados das 08:00 às 14:00.
Domingos comuns permanecem fechados. A data de 3 de abril para a Paixão de
Cristo corresponde a **2026**; o comando só prepara os feriados desse ano.
No painel, o cadastro de unidade conserva o campo `Categoria` para as regras
de acesso entre unidades, mas não cria uma aba de categorias de planos.

Para testar a base fictícia que acompanha o ZIP, copie
`demo/GymInsight-demonstracao.sqlite3` para `backend/db.sqlite3` **somente em uma
instalação de demonstração sem banco próprio**. Em seguida crie um superusuário
e vincule-o como gerente conforme `backend/README.md`. Nunca substitua um
`db.sqlite3` existente; aplique as migrações nele para conservar seus dados.

O [DER do banco de dados](DER.md) documenta entidades, cardinalidades e restrições do projeto.
O [modelo do banco de dados](MODELAGEM_BANCO.md) detalha campos, tipos, índices e regras que dependem dos serviços.

Backend do GymInsight em Django e Django REST Framework. Inclui os modelos `Unidade`, `Funcionario`, `Aluno`, `Plano`, `Matricula`, `Frequencia`, `Pagamento` e `LogAuditoria`, painel administrativo em `/admin/` e API em `/api/`.

## Executar no Windows (PowerShell)

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py configurar_grupos
python manage.py createsuperuser
python manage.py vincular_gerente --usuario SEU_USUARIO --unidade "Unidade Central"
python manage.py runserver
```

Abra `http://127.0.0.1:8000/admin/` e entre com o superusuário criado.

O comando `vincular_gerente` cria a unidade inicial se necessário e vincula o superusuário existente a um funcionário com cargo Gerente. Sem esse vínculo, o Admin e a API recusam o acesso. Entre em `http://127.0.0.1:8000/api/auth/login/` com o usuário criado e abra `http://127.0.0.1:8000/api/` para navegar pelos endpoints.

## Executar no Linux ou macOS

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py configurar_grupos
python manage.py createsuperuser
python manage.py vincular_gerente --usuario SEU_USUARIO --unidade "Unidade Central"
python manage.py runserver
```

## API

| Rota | Operações |
| --- | --- |
| `/api/unidades/` | Listar unidades autorizadas; gerente cadastra e altera unidades, categorias e horários especiais |
| `/api/unidades/resumo/` | Visão das unidades autorizadas com alunos, matrículas vigentes, equipe e abertura no dia |
| `/api/unidades/{id}/funcionamento/?data=AAAA-MM-DD` | Consultar se a unidade abre na data e o horário especial |
| `/api/unidades/{id}/selecionar/` | Selecionar unidade ativa autorizada para trabalhar nos demais módulos |
| `/api/feriados/` | Consultar calendário da unidade selecionada; gerente cadastra e edita feriados |
| `/api/alunos/` | Listar, cadastrar com matrícula, consultar e editar alunos |
| `/api/planos/` | Listar, criar, consultar, editar e excluir planos |
| `/api/funcionarios/` | Listar funcionários; gerente cadastra e altera cargos, vínculo de conta e situação |
| `/api/matriculas/` | Listar, criar, consultar, editar e excluir matrículas (exceto a última de cada aluno) |
| `/api/matriculas/{id}/cancelar/` | Cancelar matrícula ativa com motivo obrigatório |
| `/api/frequencias/` | Registrar uma entrada por chamada, listar e consultar registros |
| `/api/pagamentos/` | Listar, criar, consultar, editar e excluir pagamentos |
| `/api/alunos/{id}/frequencia/` | Calcular entradas, dias com presença e distribuição diária; aceita filtros `inicio` e `fim` |
| `/api/alunos/relatorio-frequencia/` | Relatório paginado da frequência de todos os alunos da unidade; filtros `inicio` e `fim` |
| `/api/auditoria/` | Gestores consultam logs de alterações da própria unidade; somente leitura |

As listas retornam resultados paginados (`count`, `next`, `previous` e `results`). A API usa autenticação por sessão: entre pela página de login e use o navegador para testar requisições; escritas feitas por clientes HTTP precisam enviar o cookie de sessão e o token CSRF. Cada atendente vê sua unidade de lotação; o gerente pode selecionar entre a unidade de lotação e as demais unidades autorizadas em seu cadastro de funcionário. IDs de alunos, planos e matrículas de outras unidades são rejeitados mesmo em requisições de criação.

## Permissões dos usuários

Depois de `migrate`, execute `python manage.py configurar_grupos`. **Em instalações existentes, execute `migrate` e depois `configurar_grupos` novamente** para migrar professores e perfis antigos ao cadastro de funcionários. O comando cria os grupos abaixo; executá-lo novamente **redefine** as permissões desses dois grupos para a configuração do projeto. No Admin, crie um usuário, vincule-o a um funcionário Gerente ou Atendente da unidade e atribua o grupo correspondente. Funcionários não precisam da opção **Acesso à equipe** (`is_staff`) para usar a API. O Django Admin é reservado a gerentes superusuários com unidade ativa porque suas telas mostram registros de todas as unidades. Gerentes sem superusuário operam apenas nas unidades autorizadas pela API.

| Grupo | Acesso na API |
| --- | --- |
| GymInsight Gerente | Consulta unidades autorizadas e gerencia unidades, calendário, alunos, planos, funcionários, matrículas, entradas e pagamentos. |
| GymInsight Atendimento | Consulta sua unidade, calendário, alunos, planos, funcionários, matrículas e entradas; cadastra e altera alunos e matrículas, registra entradas e cancela matrículas. Não acessa pagamentos. |

Somente o grupo **GymInsight Gerente** recebe `view_logauditoria` para consultar os logs. Após atualizar uma instalação existente, execute `python manage.py migrate` e `python manage.py configurar_grupos` para atualizar os grupos.

`usuario_tem_permissao` exige usuário ativo, funcionário ativo com cargo de gerente ou atendente vinculado a uma unidade ativa e a permissão Django correspondente à operação e permissão prevista para o papel (`view`, `add`, `change` ou `delete`). Ações especiais têm permissões separadas: cancelar requer **`change_matricula` e `cancelar_matricula`**; registrar presença requer **`add_frequencia`, `registrar_frequencia` e `view_matricula`**. Ambas são verificadas também pelos serviços quando um usuário é informado. Consultar frequência exige leitura de aluno e de entradas. Cadastrar aluno exige ainda criação de matrícula e leitura de plano. Usuários fora dos grupos Gerente e Atendimento, ou sem permissão exigida, recebem **403**. Mesmo com permissão, registros de unidade não autorizada continuam inacessíveis. Superusuários também precisam de um `Funcionario` e de unidade ativa para acessar a API.

Para cadastrar um aluno, envie `nome`, `plano` (ID de um plano ativo da sua unidade) e `inicio` (formato `AAAA-MM-DD`) em `POST /api/alunos/`. Exemplo: `{"nome":"Ana Souza","plano":1,"inicio":"2026-09-24"}`. A unidade vem do usuário autenticado. O serviço `cadastrar_aluno_com_matricula` cria o aluno e a primeira matrícula na mesma transação; o retorno inclui `matricula_ativa_id`. Se faltar o plano ou a data, o cadastro falha sem criar o aluno.

Para experimentar matrículas e frequências sem dados reais, execute `python manage.py criar_dados_demo` depois de `migrate` e `configurar_grupos`. Em banco vazio, o comando cria dez alunos fictícios, dez matrículas válidas e dez entradas, uma por aluno; repeti-lo não duplica esses registros. Há também um [banco SQLite de demonstração separado](demo/README.md) para inspecionar as tabelas. O operador de demonstração não tem senha utilizável: entre com um usuário seu, vinculado à unidade de demonstração, para consultar a API.

Para registrar uma entrada, envie `{"matricula":1}` em `POST /api/frequencias/`. O servidor define `entrada_em` e `registrada_por`. Duas chamadas criam dois registros diferentes, mesmo no mesmo dia. O endpoint permite listar e consultar os registros, sem editar ou excluir; o Admin também mantém esses registros apenas para consulta. O serviço `registrar_entrada(matricula=..., usuario=...)` pode ser usado por futuras integrações de catraca.

Para consultar a frequência calculada, acesse `GET /api/alunos/{id}/frequencia/`. A resposta traz `total_entradas`, `dias_com_presenca`, `ultima_entrada` e `por_dia`, considerando também matrículas anteriores. Para filtrar por datas, use `?inicio=2026-09-01&fim=2026-09-30`; os dois limites são inclusivos e podem ser informados separadamente. Sem filtros, o resultado inclui todo o histórico. A frequência é recalculada a partir dos registros a cada consulta, com datas no fuso configurado no Django, sem contador manual armazenado.

Para cancelar, envie `{"motivo_cancelamento":"Mudança de cidade"}` em `POST /api/matriculas/{id}/cancelar/`. O serviço `cancelar_matricula(matricula=..., motivo=..., usuario=...)` exige usuário autorizado e texto não vazio, cancela a matrícula e recalcula o status do aluno. O motivo e as entradas anteriores permanecem registrados; novas entradas nessa matrícula são bloqueadas. O cancelamento também funciona via `PATCH /api/matriculas/{id}/` com `status: "cancelada"` e `motivo_cancelamento`; ambas as rotas exigem a permissão específica. A API rejeita cancelamento direto em `PATCH /api/alunos/{id}/` e não permite desfazer o cancelamento ou alterar seu motivo.

O status do aluno é calculado por `sincronizar_status_aluno(aluno=...)`: **ativo** se tiver matrícula vigente na data de referência; **cancelado** se não tiver matrícula vigente e a matrícula mais recente estiver cancelada; **inativo** nos demais casos, inclusive antes do início de uma matrícula futura. Cadastro, renovação automática ou manual, cancelamento e vencimento acionam esse serviço. A API recusa alterações manuais no campo `status` do aluno, e o Admin exibe esse campo para leitura. O comando diário `python manage.py encerrar_matriculas` também sincroniza todos os alunos, ativando matrículas cujo dia de início chegou.

## Auditoria

O modelo `LogAuditoria` registra **criado**, **alterado** ou **excluido** para alunos, planos, matrículas, frequências, pagamentos, funcionários e vínculos de conta com unidade. Mudanças nos grupos e nas permissões diretas de um usuário que já tem perfil também geram evento. Cada registro guarda data e hora, unidade, usuário responsável quando conhecido, tipo e ID do objeto e apenas os **nomes** dos campos alterados. Não guarda nomes de alunos, valores de pagamentos, contatos nem motivos de cancelamento. A API e o Admin exibem os logs apenas para leitura, e a API filtra pela unidade do gestor.

Os eventos são salvos no mesmo banco e na mesma transação das operações dos serviços. Chamadas feitas por scripts sem usuário ficam com `usuario` vazio. Operações diretas com `QuerySet.update()` ou SQL não passam pelos sinais do Django e podem escapar à auditoria; integrações devem usar os serviços ou `save()`/`delete()` em instâncias. Estes logs não são imutáveis contra administradores do banco nem substituem backup, monitoramento de erros, logs de acesso e política de retenção. O Django Admin também possui seu próprio histórico de ações administrativas.

## Como os dados se relacionam

- `Unidade` contém alunos, planos, funcionários.
- `Aluno` pode ter várias matrículas ao longo do tempo; o banco permite no máximo uma matrícula com status **ativa** por aluno.
- A API impede excluir a última matrícula e transferir uma matrícula para outro aluno. No Admin, o formulário do aluno exige ao menos uma matrícula e a exclusão direta de matrículas está desabilitada.
- `Matricula` associa aluno e plano da mesma unidade. Tem início, fim e motivo obrigatório em caso de cancelamento.
- O serviço `criar_matricula(aluno=..., plano=..., inicio=...)` centraliza a criação: exige um plano cadastrado e ativo, verifica se pertence à unidade do aluno e valida a matrícula antes de salvá-la. O cadastro inicial de alunos e `POST /api/matriculas/` usam esse mesmo serviço. O campo `plano` também é obrigatório no banco de dados.
- A validade é calculada por `calcular_fim_plano`: `fim = inicio + duracao_dias - 1`. Informar um `fim` diferente gera erro. Plano e datas de matrículas já criadas ficam fixos, preservando o prazo contratado se a duração do plano mudar posteriormente.
- `encerrar_matriculas_vencidas()` transforma matrículas ativas cujo `fim` passou em **encerradas** e inativa alunos sem outra matrícula ativa. Uma renovação pela API também encerra a matrícula vencida do aluno antes de criar a nova. O último dia de validade ainda permite registrar entradas.
- O status de uma matrícula encerrada não pode voltar a **ativa** por `PATCH`; novas contratações devem usar a criação de matrícula. O comando diário informa quantos alunos tiveram o status atualizado na sincronização.
- `Frequencia` registra uma linha por entrada. A quantidade de entradas por período é a frequência calculada; `registrar_entrada` exige matrícula ativa e válida, unidade ativa e usuário da mesma unidade. O registro inclui horário e usuário responsável.
- `cancelar_matricula` exige motivo antes de alterar o status. A validação do modelo também rejeita matrículas canceladas sem motivo. O Admin exibe status e motivo das matrículas apenas para leitura; faça cancelamentos pela API para atualizar também o status do aluno.
- `Pagamento` pertence a uma matrícula. `Funcionario` fica associado à unidade.
- `Funcionario` vincula opcionalmente uma conta Django à unidade; grupos e permissões podem ser configurados pelo Django Admin.

Para processar vencimentos e mudanças de status diariamente, use `python manage.py rotina_diaria`: o comando encerra matrículas, sincroniza alunos, renova os contratos quitados e emite as cobranças devidas, nessa ordem. Pode ser repetido sem duplicar cobranças. No Windows, instale a tarefa pelo script indicado em **Rotina diária no Windows** abaixo. Sem sua execução agendada, os status podem ficar desatualizados na virada do dia; o registro de entrada continua bloqueado pela validação das datas.

As validações de formulário do Django Admin chamam `clean()`. Ao criar registros diretamente por scripts, chame `full_clean()` antes de `save()`. O Django Admin não isola os dados entre unidades e por isso só admite superusuários; a API aplica permissões por operação e limita dados à unidade do perfil.

O vínculo obrigatório da matrícula com um plano é imposto também pelo banco de dados. As validações de plano ativo e unidade são realizadas pelo serviço e pelo formulário/API; código que salvar uma `Matricula` diretamente sem chamar `full_clean()` pode contorná-las. Para integrações, use `cadastrar_aluno_com_matricula` ou `criar_matricula`. Código que crie `Aluno` diretamente com `Aluno.objects.create(...)` ainda pode contornar a regra de primeira matrícula.

Para executar as verificações: `python manage.py check` e `python manage.py test core`.

### Proteção de dados

O inventário preliminar, os controles técnicos e o procedimento para pedidos dos titulares estão em [LGPD.md](LGPD.md). A academia deve definir bases legais, retenção, aviso e canal de atendimento antes do uso real.

A API limita os registros à unidade selecionada pelo gerente ou à unidade de lotação do atendente. **Gerente** e **Atendimento** recebem os dados de contato necessários à gestão porque têm a permissão específica `ver_contato_aluno`; somente gerentes podem consultar o e-mail de funcionários por `ver_contato_funcionario`. Se personalizar grupos, conceda essas permissões apenas a quem precisa desses dados. Execute `python manage.py migrate` e `python manage.py configurar_grupos` depois de atualizar.

Para produção, configure `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY` (ao menos 50 caracteres aleatórios) e `DJANGO_ALLOWED_HOSTS` (domínios explícitos). Sem essas variáveis, o aplicativo recusa iniciar. Com debug desligado, redirecionamento HTTPS e cookies de sessão/CSRF seguros ficam ativos. Se usar um proxy reverso que termina HTTPS, configure o reconhecimento do protocolo **somente** depois de validar os cabeçalhos enviados pelo proxy; uma configuração incorreta causa redirecionamento em loop. Defina `DJANGO_CSRF_TRUSTED_ORIGINS` quando necessário, com origens completas separadas por vírgula. `DJANGO_HSTS_SECONDS` começa em zero: ative HSTS apenas após garantir HTTPS em todos os acessos. Rode `python manage.py check --deploy` no ambiente final.

Antes de usar dados reais, configure banco de produção, criptografia e cópias de segurança, política de retenção e exclusão, gestão de incidentes e avaliação jurídica da LGPD. O SQLite e o segredo padrão servem apenas para desenvolvimento; estas medidas técnicas não equivalem, isoladamente, à conformidade com a LGPD.

### Backup e recuperação do SQLite

Execute na pasta `backend`, em um terminal com o ambiente virtual ativado:

```powershell
python manage.py backup_banco --diretorio "C:\GymInsight-Backups"
python manage.py backup_banco --verificar "C:\GymInsight-Backups\gyminsight-AAAA...sqlite3"
```

No Linux/macOS, substitua a pasta por um caminho absoluto fora do projeto, como `/var/backups/gyminsight`. O comando cria uma cópia consistente usando a API de backup do SQLite, verifica a integridade do banco e grava um arquivo `.json` ao lado com o hash SHA-256. Ele recusa destinos dentro do diretório do projeto. Mantenha **ambos** os arquivos, com acesso restrito; o backup inclui dados pessoais e senhas protegidas por hash. Armazene cópias criptografadas em outro dispositivo ou serviço, mantenha uma política de retenção e agende o comando diariamente no Agendador de Tarefas ou cron. Um backup apenas no mesmo computador não protege contra perda do equipamento. Falha no comando deve gerar alerta no agendador.

Para restaurar, primeiro pare todos os processos do aplicativo e mantenha uma cópia do banco atual. Verifique o arquivo com `python manage.py backup_banco --verificar CAMINHO_DO_BACKUP`. Copie o `.sqlite3` verificado para `backend/db.sqlite3`, confira as permissões do arquivo, execute `python manage.py check` e teste o login e os registros antes de reabrir o serviço. Nunca substitua o banco com o aplicativo em execução: conexões e arquivos WAL podem causar perda de dados. Teste periodicamente a recuperação em um ambiente isolado; restaurar uma cópia antiga descarta alterações feitas após sua criação. Este comando só atende à configuração SQLite atual. Ao migrar para PostgreSQL ou outro banco, use uma rotina própria para esse banco e valide a recuperação separadamente.
# Interface inicial (HTML, CSS e JavaScript)

Após instalar dependências, aplicar `migrate`, executar `configurar_grupos` e cadastrar um usuário com perfil e grupo, inicie `python manage.py runserver` na pasta `backend` e abra `http://127.0.0.1:8000/`. A página de acesso usa a sessão do Django e o painel consulta alunos, planos, matrículas, entradas, pagamentos, funcionários e auditoria conforme as permissões do usuário.

O frontend inclui consulta paginada, navegação, login e os módulos de alunos, matrículas, planos, presença, relatórios abaixo. A autenticação e a autorização permanecem no backend.

### Módulo de alunos

Na seção **Alunos**, usuários autorizados podem cadastrar o aluno junto de sua primeira matrícula (plano ativo e data de início), abrir detalhes e editar nome, e-mail, telefone e data de nascimento. A frequência mostra total de entradas, dias com presença e contagem diária, com filtro opcional de datas. O botão **Novo aluno** depende das permissões para criar aluno e matrícula e visualizar plano; **Editar cadastro** depende da permissão de alteração. A API continua validando permissões e unidade em todas as operações. Não há exclusão de alunos pela API, para preservar o histórico.

Para testar em um navegador: inicie `python manage.py runserver` em `backend`, abra `/contas/login/` e entre com um usuário vinculado a uma unidade e a um grupo. Prepare um plano ativo na unidade antes de cadastrar alunos. O formulário utiliza sessão do Django e token CSRF. O arquivo `core/static/core/alunos.js` contém a lógica dessa seção.

### Módulo de matrículas

Na seção **Matrículas**, usuários autorizados podem consultar detalhes, cadastrar uma matrícula para um aluno existente e cancelar uma matrícula ativa com motivo obrigatório. Ao criar, selecione aluno, plano ativo da unidade e início; o backend calcula o fim do contrato. A renovação ocorre automaticamente após o último dia, quando todas as cobranças do histórico estiverem quitadas; usuários autorizados ainda podem renovar manualmente após o vencimento. A API impede duplicar matrícula ativa vigente e mantém o histórico de matrículas canceladas. O botão **Nova matrícula** requer permissões de criar matrícula e consultar aluno e plano; **Cancelar matrícula** requer as permissões específicas de cancelar e alterar matrícula. O backend revalida cada operação, inclusive unidade e status.

### Módulo de planos

Na seção **Planos**, todos os perfis com permissão de leitura consultam os planos da própria unidade e seus detalhes, inclusive os inativos. Usuários com permissão de criar plano veem **Novo plano**; usuários com permissão de alterar plano veem **Editar plano**. O formulário permite definir nome, duração em dias, preço e disponibilidade para novas matrículas. Nomes repetidos na unidade, duração inválida e preço negativo são rejeitados pela API. Para impedir novas contratações sem perder o histórico, desative o plano. Matrículas anteriores preservam suas datas de validade.

### Módulo de presença

Na seção **Entradas**, usuários com permissões `add_frequencia`, `registrar_frequencia` e `view_matricula` podem usar **Registrar presença**. A interface oferece matrículas da unidade marcadas como ativas e vigentes no dia atual em Manaus, identifica aluno, plano e validade antes do envio, e mostra número, aluno e horário do registro após a confirmação. A API verifica novamente unidade, status e prazo: opções carregadas anteriormente podem deixar de ser válidas. O histórico fica paginado na mesma seção, somente para consulta. Perfis sem permissão de registrar podem consultar esse histórico quando possuem `view_frequencia`.

Cada confirmação aceita cria uma entrada independente; o frontend desabilita o botão enquanto aguarda a resposta e não reenviará automaticamente. Em caso de falha de conexão, confira o histórico antes de tentar novamente: a API ainda não oferece chave de idempotência para evitar duplicação quando um envio é repetido.

### Relatório de frequência

A aba **Relatórios** consulta `GET /api/alunos/relatorio-frequencia/`, com filtros opcionais `inicio` e `fim` no formato `AAAA-MM-DD` e paginação `page`. Exige `view_aluno` e `view_frequencia` e restringe os registros à unidade do usuário. Exibe o total de alunos, alunos com presença e entradas no período para **toda a unidade**, além de uma tabela paginada com cada aluno, status, total de entradas, dias distintos com presença e última entrada. Alunos sem presença aparecem com zero. Entradas de matrículas anteriores continuam contando; filtros usam a data local da academia (America/Manaus). O relatório conta entradas registradas, não tempo de permanência ou lotação em tempo real. Reenvios duplicados e entradas não registradas podem distorcer os totais.

### Escopo de gestão

Alunos são cadastros administrativos para matrículas, cobrança e controle operacional de entradas. Não há portal nem serviço de avaliação física para alunos. Gerente e atendimento são os únicos perfis operacionais autorizados no painel e na API. O grupo antigo Gestor é migrado para Gerente ao executar `configurar_grupos`; Consulta e Avaliador perdem o acesso. Instalações antigas mantêm os registros clínicos somente na tabela isolada `core_avaliacaofisica_arquivo`, sem acesso por API, painel ou Admin; defina sua destinação e retenção antes de excluí-los.

### Funcionários e contas de acesso

A aba **Funcionários** lista a equipe da unidade: **gerentes, atendentes, professores, faxineiros e outros**. O gerente pode cadastrar e editar funcionários em `/api/funcionarios/`; o formulário do painel permite novos cadastros. Professores e faxineiros são apenas cadastros, sem login. A conta Django é opcional e, quando vinculada, deve pertencer ao grupo correspondente ao cargo Gerente ou Atendimento. A autorização exige simultaneamente conta ativa, funcionário ativo, cargo compatível, grupo correto e unidade ativa. Para criar a primeira conta administrativa, use `createsuperuser` e depois `vincular_gerente`.

Na migração `0008`, os antigos professores e perfis são copiados para funcionários antes da remoção das tabelas antigas. Execute `python manage.py migrate` e depois `python manage.py configurar_grupos` em instalações existentes. Faça backup do banco antes da atualização; não substitua o `backend/db.sqlite3` pelos dados de demonstração.

**Catálogo da rede demonstrativa:** os três planos são sincronizados entre as unidades quando `criar_rede_demo` ativa a configuração da rede. O banco ainda guarda um registro de plano por unidade para preservar contratos existentes; o [DER proposto](DER-GESTAO-PROPOSTO.md) representa uma possível migração futura para uma tabela global.


### Unidades e horários especiais

Cada unidade tem categoria **Tradicional**, **Premium** ou **Diamante**, situação ativa e horários para segunda a sexta, sábado, domingo e feriados cadastrados. O gerente cadastra e altera unidades no painel e registra datas de feriado **por unidade**; o feriado pode seguir a configuração padrão, fechar a unidade ou definir horário excepcional. Feriado registrado prevalece sobre domingo. O comando de registro de presença rejeita entradas fora do horário cadastrado.

Gerentes veem apenas a unidade de lotação e as unidades adicionais vinculadas a `Funcionario.unidades_acesso`. Ao criar uma unidade, o gerente recebe automaticamente acesso a ela. Um gerente superusuário pode atribuir acesso a unidades preexistentes pelo Django Admin; pela API, o gerente só pode delegar unidades às quais já tem acesso. O seletor de unidade do painel muda o contexto de **alunos, matrículas, planos, pagamentos, funcionários, feriados, entradas, auditoria e relatórios**. Atendentes não podem trocar para outra unidade. A API mantém o mesmo contexto na sessão; após mudar de unidade, novas operações usam a unidade selecionada.

Os planos da rede são registros locais sincronizados entre unidades, e sua categoria define o acesso entre unidades. Cada presença registra a unidade de entrada; confira as regras em **Entrada por unidade e categoria do plano** abaixo.

### Lista de matriculados e situação

No painel, a seção **Matriculados** mostra as matrículas da unidade selecionada, com busca por nome, filtros, totais por situação e acesso aos detalhes da matrícula. Gerentes podem mudar entre unidades autorizadas; atendentes veem apenas a própria unidade. A API correspondente é `GET /api/matriculas/matriculados/`, com parâmetros opcionais `busca`, `situacao` e `page`.

A lista mostra **Sem pendências** somente quando todas as cobranças registradas do aluno estão quitadas. Cobranças abertas com vencimento futuro aparecem como **A vencer**; cobranças vencidas aparecem como **Atrasada**, com mês da competência e data de vencimento, inclusive quando pertencem a uma matrícula anterior do mesmo aluno. Cobranças antigas sem competência identificada exibem **competência não informada** e a data do vencimento. Matrículas sem qualquer cobrança aparecem como **Sem cobrança**; canceladas e encerradas mantêm sua situação contratual, e suas pendências vencidas continuam visíveis.


### Mensalidades e faturamento por competência

Execute `python manage.py migrate` após atualizar o projeto. O campo opcional `Pagamento.competencia` identifica o mês como o primeiro dia (`AAAA-MM-01`). Registros antigos ficam sem competência e continuam acessíveis; não são convertidos automaticamente em mensalidades, pois não há informação segura sobre qual mês representam.

Ao criar uma matrícula, o sistema copia `Plano.preco` para `Matricula.valor_contratado`. Se o período já começou, emite automaticamente uma cobrança de mesmo valor; para um início futuro, a tarefa diária a emitirá somente a partir desse dia. O vencimento é o dia de início e a competência é o mês de início. Esse preço não muda se o gerente alterar o plano. O preço cobre **todo o período** indicado por `Plano.duracao_dias`; um plano de 30 dias contratado no fim do mês não recebe uma segunda cobrança apenas por entrar no mês seguinte. Uma renovação cria outra matrícula, com o preço atual do plano e nova cobrança. A renovação é automática somente com o histórico financeiro quitado; também pode ser iniciada manualmente após o fim do período; se ocorrerem depois, o novo período começa no dia da renovação, sem cobrança retroativa pelos dias em que o aluno ficou sem matrícula. A nova matrícula aponta para a anterior e o mesmo período não pode ser renovado duas vezes. É possível renovar pelo botão **Renovar mesmo plano** nos detalhes ou por `POST /api/matriculas/{id}/renovar/` (opcionalmente `{"plano": ID}` para trocar de plano da unidade).

A operação `POST /api/pagamentos/gerar-mensalidades/` com `{"competencia":"AAAA-MM"}` agora serve para recuperar **cobranças ausentes** de matrículas que **começaram** naquele mês (ativas ou encerradas), jamais para cobrar novamente uma matrícula que apenas atravessou a virada do calendário. É idempotente. Os valores antigos não são deduzidos do preço atual: a migração `0012` deixa `valor_contratado` vazio nos contratos anteriores; o gerente consulta o contrato e confirma uma vez pelo botão **Confirmar valor antigo** ou por `POST /api/matriculas/{id}/confirmar-valor/` com `{"valor":"100.00"}`. Se já houver cobrança para a competência de início, o valor informado precisa corresponder ao valor dessa cobrança. Uma matrícula antiga sem valor confirmado bloqueia a emissão de sua cobrança até a confirmação. Cobranças de matrículas canceladas não são geradas por esse recurso.

`GET /api/pagamentos/?competencia=AAAA-MM` lista as cobranças do mês, com `situacao=atrasada` quando ainda pendentes e vencidas **antes de hoje**. O painel permite confirmar pagamento, registrando data e hora. `GET /api/pagamentos/faturamento/?competencia=AAAA-MM` informa quantidade de cobranças, faturamento previsto, recebido da competência (independentemente do dia em que foi pago), em aberto e vencido em aberto. O indicador **recebido no mês (caixa)** soma pagamentos com `pago_em` dentro do mês consultado, inclusive pagamentos de competências anteriores e registros legados. Cobranças canceladas são excluídas dos totais de faturamento e aberto. O filtro de unidade e as permissões de gerente são aplicados às duas operações.


### Entrada por unidade e categoria do plano

Após atualizar o projeto, execute `python manage.py migrate`. A migração `0011` atribui aos planos antigos a categoria Tradicional, exceto nomes exatamente **Premium**, **Plano Premium**, **Diamante** ou **Plano Diamante**, cujas categorias correspondentes são reconhecidas. Revise planos com nomes próprios antes de usar o controle entre unidades. As matrículas antigas recebem a categoria correspondente ao plano encontrado e as entradas históricas recebem como local a unidade sede do aluno, já que antes não havia registro de visitas a outras unidades.

Ao cadastrar um plano, informe sua categoria. **Tradicional** dá acesso à unidade sede e opcionalmente a outras unidades Tradicionais se a cláusula `acesso_tradicional_rede` estiver ativada. **Premium** dá acesso à sede e a unidades Tradicionais e Premium. **Diamante** dá acesso à sede e a todas as categorias, inclusive visitas em domingos e feriados quando a unidade estiver aberta. A matrícula copia essas condições na contratação; elas não mudam quando o plano é editado. Na própria unidade sede, domingos e feriados obedecem ao funcionamento da unidade para qualquer categoria. Em outras unidades, visitas aos domingos ou feriados exigem Diamante.

No módulo de Entradas, o funcionário vê matrículas vigentes elegíveis para sua unidade em `GET /api/frequencias/elegiveis/`. `POST /api/frequencias/` recebe somente o ID da matrícula: a API determina a unidade pela lotação do atendente ou pela unidade escolhida pelo gerente, verifica permissão do funcionário, plano contratado, matrícula válida, abertura e horário local e grava `Frequencia.unidade_id`. Não aceita que o cliente informe outra unidade no corpo da requisição. A listagem de entradas mostra as realizadas na unidade selecionada, inclusive alunos visitantes; o relatório individual de frequência do aluno continua contando também entradas feitas em outras unidades.

### Atualizar uma instalação local no Windows sem perder os dados

Pare o servidor com `Ctrl+C` antes de atualizar. O ZIP entregue contém o código e **não contém** `backend/db.sqlite3`. Mantenha uma cópia de segurança do banco existente, extraia o novo ZIP em **outra pasta** e copie seu `db.sqlite3` antigo para `gyminsight/backend/db.sqlite3` da pasta nova antes de executar `migrate`. Instale as dependências na nova pasta com `python -m pip install -r requirements.txt`, depois execute `python manage.py migrate`, `python manage.py configurar_grupos` e `python manage.py runserver`. Não execute `createsuperuser` novamente quando estiver reutilizando o banco antigo: a conta já está nele. Em contratos históricos, o gerente pode precisar confirmar o valor contratado antes de emitir cobranças antigas.

### Emissão diária sem botão

Cada matrícula cujo início já chegou cria sua cobrança na contratação; matrículas com início futuro aguardam a data contratada. A rotina `python manage.py emitir_mensalidades` procura matrículas **ativas ou encerradas cujo início já ocorreu** e cria somente a cobrança faltante da competência do **mês de início**. Assim, uma contratação em 29/08 com 30 dias de duração não ganha outra cobrança em 01/09; a próxima cobrança só virá com uma **nova matrícula de renovação**. Repetir a rotina não duplica faturas: há chave única por matrícula e competência e emissão idempotente. Uma tarefa diária também recupera cobranças omitidas se o processo não rodar em um dia anterior.

Registros históricos sem `valor_contratado` não são faturados automaticamente: o gerente deve confirmar o preço acordado. Matrículas com outros pagamentos anteriores (especialmente sem competência) ficam **pendentes de conciliação** para evitar duplicar um pagamento legado. A saída do comando mostra quantos registros foram criados, já existiam, dependem de preço e precisam de conciliação. Matrículas canceladas não recebem cobranças novas. A emissão isolada não renova matrícula. A rotina diária renova contratos vencidos elegíveis antes da emissão e nunca cobra antecipadamente períodos futuros.

### Rotina diária no Windows

No PowerShell, na pasta `backend` da instalação que contém o **seu banco de dados** e depois de `python manage.py migrate`, instale a tarefa diária das duas rotinas (06:00 no relógio do Windows):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\instalar_emissao_windows.ps1"
Start-ScheduledTask -TaskName "GymInsight - Rotina diaria"
```

O instalador usa primeiro `backend\.venv\Scripts\python.exe`, se existir; caso contrário usa `python` encontrado no PowerShell. Pode receber `-PythonExecutable "C:\caminho\python.exe"`. Ele confere as dependências, o Django e as migrações antes de registrar a tarefa; reexecutá-lo atualiza o caminho da instalação. A tarefa antiga **GymInsight - Mensalidades** é removida automaticamente quando contém a ação anterior conhecida, evitando execução paralela. Se essa tarefa antiga foi personalizada, a instalação é bloqueada até que o operador desative a tarefa antiga.

Depois que a execução de teste terminar, confira:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\verificar_rotina_windows.ps1"
```

O verificador confere a presença e o estado da tarefa, o código de saída do Agendador, o horário da última execução e o marcador de sucesso em `backend\logs\rotina-diaria.log`; falhas da rotina também ficam nesse arquivo. Os comandos fazem a atualização de forma idempotente: se o PC não estava disponível no horário agendado, a opção de executar quando disponível permite recuperar as matrículas vencidas e cobranças faltantes na próxima execução. O script usa a sessão interativa do usuário: deixe uma sessão iniciada para execução agendada; para operação contínua sem login, configure a tarefa com uma conta de serviço apropriada no servidor. Ao mover a pasta ou alterar o Python, instale a tarefa novamente na nova pasta. Confira que o relógio do Windows esteja ajustado ao horário desejado; as datas de negócio no Django usam `America/Manaus`.

### Cancelamento e acerto financeiro

O cancelamento da matrícula exige motivo. A decisão **manter** preserva a cobrança existente; **cancelar cobrança pendente** exige gerente e justificativa e retira o lançamento do faturamento. Novas operações de reembolso foram desativadas na interface e na API. Registros históricos de reembolso permanecem guardados para auditoria; instalações que possuam esses registros devem conciliá-los antes de usar os valores apresentados como receita líquida.

### Gráfico financeiro dinâmico

Na aba **Financeiro**, selecione a competência e a unidade para ver o faturamento. O anel externo verde representa 100% do faturamento previsto (cobranças emitidas, excluídas as canceladas). A pizza interna divide esse mesmo total entre recebidos em Pix (azul escuro), cartão (azul claro), recebidos antigos sem forma informada (azul acinzentado) e cobranças pendentes (vermelho). O gráfico evita contar o previsto novamente como parcela adicional. A legenda exibe valores em reais. Pendência é dinheiro não recebido, incluindo valores a vencer e vencidos; ainda não é perda definitiva. O painel atualiza imediatamente após pagamentos e emissões feitos na tela e consulta novamente o servidor a cada 10 segundos enquanto a aba estiver visível, além de atualizar quando o usuário retorna à janela. A consulta periódica traz dados recentes de alterações feitas por outros gerentes sem exigir recarregar a página. Reembolsos não aparecem nos indicadores nem podem ser criados; registros históricos permanecem no banco.

### Conciliação das matrículas e pagamentos antigos

Execute `python manage.py migrate` para aplicar a migração `0014`. Na aba **Financeiro**, a seção **Contratos antigos para conferir** lista matrículas iniciadas com preço não confirmado ou pagamentos sem competência ainda sem decisão. O gerente abre a matrícula, confirma uma única vez o preço **acordado no contrato original** e examina cada pagamento antigo (valor, situação, vencimento e data de recebimento). O preço atual do plano não é usado para preencher contratos históricos.

Cada lançamento antigo exige justificativa e uma destas decisões:

| Decisão | Condição | Efeito |
| --- | --- | --- |
| Associar ao período | Preço confirmado, valor exatamente igual ao contratado e nenhuma cobrança já associada ao período | Preenche apenas a competência do **mês de início da matrícula**; preserva valor, vencimento, situação e `pago_em`. A chave única por matrícula e competência impede duas associações ao mesmo período. |
| Recebimento avulso | Pagamento efetivamente recebido | Mantém a competência vazia e o recebimento no caixa. Este valor não quita o período contratado. |
| Descartar cobrança pendente | Lançamento ainda pendente | Muda sua situação para cancelado, preserva o registro e retira seu valor em aberto. |

Após todos os lançamentos sem competência terem sido associados ou classificados, a rotina diária pode emitir a cobrança faltante **somente se não houver outra para o período**, a matrícula não estiver cancelada e o preço estiver confirmado. Isso permite recuperar cobranças faltantes após classificar valores avulsos ou pendências descartadas. Um pagamento pago com valor diferente do contratado não é associado nem ajustado automaticamente: o gerente deve verificar o documento e decidir como tratar a diferença. Conciliações são únicas e não podem ser repetidas pela API. Cobranças já conciliadas ficam protegidas contra alteração pela API.

O gerente pode consultar `GET /api/matriculas/pendencias-legadas/`, confirmar o preço por `POST /api/matriculas/{id}/confirmar-valor/` com `{"valor":"100.00"}` e classificar cada lançamento por `POST /api/pagamentos/{id}/conciliar/` com `{"destino":"associado","justificativa":"Contrato e recibo conferidos"}`. As outras opções de `destino` são `avulso` e `descartado`. A lista e a ação são limitadas à unidade selecionada pelo gerente.

### Avisos e renovação automática

Em **Matriculados**, a seção **Matrículas próximas do vencimento** aparece desde **sete dias antes do último dia de validade**, incluindo o último dia. Gerente e atendentes veem aluno, plano, fim, dias restantes e se a renovação automática está prevista ou bloqueada. `GET /api/matriculas/avisos-vencimento/` retorna essa lista paginada por unidade. O aviso fica no painel; o sistema não envia mensagens ao aluno.

Não há renovação antecipada: o contrato atual vale até `fim`, inclusive. No primeiro dia **após** o vencimento, `python manage.py rotina_diaria` encerra o período, verifica o histórico completo de pagamentos e, se elegível, cria uma única nova matrícula do mesmo plano e sua cobrança pendente. **Todas as cobranças pendentes do aluno, inclusive de matrículas anteriores ou canceladas, impedem a renovação automática**, ainda que a fatura atual esteja paga. Pagamentos pagos mas sem competência e sem conciliação, contratos antigos sem valor confirmado e períodos não cancelados sem comprovante de pagamento também bloqueiam. Cobranças explicitamente canceladas não representam dívida.

A renovação usa o preço vigente do plano na nova contratação e conserva o valor acordado nos períodos anteriores. Se o computador ficou desligado e a rotina rodou dias depois do vencimento, a nova matrícula começa na data de execução: não cria dias ou cobranças retroativas pelo intervalo sem cobertura. A rotina não renova matrícula cancelada, plano inativo, unidade inativa, período já renovado nem aluno com contratação mais recente. Após criar a matrícula, a nova cobrança fica **pendente** até o gerente registrar seu pagamento; renovação automática não equivale a pagamento automático. A operação pode ser repetida sem duplicar períodos. Gerentes e atendentes autorizados continuam podendo usar `POST /api/matriculas/{id}/renovar/` somente após o vencimento; a condição de quitação descrita aqui rege a renovação **automática**.

Atualize a pasta instalada e execute novamente `powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\instalar_emissao_windows.ps1"` se mudou o caminho do projeto. A tarefa diária existente chama `rotina_diaria`, portanto passará a incluir as renovações depois da atualização. Nenhuma migração de banco é necessária para esta etapa.

### Registro manual de recebimentos por Pix e cartão

Execute `python manage.py migrate` para aplicar a migração `0015`. Na aba **Financeiro**, cada cobrança pendente mostra um seletor **Pix** ou **Cartão** ao lado do botão **Confirmar pagamento**. O gerente confirma que recebeu **o valor integral**; o servidor registra a data e hora de quitação, a forma escolhida e o usuário responsável. O valor e o vencimento da cobrança não podem ser alterados pela API após a emissão. Não há pagamentos parciais, parcelamento ou descontos. A seleção **Cartão** não distingue crédito e débito.

A lista de cobranças mostra **Forma de pagamento** ao lado da situação; cobranças pendentes mostram um traço. Pagamentos antigos que já estavam quitados antes da migração mantêm a forma vazia e são apresentados como **Não informado (histórico)**, sem inferir Pix ou cartão. Os resumos por competência e caixa trazem totais recebidos por forma e em separado os valores históricos sem forma; o consolidado por unidade também os separa. 

O sistema **não processa pagamentos**: não contata banco, operadora de cartão nem gateway e não armazena dados de cartão. O registro é uma confirmação administrativa de um recebimento ocorrido fora do aplicativo. A API aceita `PATCH /api/pagamentos/{id}/` com `{"status":"pago","forma_pagamento":"pix"}` ou `"cartao"`; se omitida a data, o servidor usa o momento da confirmação. Cobranças já quitadas não podem ser modificadas pela API.
