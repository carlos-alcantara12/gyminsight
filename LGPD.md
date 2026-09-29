# Plano de adequação à LGPD — GymInsight

Este documento descreve os controles disponíveis no software e as decisões que a academia deve tomar antes de tratar dados reais. Implementar recursos técnicos, por si só, não comprova conformidade jurídica. Referências: [LGPD, Lei 13.709/2018](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709compilado.htm), [direitos dos titulares — ANPD](https://www.gov.br/anpd/pt-br/assuntos/titular-de-dados-1/direito-dos-titulares) e [guia de segurança — ANPD](https://www.gov.br/anpd/pt-br/centrais-de-conteudo/materiais-educativos-e-publicacoes/guia-orientativo-sobre-seguranca-da-informacao-para-agentes-de-tratamento-de-pequeno-porte).

## Inventário preliminar do tratamento

| Categoria | Dados mantidos | Finalidade funcional | Responsável pela definição da base legal e retenção |
| --- | --- | --- | --- |
| Alunos | Nome, contatos opcionais, nascimento opcional, status | Cadastro, comunicação e gestão de matrícula | Academia/controlador |
| Matrículas e planos | Vínculo, datas, preço, status, motivo de cancelamento | Execução de contratação e comprovação de histórico | Academia/controlador |
| Entradas | Hora, matrícula, operador | Controle de acesso e cálculo de frequência | Academia/controlador |
| Pagamentos | Valor, vencimento, pagamento e status | Gestão financeira | Academia/controlador |
| Funcionários | Nome, e-mail opcional, cargo, unidade e vínculo opcional à conta | Gestão da equipe e controle de acesso | Academia/controlador |
| Usuários e auditoria | Identidade de operador, unidade, grupos, ações e horários | Controle de acesso e responsabilização | Academia/controlador |

O sistema **não define automaticamente** bases legais, períodos de retenção ou compartilhamentos. A academia deve mapear cada operação, consultar assessoria jurídica quando necessário e aprovar política de retenção e aviso de privacidade antes de colocar dados reais no sistema. O campo de motivo de cancelamento é texto livre: oriente operadores a registrar apenas o motivo necessário, sem dados de saúde ou detalhes de terceiros. Avalie se a data de nascimento é necessária para a operação; ela é opcional.

## Controles implementados

- Autenticação por sessão, permissões Django, acesso limitado à unidade e grupos distintos. Apenas Gerente e Atendimento possuem acesso operacional.
- `GET /api/alunos/{id}/dados-pessoais/`: o Gerente pode obter um extrato dos dados operacionais do aluno, suas matrículas, entradas e pagamentos na sua unidade. O endpoint exige permissão `exportar_dados_aluno` **e** leitura de pagamentos. Define `Cache-Control: no-store` e registra evento `exportado` no log, sem copiar os valores exportados. Execute `python manage.py migrate` e `python manage.py configurar_grupos` após a atualização.
- Correções cadastrais podem ser feitas por funcionário autorizado via API; alterações ficam na auditoria sem replicar valores pessoais. A API não edita nem apaga registros de frequência, preservando o histórico operacional.
- O aplicativo exige chave e domínios explícitos quando `DJANGO_DEBUG=0` e ativa cookies seguros e redirecionamento HTTPS. O backup SQLite verifica integridade e SHA-256; proteja o destino e as cópias externas.

## Procedimento para direitos dos titulares

1. A academia recebe e registra o pedido em canal próprio e verifica a identidade do titular ou representante **antes** de consultar ou entregar qualquer extrato. Não use apenas o número do cadastro como prova de identidade.
2. Uma pessoa designada verifica a unidade, a extensão do pedido e eventuais dados de terceiros. Gestores obtêm o extrato pelo endpoint, fazem revisão humana e entregam por canal seguro. Evite salvar o extrato em pasta compartilhada ou enviá-lo por canal sem proteção.
3. Para correção, confirme o dado correto e altere os campos permitidos na API. Para oposição, bloqueio, anonimização ou exclusão, avalie a finalidade e a obrigação aplicável a cada categoria antes de agir. **Não há exclusão automática de dados pessoais**, porque pode haver histórico contratual, pagamentos, auditoria e obrigações de guarda. Documente e comunique a decisão no atendimento.
4. Registre recebimento, validação de identidade, decisão, responsável, canal de resposta e encerramento em um processo administrativo protegido fora do GymInsight. Defina prazos de atendimento conforme a legislação e orientações aplicáveis, com revisão jurídica.

## Pendências obrigatórias para uso real

- Identificar controlador, operador(es), encarregado ou canal de contato aplicável e publicar aviso de privacidade com finalidade, bases, compartilhamento, duração e direitos.
- Aprovar tabela de retenção por categoria, com método de exclusão ou anonimização revisado para vínculos históricos e cópias de segurança. Não inventar prazo único no sistema.
- Configurar HTTPS, servidor de produção, controle de acesso ao banco, criptografia e cópias externas, testes de restauração e resposta a incidentes.
- Treinar funcionários no registro mínimo de dados e revisar permissões ao admitir ou desligar pessoas. Revisar periodicamente acessos e logs.
- Validar em ambiente real os fluxos de pedidos, correções e resposta a incidentes. Exportações não cobrem automaticamente informações mantidas fora do GymInsight nem dispensam avaliação sobre dados de terceiros.

Dados antigos de avaliação física, caso existam, permanecem na tabela `core_avaliacaofisica_arquivo` fora dos modelos e endpoints ativos. A academia deve decidir a guarda ou a exclusão conforme sua política de retenção; backups anteriores podem conter esses registros.
