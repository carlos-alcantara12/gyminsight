# Rede demonstrativa do GymInsight

`GymInsight-demonstracao.sqlite3` é um banco separado com cinco unidades,
dez alunos fictícios por unidade, três planos compartilhados (sincronizados
entre os registros de cada unidade) e dez feriados de 2026 por unidade.
Os alunos `aluno01` a `aluno50` se distribuem igualmente; há matrículas com
cobranças atrasadas, matrículas futuras com cobrança a vencer, cancelamentos
e pagamentos fictícios quitados. A Paixão de Cristo em 3 de abril é válida
para o calendário de 2026.

Para abrir a interface com essa amostra:

1. Extraia o ZIP em uma nova pasta; **não substitua seu banco real**.
2. Copie `demo/GymInsight-demonstracao.sqlite3` para `backend/db.sqlite3`.
3. Em `backend`, instale as dependências de `requirements.txt` e execute
   `python manage.py migrate`.
4. Execute `python manage.py createsuperuser` e depois
   `python manage.py vincular_gerente --usuario SEU_LOGIN --unidade "GymInsight - Zona Norte"`.
   Esse vínculo dá acesso às cinco unidades da rede de demonstração.
5. Execute `python manage.py runserver` e entre em `http://127.0.0.1:8000/`.

O operador interno de demonstração não possui senha e não pode fazer login.
As situações financeiras são amostras com datas relativas ao dia em que o
comando foi executado; a rotina diária pode alterá-las ao longo do tempo.
Para gerar dados com datas atuais em um banco **vazio**, execute `migrate`,
`configurar_grupos` e `criar_rede_demo` nessa ordem.
