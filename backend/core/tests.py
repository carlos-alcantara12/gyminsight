from datetime import datetime, time, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, TransactionTestCase
from django.test import Client
from django.utils import timezone
from rest_framework.test import APIClient

from .models import AcertoCancelamento, Aluno, ConciliacaoLegado, Feriado, Frequencia, LogAuditoria, Matricula, Pagamento, Funcionario, Plano, Unidade
from .audit_context import ator_da_operacao
from .access import configurar_grupos_padrao, usuario_tem_permissao
from .services import cadastrar_aluno_com_matricula, calcular_fim_plano, calcular_frequencia, cancelar_matricula, criar_matricula, encerrar_matriculas_vencidas, registrar_entrada, sincronizar_status_aluno
from .management.commands.backup_banco import verificar_backup
from .financeiro import emitir_cobrancas_devidas


def criar_funcionario(*, usuario, unidade):
    nome = usuario.get_full_name() or usuario.username
    cargo = Funcionario.Cargo.GERENTE if "gestor" in usuario.username or "gerente" in usuario.username else Funcionario.Cargo.ATENDENTE
    return Funcionario.objects.create(usuario=usuario, unidade=unidade, nome=nome, cargo=cargo)


class DemoDataTests(TestCase):
    def test_comando_cria_matriculas_e_frequencias_sem_duplicar(self):
        configurar_grupos_padrao()
        saida = StringIO()
        call_command("criar_dados_demo", stdout=saida)
        unidade = Unidade.objects.get(nome="GymInsight - Unidade Demonstracao")
        self.assertEqual(Aluno.objects.filter(unidade=unidade).count(), 10)
        self.assertEqual(Matricula.objects.filter(aluno__unidade=unidade).count(), 10)
        self.assertEqual(Frequencia.objects.filter(matricula__aluno__unidade=unidade).count(), 10)
        self.assertEqual(calcular_frequencia(aluno=Aluno.objects.get(email="ana.demo@example.invalid"))["total_entradas"], 1)
        self.assertEqual(Aluno.objects.filter(matriculas__frequencias__isnull=False).distinct().count(), 10)
        self.assertFalse(get_user_model().objects.get(username="gyminsight_demo_operador").has_usable_password())
        call_command("criar_dados_demo", stdout=saida)
        self.assertEqual(Matricula.objects.count(), 10)
        self.assertEqual(Frequencia.objects.count(), 10)
        self.assertIn("0 entrada(s) criada(s)", saida.getvalue())


class RotinaDiariaTests(TestCase):
    def test_encerramento_e_emissao_ocorrem_em_ordem_e_podem_ser_repetidos(self):
        hoje = timezone.localdate()
        unidade = Unidade.objects.create(nome="Sede")
        plano = Plano.objects.create(unidade=unidade, nome="Mensal", duracao_dias=30, preco="100.00")
        vencido = Aluno.objects.create(unidade=unidade, nome="Vencido", status=Aluno.Status.ATIVO)
        antiga = Matricula.objects.create(
            aluno=vencido, plano=plano, inicio=hoje - timedelta(days=30),
            fim=hoje - timedelta(days=1), status=Matricula.Status.ATIVA,
        )
        futuro = Aluno.objects.create(unidade=unidade, nome="Iniciando", status=Aluno.Status.INATIVO)
        iniciando = Matricula.objects.create(
            aluno=futuro, plano=plano, inicio=hoje, fim=hoje + timedelta(days=29), status=Matricula.Status.ATIVA,
        )
        saida = StringIO()
        call_command("rotina_diaria", stdout=saida)
        antiga.refresh_from_db()
        vencido.refresh_from_db()
        futuro.refresh_from_db()
        self.assertEqual(antiga.status, Matricula.Status.ENCERRADA)
        self.assertEqual(vencido.status, Aluno.Status.INATIVO)
        self.assertEqual(futuro.status, Aluno.Status.ATIVO)
        self.assertEqual(Pagamento.objects.filter(matricula=iniciando).count(), 1)
        self.assertIn("Rotina diária concluída", saida.getvalue())
        call_command("rotina_diaria", stdout=StringIO())
        self.assertEqual(Pagamento.objects.filter(matricula=iniciando).count(), 1)

    def test_renova_apos_o_fim_sem_duplicar_e_sem_cobrar_intervalo_perdido(self):
        hoje = timezone.localdate()
        unidade = Unidade.objects.create(nome="Sede")
        plano = Plano.objects.create(unidade=unidade, nome="Mensal", duracao_dias=30, preco="100.00")
        aluno = Aluno.objects.create(unidade=unidade, nome="Renovável")
        anterior = Matricula.objects.create(aluno=aluno, plano=plano, inicio=hoje - timedelta(days=32),
                                            fim=hoje - timedelta(days=3), status=Matricula.Status.ATIVA)
        Pagamento.objects.create(matricula=anterior, competencia=anterior.inicio.replace(day=1),
                                 valor="100.00", vencimento=anterior.inicio, pago_em=timezone.now(), status="pago")
        call_command("rotina_diaria", stdout=StringIO())
        nova = Matricula.objects.get(matricula_anterior=anterior)
        self.assertEqual(nova.inicio, hoje)
        self.assertEqual(nova.pagamentos.get().status, Pagamento.Status.PENDENTE)
        self.assertEqual(nova.pagamentos.get().vencimento, hoje)
        call_command("rotina_diaria", stdout=StringIO())
        self.assertEqual(Matricula.objects.filter(aluno=aluno).count(), 2)
        self.assertEqual(nova.pagamentos.count(), 1)

    def test_divida_de_periodo_anterior_impede_renovacao_ate_quitacao(self):
        hoje = timezone.localdate()
        unidade = Unidade.objects.create(nome="Sede")
        plano = Plano.objects.create(unidade=unidade, nome="Mensal", duracao_dias=30, preco="100.00")
        aluno = Aluno.objects.create(unidade=unidade, nome="Histórico com dívida")
        antigo = Matricula.objects.create(aluno=aluno, plano=plano, inicio=hoje - timedelta(days=60),
                                          fim=hoje - timedelta(days=31), status=Matricula.Status.ENCERRADA)
        divida = Pagamento.objects.create(matricula=antigo, competencia=antigo.inicio.replace(day=1),
                                         valor="100.00", vencimento=antigo.inicio)
        atual = Matricula.objects.create(aluno=aluno, plano=plano, inicio=hoje - timedelta(days=30),
                                         fim=hoje - timedelta(days=1), status=Matricula.Status.ATIVA,
                                         matricula_anterior=antigo)
        Pagamento.objects.create(matricula=atual, competencia=atual.inicio.replace(day=1),
                                 valor="100.00", vencimento=atual.inicio, pago_em=timezone.now(), status="pago")
        call_command("rotina_diaria", stdout=StringIO())
        self.assertFalse(Matricula.objects.filter(matricula_anterior=atual).exists())
        divida.status = Pagamento.Status.PAGO
        divida.pago_em = timezone.now()
        divida.save()
        call_command("rotina_diaria", stdout=StringIO())
        self.assertTrue(Matricula.objects.filter(matricula_anterior=atual, inicio=hoje).exists())

    def test_aviso_sete_dias_antes_nao_renova_antecipado(self):
        from .services import renovar_matriculas_automaticamente
        configurar_grupos_padrao()
        hoje = timezone.localdate()
        unidade = Unidade.objects.create(nome="Avisos")
        plano = Plano.objects.create(unidade=unidade, nome="Mensal", duracao_dias=30, preco="100.00")
        aluno = Aluno.objects.create(unidade=unidade, nome="Avisado")
        matricula = Matricula.objects.create(aluno=aluno, plano=plano, inicio=hoje - timedelta(days=22),
                                             fim=hoje + timedelta(days=7))
        Pagamento.objects.create(matricula=matricula, competencia=matricula.inicio.replace(day=1),
                                 valor="100.00", vencimento=matricula.inicio, pago_em=timezone.now(), status="pago")
        usuario = get_user_model().objects.create_user(username="gerente_aviso", password="teste")
        Funcionario.objects.create(usuario=usuario, unidade=unidade, nome="Gerente", cargo=Funcionario.Cargo.GERENTE)
        usuario.groups.add(Group.objects.get(name="GymInsight Gerente"))
        cliente = APIClient()
        cliente.force_authenticate(usuario)
        resposta = cliente.get("/api/matriculas/avisos-vencimento/")
        self.assertEqual(resposta.data["count"], 1)
        self.assertEqual(resposta.data["results"][0]["dias_restantes"], 7)
        self.assertTrue(resposta.data["results"][0]["renovacao_automatica"])
        self.assertEqual(renovar_matriculas_automaticamente()["renovadas"], 0)
        self.assertEqual(cliente.post(f"/api/matriculas/{matricula.pk}/renovar/").status_code, 400)

    def test_pagamento_pago_mas_sem_conciliacao_nao_dispara_renovacao(self):
        hoje = timezone.localdate()
        unidade = Unidade.objects.create(nome="Sede")
        plano = Plano.objects.create(unidade=unidade, nome="Mensal", duracao_dias=30, preco="100.00")
        aluno = Aluno.objects.create(unidade=unidade, nome="Pagamento indefinido")
        antiga = Matricula.objects.create(aluno=aluno, plano=plano, inicio=hoje - timedelta(days=30),
                                          fim=hoje - timedelta(days=1), status=Matricula.Status.ATIVA)
        Pagamento.objects.create(matricula=antiga, valor="100.00", vencimento=antiga.inicio,
                                 pago_em=timezone.now(), status=Pagamento.Status.PAGO)
        call_command("rotina_diaria", stdout=StringIO())
        self.assertFalse(Matricula.objects.filter(matricula_anterior=antiga).exists())


class UnidadeRedeTests(TestCase):
    def setUp(self):
        configurar_grupos_padrao()
        self.sede = Unidade.objects.create(nome="Sede", categoria=Unidade.Categoria.TRADICIONAL)
        self.gerente = get_user_model().objects.create_user(username="gerente_rede", password="senha-testes")
        criar_funcionario(usuario=self.gerente, unidade=self.sede)
        self.gerente.groups.add(Group.objects.get(name="GymInsight Gerente"))
        self.client = APIClient()
        self.client.force_authenticate(self.gerente)

    def test_gerente_cria_e_seleciona_unidade_sem_abrir_acesso_nao_autorizado(self):
        criada = self.client.post("/api/unidades/", {
            "nome": "Filial Premium", "categoria": "premium", "abre_domingo": True,
            "domingo_inicio": "08:00", "domingo_fim": "13:00",
        })
        self.assertEqual(criada.status_code, 201, criada.data)
        filial_id = criada.data["id"]
        self.assertEqual(criada.data["categoria"], "premium")
        self.assertEqual(self.client.get("/api/unidades/").data["count"], 2)
        resumo = self.client.get("/api/unidades/resumo/")
        self.assertEqual(resumo.status_code, 200)
        self.assertEqual(len(resumo.data["unidades"]), 2)
        self.assertEqual({u["categoria"] for u in resumo.data["unidades"]}, {"tradicional", "premium"})
        self.assertEqual(self.client.post(f"/api/unidades/{filial_id}/selecionar/").status_code, 200)
        self.assertEqual(self.client.get("/api/unidades/selecionada/").data["unidade"], filial_id)
        plano = self.client.post("/api/planos/", {"nome": "Local", "duracao_dias": 30, "preco": "150.00"})
        self.assertEqual(plano.status_code, 201, plano.data)
        self.assertEqual(plano.data["unidade"], filial_id)
        self.assertEqual(self.client.get("/api/planos/").data["count"], 1)
        self.assertEqual(self.client.post(f"/api/unidades/{self.sede.pk}/selecionar/").status_code, 200)
        self.assertEqual(self.client.get("/api/planos/").data["count"], 0)

        atendente = get_user_model().objects.create_user(username="atendente_sede")
        criar_funcionario(usuario=atendente, unidade=self.sede)
        atendente.groups.add(Group.objects.get(name="GymInsight Atendimento"))
        self.client.force_authenticate(atendente)
        self.assertEqual(self.client.get("/api/unidades/").data["count"], 1)
        self.assertEqual(len(self.client.get("/api/unidades/resumo/").data["unidades"]), 1)
        self.assertEqual(self.client.get(f"/api/unidades/{filial_id}/").status_code, 404)
        self.assertEqual(self.client.post("/api/unidades/", {"nome": "Invasão"}).status_code, 403)
        self.assertEqual(self.client.post(f"/api/unidades/{filial_id}/selecionar/").status_code, 404)
        self.assertEqual(self.client.get("/api/planos/").data["count"], 0)

        outro = Unidade.objects.create(nome="Outra rede")
        self.client.force_authenticate(self.gerente)
        self.assertEqual(self.client.get(f"/api/unidades/{outro.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/unidades/{outro.pk}/selecionar/").status_code, 404)
        self.gerente.funcionario_academia.unidades_acesso.add(outro)
        self.assertEqual(self.client.get(f"/api/unidades/{outro.pk}/").status_code, 200)

    def test_domingo_feriado_excecao_e_validacoes(self):
        dia = "2026-09-27"  # domingo
        resposta = self.client.get(f"/api/unidades/{self.sede.pk}/funcionamento/", {"data": dia})
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(resposta.data["abre"])
        invalida = self.client.patch(f"/api/unidades/{self.sede.pk}/", {"abre_domingo": True})
        self.assertEqual(invalida.status_code, 400)
        atualizada = self.client.patch(f"/api/unidades/{self.sede.pk}/", {
            "abre_domingo": True, "domingo_inicio": "08:00", "domingo_fim": "12:00",
            "abre_feriado": True, "feriado_inicio": "09:00", "feriado_fim": "13:00",
        })
        self.assertEqual(atualizada.status_code, 200, atualizada.data)
        self.assertTrue(self.client.get(f"/api/unidades/{self.sede.pk}/funcionamento/", {"data": dia}).data["abre"])
        feriado = self.client.post("/api/feriados/", {"nome": "Feriado local", "data": dia, "abre": False})
        self.assertEqual(feriado.status_code, 201, feriado.data)
        consulta = self.client.get(f"/api/unidades/{self.sede.pk}/funcionamento/", {"data": dia}).data
        self.assertEqual(consulta["tipo"], "feriado")
        self.assertFalse(consulta["abre"])
        self.assertEqual(self.client.post("/api/feriados/", {"nome": "Duplicado", "data": dia}).status_code, 400)
        reaberta = self.client.patch(f"/api/feriados/{feriado.data['id']}/", {
            "abre": True, "inicio": "10:00", "fim": "15:00",
        })
        self.assertEqual(reaberta.status_code, 200, reaberta.data)
        consulta = self.client.get(f"/api/unidades/{self.sede.pk}/funcionamento/", {"data": dia}).data
        self.assertEqual(str(consulta["inicio"]), "10:00:00")
        self.assertEqual(self.client.get(f"/api/unidades/{self.sede.pk}/funcionamento/", {"data": "errada"}).status_code, 400)

        atendente = get_user_model().objects.create_user(username="atendente_feriado")
        criar_funcionario(usuario=atendente, unidade=self.sede)
        atendente.groups.add(Group.objects.get(name="GymInsight Atendimento"))
        self.client.force_authenticate(atendente)
        self.assertEqual(self.client.get("/api/feriados/").data["count"], 1)
        self.assertEqual(self.client.post("/api/feriados/", {"nome": "Sem permissão", "data": "2026-10-01"}).status_code, 403)

    def test_presenca_obedece_abertura_domingo_e_feriado(self):
        hoje = timezone.localdate()
        dias = (hoje.weekday() + 1) % 7 or 7
        domingo = hoje - timedelta(days=dias)
        plano = Plano.objects.create(unidade=self.sede, nome="Mensal", duracao_dias=30, preco="100.00")
        aluno = Aluno.objects.create(unidade=self.sede, nome="Aluno com acesso")
        matricula = criar_matricula(aluno=aluno, plano=plano, inicio=hoje - timedelta(days=14))
        as_11h = timezone.make_aware(datetime.combine(domingo, time(11, 0)))
        with self.assertRaises(ValidationError):
            registrar_entrada(matricula=matricula, usuario=self.gerente, instante=as_11h)

        self.sede.abre_domingo = True
        self.sede.domingo_inicio = time(10, 0)
        self.sede.domingo_fim = time(12, 0)
        self.sede.save()
        self.assertEqual(registrar_entrada(matricula=matricula, usuario=self.gerente, instante=as_11h).matricula_id, matricula.pk)
        with self.assertRaises(ValidationError):
            registrar_entrada(matricula=matricula, usuario=self.gerente,
                              instante=timezone.make_aware(datetime.combine(domingo, time(13, 0))))
        Feriado.objects.create(unidade=self.sede, data=domingo, nome="Feriado da unidade", abre=False)
        with self.assertRaises(ValidationError):
            registrar_entrada(matricula=matricula, usuario=self.gerente, instante=as_11h)


    def test_entrada_em_outra_unidade_obedece_categoria_e_registra_destino(self):
        # As chamadas de API desta prova exigem um dia útil; domingos são testados adiante.
        if timezone.localdate().weekday() == 6:
            quarta = timezone.localdate() - timedelta(days=4)
            relogio = patch("django.utils.timezone.now", return_value=timezone.make_aware(datetime.combine(quarta, time(11, 0))))
            relogio.start()
            self.addCleanup(relogio.stop)
        hoje = timezone.localdate()
        dia = hoje - timedelta(days=(hoje.weekday() - 2) % 7 or 7)
        instante = timezone.make_aware(datetime.combine(dia, time(11, 0)))
        inicio = hoje - timedelta(days=14)
        premium = Unidade.objects.create(nome="Filial Premium", categoria=Unidade.Categoria.PREMIUM)
        diamante = Unidade.objects.create(nome="Filial Diamante", categoria=Unidade.Categoria.DIAMANTE)
        tradicional = Unidade.objects.create(nome="Filial Tradicional", categoria=Unidade.Categoria.TRADICIONAL)
        atendente = get_user_model().objects.create_user(username="atendente_filial", password="senha-testes")
        criar_funcionario(usuario=atendente, unidade=premium)
        atendente.groups.add(Group.objects.get(name="GymInsight Atendimento"))
        plano = Plano.objects.create(unidade=self.sede, nome="Premium", categoria=Unidade.Categoria.PREMIUM,
                                    duracao_dias=30, preco="150.00")
        matricula = criar_matricula(aluno=Aluno.objects.create(nome="Visitante", unidade=self.sede), plano=plano, inicio=inicio)
        self.client.force_authenticate(atendente)
        elegiveis = self.client.get("/api/frequencias/elegiveis/")
        self.assertEqual(elegiveis.status_code, 200, elegiveis.data)
        self.assertIn(matricula.pk, [item["id"] for item in elegiveis.data["results"]])
        resposta = self.client.post("/api/frequencias/", {"matricula": matricula.pk})
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertEqual(resposta.data["unidade"], premium.pk)
        self.assertEqual(resposta.data["unidade_nome"], premium.nome)
        tentativa = self.client.post("/api/frequencias/", {"matricula": matricula.pk, "unidade": diamante.pk})
        self.assertEqual(tentativa.status_code, 400)
        self.assertEqual(self.client.get("/api/frequencias/").data["count"], 1)
        self.assertEqual(self.client.get("/api/matriculas/").data["count"], 0)
        with self.assertRaises(ValidationError):
            registrar_entrada(matricula=matricula, usuario=atendente, unidade=diamante, instante=instante)
        plano_trad = Plano.objects.create(unidade=self.sede, nome="Tradicional", duracao_dias=30, preco="100.00")
        matricula_trad = criar_matricula(aluno=Aluno.objects.create(nome="Trad", unidade=self.sede), plano=plano_trad, inicio=inicio)
        self.assertEqual(self.client.post("/api/frequencias/", {"matricula": matricula_trad.pk}).status_code, 400)
        atendente.funcionario_academia.unidade = tradicional
        atendente.funcionario_academia.save(update_fields=["unidade"])
        self.assertEqual(self.client.post("/api/frequencias/", {"matricula": matricula_trad.pk}).status_code, 400)
        plano_trad_rede = Plano.objects.create(unidade=self.sede, nome="Tradicional rede", duracao_dias=30,
                                               preco="100.00", acesso_tradicional_rede=True)
        matricula_rede = criar_matricula(aluno=Aluno.objects.create(nome="Trad rede", unidade=self.sede), plano=plano_trad_rede, inicio=inicio)
        self.assertEqual(self.client.post("/api/frequencias/", {"matricula": matricula_rede.pk}).status_code, 201)
        self.assertEqual(self.client.get("/api/frequencias/").data["count"], 1)
        plano_diamante = Plano.objects.create(unidade=self.sede, nome="Diamante", duracao_dias=30,
                                              preco="200.00", categoria=Unidade.Categoria.DIAMANTE)
        matricula_diamante = criar_matricula(aluno=Aluno.objects.create(nome="Diamante", unidade=self.sede),
                                             plano=plano_diamante, inicio=inicio)
        self.assertEqual(matricula_diamante.categoria_acesso, Unidade.Categoria.DIAMANTE)
        self.assertEqual(self.client.post("/api/frequencias/", {"matricula": matricula_diamante.pk}).status_code, 201)
        self.gerente.funcionario_academia.unidades_acesso.add(diamante, premium)
        with self.assertRaises(ValidationError):
            registrar_entrada(matricula=matricula, usuario=self.gerente, unidade=diamante, instante=instante)
        diamante.abre_domingo = True
        diamante.domingo_inicio = time(10, 0)
        diamante.domingo_fim = time(12, 0)
        diamante.save()
        premium.abre_domingo = True
        premium.domingo_inicio = time(10, 0)
        premium.domingo_fim = time(12, 0)
        premium.save()
        domingo = hoje - timedelta(days=(hoje.weekday() + 1) % 7 or 7)
        domingo_11h = timezone.make_aware(datetime.combine(domingo, time(11, 0)))
        registro = registrar_entrada(matricula=matricula_diamante, usuario=self.gerente, unidade=diamante,
                                      instante=domingo_11h)
        self.assertEqual(registro.unidade_id, diamante.pk)
        with self.assertRaises(ValidationError):
            registrar_entrada(matricula=matricula, usuario=self.gerente, unidade=premium, instante=domingo_11h)
        plano_diamante.categoria = Unidade.Categoria.TRADICIONAL
        with self.assertRaises(ValidationError):
            plano_diamante.full_clean()
        self.assertEqual(Matricula.objects.get(pk=matricula_diamante.pk).categoria_acesso, Unidade.Categoria.DIAMANTE)
        self.assertEqual(Frequencia.objects.filter(matricula=matricula_rede, unidade=tradicional).count(), 1)


class StudentFrontendTests(TestCase):
    def test_gerente_muda_unidade_por_sessao_com_csrf(self):
        import json
        configurar_grupos_padrao()
        sede = Unidade.objects.create(nome="Sede da rede")
        gerente = get_user_model().objects.create_user(username="gerente_painel", password="senha-testes")
        criar_funcionario(usuario=gerente, unidade=sede)
        gerente.groups.add(Group.objects.get(name="GymInsight Gerente"))
        cliente = Client(enforce_csrf_checks=True, HTTP_HOST="localhost")
        cliente.get("/contas/login/")
        cliente.force_login(gerente)
        self.assertContains(cliente.get("/"), 'id="unit-picker"')
        self.assertContains(cliente.get("/"), 'js/unidades.js')
        payload = json.dumps({"nome": "Nova filial", "categoria": "diamante"})
        self.assertEqual(cliente.post("/api/unidades/", data=payload, content_type="application/json").status_code, 403)
        criada = cliente.post("/api/unidades/", data=payload, content_type="application/json",
                             HTTP_X_CSRFTOKEN=cliente.cookies["csrftoken"].value)
        self.assertEqual(criada.status_code, 201, criada.content)
        filial_id = criada.json()["id"]
        self.assertEqual(cliente.post(f"/api/unidades/{filial_id}/selecionar/",
                                      HTTP_X_CSRFTOKEN=cliente.cookies["csrftoken"].value).status_code, 200)
        self.assertContains(cliente.get("/"), f'data-selected="{filial_id}"')

    def test_modulo_clinico_nao_esta_disponivel(self):
        configurar_grupos_padrao()
        unidade = Unidade.objects.create(nome="Unidade operacional")
        usuario = get_user_model().objects.create_user(username="gerente_web", password="senha-testes")
        criar_funcionario(usuario=usuario, unidade=unidade)
        usuario.groups.add(Group.objects.get(name="GymInsight Gerente"))
        cliente = Client(HTTP_HOST="localhost")
        cliente.force_login(usuario)
        self.assertNotContains(cliente.get("/"), "avaliações físicas")
        self.assertEqual(cliente.get("/api/avaliacoes-fisicas/").status_code, 404)

    def test_relatorio_abre_para_consulta_sem_campos_de_contato(self):
        configurar_grupos_padrao()
        unidade = Unidade.objects.create(nome="Unidade de relatórios")
        aluno = Aluno.objects.create(unidade=unidade, nome="Aluno para relatório", email="privado@example.com")
        usuario = get_user_model().objects.create_user(username="leitor_relatorio", password="senha-testes")
        criar_funcionario(usuario=usuario, unidade=unidade)
        usuario.groups.add(Group.objects.get(name="GymInsight Atendimento"))
        cliente = Client(HTTP_HOST="localhost")
        cliente.force_login(usuario)
        self.assertContains(cliente.get("/"), 'data-section="relatorios"')
        self.assertContains(cliente.get("/"), "js/relatorios.js")
        resultado = cliente.get("/api/alunos/relatorio-frequencia/").json()
        self.assertEqual(resultado["resumo"]["total_alunos"], 1)
        self.assertEqual(resultado["results"][0]["aluno_id"], aluno.pk)
        self.assertEqual(resultado["results"][0]["total_entradas"], 0)
        self.assertNotIn("email", resultado["results"][0])

    def test_sessao_registra_presenca_e_restringe_perfil_consulta(self):
        import json
        configurar_grupos_padrao()
        unidade = Unidade.objects.create(nome="Unidade presenças", abre_domingo=True,
                                        domingo_inicio=time(0, 0), domingo_fim=time(23, 59))
        plano = Plano.objects.create(unidade=unidade, nome="Mensal", duracao_dias=30, preco="90.00")
        aluno = Aluno.objects.create(unidade=unidade, nome="Aluno com presença")
        matricula = criar_matricula(aluno=aluno, plano=plano, inicio=timezone.localdate())
        usuario = get_user_model().objects.create_user(username="recepcao_presenca", password="senha-testes")
        criar_funcionario(usuario=usuario, unidade=unidade)
        usuario.groups.add(Group.objects.get(name="GymInsight Atendimento"))
        cliente = Client(enforce_csrf_checks=True, HTTP_HOST="localhost")
        cliente.get("/contas/login/")
        cliente.post("/contas/login/", {
            "username": usuario.username, "password": "senha-testes",
            "csrfmiddlewaretoken": cliente.cookies["csrftoken"].value,
        })
        self.assertContains(cliente.get("/"), 'id="new-presence"')
        self.assertContains(cliente.get("/"), "js/presencas.js")
        token = cliente.cookies["csrftoken"].value
        sem_token = cliente.post("/api/frequencias/", data=json.dumps({"matricula": matricula.pk}),
                                content_type="application/json")
        self.assertEqual(sem_token.status_code, 403)
        registrada = cliente.post("/api/frequencias/", data=json.dumps({"matricula": matricula.pk}),
                                 content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(registrada.status_code, 201, registrada.content)
        self.assertEqual(registrada.json()["aluno_nome"], aluno.nome)
        self.assertEqual(Frequencia.objects.filter(matricula=matricula).count(), 1)
        consulta = get_user_model().objects.create_user(username="consulta_presenca", password="senha-testes")
        criar_funcionario(usuario=consulta, unidade=unidade)
        consulta.groups.add(Group.objects.get_or_create(name="GymInsight Consulta")[0])
        cliente.force_login(consulta)
        self.assertEqual(cliente.get("/").status_code, 403)
        self.assertEqual(cliente.get("/api/frequencias/").status_code, 403)
        self.assertEqual(cliente.post("/api/frequencias/", data=json.dumps({"matricula": matricula.pk}),
                         content_type="application/json", HTTP_X_CSRFTOKEN=cliente.cookies["csrftoken"].value).status_code, 403)

    def test_sessao_cria_edita_e_inativa_plano_sem_acesso_para_consulta(self):
        import json
        configurar_grupos_padrao()
        unidade = Unidade.objects.create(nome="Unidade planos")
        gestor = get_user_model().objects.create_user(username="gestor_planos", password="senha-testes")
        criar_funcionario(usuario=gestor, unidade=unidade)
        gestor.groups.add(Group.objects.get(name="GymInsight Gerente"))
        cliente = Client(enforce_csrf_checks=True, HTTP_HOST="localhost")
        cliente.get("/contas/login/")
        cliente.post("/contas/login/", {
            "username": gestor.username, "password": "senha-testes",
            "csrfmiddlewaretoken": cliente.cookies["csrftoken"].value,
        })
        self.assertContains(cliente.get("/"), "Novo plano")
        self.assertContains(cliente.get("/"), "js/planos.js")
        token = cliente.cookies["csrftoken"].value
        payload = {"nome": "Mensal web", "duracao_dias": 30, "preco": "99.90", "ativo": True}
        criado = cliente.post("/api/planos/", data=json.dumps(payload),
                              content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(criado.status_code, 201, criado.content)
        plan_id = criado.json()["id"]
        self.assertEqual(cliente.post("/api/planos/", data=json.dumps(payload),
                         content_type="application/json", HTTP_X_CSRFTOKEN=token).status_code, 400)
        editado = cliente.patch(f"/api/planos/{plan_id}/", data=json.dumps({**payload, "ativo": False}),
                               content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(editado.status_code, 200, editado.content)
        self.assertFalse(editado.json()["ativo"])
        consulta = get_user_model().objects.create_user(username="consulta_planos", password="senha-testes")
        criar_funcionario(usuario=consulta, unidade=unidade)
        consulta.groups.add(Group.objects.get_or_create(name="GymInsight Consulta")[0])
        cliente.force_login(consulta)
        self.assertEqual(cliente.get("/").status_code, 403)
        self.assertEqual(cliente.get(f"/api/planos/{plan_id}/").status_code, 403)
        self.assertEqual(cliente.patch(f"/api/planos/{plan_id}/", data=json.dumps(payload),
                         content_type="application/json", HTTP_X_CSRFTOKEN=cliente.cookies["csrftoken"].value).status_code, 403)

    def test_sessao_e_csrf_permitem_cadastro_e_edicao_do_aluno(self):
        configurar_grupos_padrao()
        unidade = Unidade.objects.create(nome="Unidade web")
        plano = Plano.objects.create(unidade=unidade, nome="Mensal", duracao_dias=30, preco="99.00")
        usuario = get_user_model().objects.create_user(username="atendimento_web", password="senha-testes")
        criar_funcionario(usuario=usuario, unidade=unidade)
        usuario.groups.add(Group.objects.get(name="GymInsight Atendimento"))
        cliente = Client(enforce_csrf_checks=True, HTTP_HOST="localhost")
        self.assertEqual(cliente.get("/").status_code, 302)
        cliente.get("/contas/login/")
        token = cliente.cookies["csrftoken"].value
        self.assertEqual(cliente.post("/contas/login/", {
            "username": "atendimento_web", "password": "senha-testes", "csrfmiddlewaretoken": token,
        }).status_code, 302)
        painel = cliente.get("/")
        self.assertContains(painel, "Novo aluno")
        self.assertContains(painel, "js/alunos.js")
        token = cliente.cookies["csrftoken"].value
        import json
        resposta = cliente.post("/api/alunos/", data=json.dumps({
            "nome": "Aluno da interface", "email": "", "telefone": "", "data_nascimento": None,
            "plano": str(plano.pk), "inicio": timezone.localdate().isoformat(),
        }), content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(resposta.status_code, 201, resposta.content)
        aluno_id = resposta.json()["id"]
        self.assertEqual(Matricula.objects.filter(aluno_id=aluno_id).count(), 1)
        editado = cliente.patch(f"/api/alunos/{aluno_id}/", data=json.dumps({
            "nome": "Aluno editado", "email": "", "telefone": "", "data_nascimento": None,
        }), content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(editado.status_code, 200, editado.content)
        self.assertEqual(editado.json()["nome"], "Aluno editado")
        self.assertEqual(cliente.get(f"/api/alunos/{aluno_id}/frequencia/").json()["total_entradas"], 0)

    def test_sessao_cria_e_cancela_matricula_com_motivo(self):
        import json
        configurar_grupos_padrao()
        unidade = Unidade.objects.create(nome="Unidade das matrículas")
        plano = Plano.objects.create(unidade=unidade, nome="Trimestral", duracao_dias=90, preco="180.00")
        aluno = Aluno.objects.create(unidade=unidade, nome="Aluno renovação")
        usuario = get_user_model().objects.create_user(username="recepcao_matriculas", password="senha-testes")
        criar_funcionario(usuario=usuario, unidade=unidade)
        usuario.groups.add(Group.objects.get(name="GymInsight Atendimento"))
        cliente = Client(enforce_csrf_checks=True, HTTP_HOST="localhost")
        cliente.get("/contas/login/")
        cliente.post("/contas/login/", {
            "username": usuario.username, "password": "senha-testes",
            "csrfmiddlewaretoken": cliente.cookies["csrftoken"].value,
        })
        self.assertContains(cliente.get("/"), "Nova matrícula")
        self.assertContains(cliente.get("/"), "js/matriculas.js")
        token = cliente.cookies["csrftoken"].value
        criada = cliente.post("/api/matriculas/", data=json.dumps({
            "aluno": str(aluno.pk), "plano": str(plano.pk), "inicio": timezone.localdate().isoformat(),
        }), content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(criada.status_code, 201, criada.content)
        matricula_id = criada.json()["id"]
        self.assertEqual(criada.json()["plano_nome"], "Trimestral")
        vazia = cliente.post(f"/api/matriculas/{matricula_id}/cancelar/", data=json.dumps({
            "motivo_cancelamento": "  ",
        }), content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(vazia.status_code, 400)
        cancelada = cliente.post(f"/api/matriculas/{matricula_id}/cancelar/", data=json.dumps({
            "motivo_cancelamento": "Mudança de unidade",
        }), content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(cancelada.status_code, 200, cancelada.content)
        self.assertEqual(cancelada.json()["status"], "cancelada")
        self.assertEqual(Matricula.objects.get(pk=matricula_id).motivo_cancelamento, "Mudança de unidade")


class BackupBancoTests(TransactionTestCase):
    def test_backup_contem_snapshot_e_detecta_alteracao(self):
        Unidade.objects.create(nome="Unidade salva")
        with TemporaryDirectory() as pasta:
            destino = Path(pasta) / "copias"
            call_command("backup_banco", diretorio=destino, stdout=StringIO())
            copia, = destino.glob("*.sqlite3")
            verificar_backup(copia)
            import sqlite3
            with sqlite3.connect(copia) as banco:
                self.assertEqual(banco.execute("SELECT nome FROM core_unidade").fetchone()[0], "Unidade salva")
            with copia.open("ab") as arquivo:
                arquivo.write(b"alterado")
            from django.core.management.base import CommandError
            with self.assertRaises(CommandError):
                verificar_backup(copia)


class ApiIsolationTests(TestCase):
    def setUp(self):
        configurar_grupos_padrao()
        self.a = Unidade.objects.create(nome="Centro", abre_domingo=True,
                                       domingo_inicio=time(0, 0), domingo_fim=time(23, 59))
        self.b = Unidade.objects.create(nome="Norte", abre_domingo=True,
                                       domingo_inicio=time(0, 0), domingo_fim=time(23, 59))
        self.user = get_user_model().objects.create_user(username="gestor", password="senha-testes")
        criar_funcionario(usuario=self.user, unidade=self.a)
        self.user.groups.add(Group.objects.get(name="GymInsight Gerente"))
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.aluno_b = Aluno.objects.create(unidade=self.b, nome="Outra unidade")
        self.plano_b = Plano.objects.create(unidade=self.b, nome="Mensal", duracao_dias=30, preco="99.00")
        self.aluno_a = Aluno.objects.create(unidade=self.a, nome="Aluno local")
        self.plano_a = Plano.objects.create(unidade=self.a, nome="Mensal", duracao_dias=30, preco="99.00")

    def test_cancelamento_mantem_divida_e_guarda_decisao(self):
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=timezone.localdate())
        resposta = self.client.post(f"/api/matriculas/{matricula.pk}/cancelar/", {
            "motivo_cancelamento": "Solicitado", "decisao": "manter",
        })
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(matricula.pagamentos.get().status, Pagamento.Status.PENDENTE)
        self.assertEqual(matricula.acerto_cancelamento.decisao, "manter")
        self.assertEqual(self.client.delete(f"/api/pagamentos/{matricula.pagamentos.get().pk}/").status_code, 400)

    def test_registra_pix_e_cartao_sem_parcelar_ou_modificar_valor(self):
        hoje = timezone.localdate()
        primeira = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=hoje)
        segunda_aluna = Aluno.objects.create(unidade=self.a, nome="Outra cliente")
        segunda = criar_matricula(aluno=segunda_aluna, plano=self.plano_a, inicio=hoje)
        pix = primeira.pagamentos.get()
        cartao = segunda.pagamentos.get()
        url = f"/api/pagamentos/{pix.pk}/"
        self.assertEqual(self.client.patch(url, {"status": "pago"}).status_code, 400)
        self.assertEqual(self.client.patch(url, {"valor": "50.00"}).status_code, 400)
        resposta = self.client.patch(url, {"status": "pago", "forma_pagamento": "pix"})
        self.assertEqual(resposta.status_code, 200, resposta.data)
        pix.refresh_from_db()
        self.assertEqual(pix.forma_pagamento, Pagamento.Forma.PIX)
        self.assertEqual(pix.valor, primeira.valor_contratado)
        self.assertEqual(pix.confirmado_por, self.user)
        self.assertIsNotNone(pix.pago_em)
        self.assertEqual(self.client.patch(url, {"valor": "49.00"}).status_code, 400)
        self.assertEqual(self.client.patch(f"/api/pagamentos/{cartao.pk}/", {
            "status": "pago", "forma_pagamento": "cartao",
        }).status_code, 200)
        mes = hoje.strftime("%Y-%m")
        resumo = self.client.get("/api/pagamentos/faturamento/", {"competencia": mes}).data
        self.assertEqual(resumo["recebido_pix"], Decimal(self.plano_a.preco))
        self.assertEqual(resumo["recebido_cartao"], Decimal(self.plano_a.preco))
        self.assertEqual(resumo["recebido_sem_forma"], 0)
        self.assertEqual(resumo["faturamento_previsto"], resumo["recebido_pix"] + resumo["recebido_cartao"] + resumo["recebido_sem_forma"] + resumo["em_aberto"])
        consolidado = self.client.get("/api/pagamentos/consolidado/", {"competencia": mes}).data["total_rede"]
        self.assertEqual(consolidado["pix"], Decimal(self.plano_a.preco))
        self.assertEqual(consolidado["cartao"], Decimal(self.plano_a.preco))
        self.assertEqual(consolidado["pix_qtd"], 1)
        self.assertEqual(consolidado["cartao_qtd"], 1)
        self.assertEqual(consolidado["sem_forma_qtd"], 0)

    def test_pagamento_historico_sem_forma_permanece_identificado(self):
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=timezone.localdate())
        antigo = matricula.pagamentos.get()
        antigo.status = Pagamento.Status.PAGO
        antigo.pago_em = timezone.now()
        antigo.save()
        resumo = self.client.get("/api/pagamentos/faturamento/", {"competencia": timezone.localdate().strftime("%Y-%m")}).data
        self.assertEqual(resumo["recebido_sem_forma"], antigo.valor)
        self.assertIsNone(self.client.get(f"/api/pagamentos/{antigo.pk}/").data["forma_pagamento"])

    def test_cancelamento_da_cobranca_pendente_exige_gerente_e_justificativa(self):
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=timezone.localdate())
        rota = f"/api/matriculas/{matricula.pk}/cancelar/"
        self.assertEqual(self.client.post(rota, {"motivo_cancelamento": "Teste", "decisao": "cancelar"}).status_code, 400)
        self.assertEqual(matricula.status, Matricula.Status.ATIVA)
        resposta = self.client.post(rota, {"motivo_cancelamento": "Solicitado", "decisao": "cancelar",
                                          "justificativa": "Isenção aprovada pelo gerente"})
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(matricula.pagamentos.get().status, Pagamento.Status.CANCELADO)
        resumo = self.client.get(f"/api/pagamentos/faturamento/?competencia={timezone.localdate():%Y-%m}")
        self.assertEqual(resumo.data["em_aberto"], 0)

    def test_atendente_pode_manter_divida_mas_nao_cancelar_cobranca(self):
        atendente = get_user_model().objects.create_user(username="recepcao_cancel", password="senha-testes")
        Funcionario.objects.create(usuario=atendente, unidade=self.a, nome="Recepção", cargo=Funcionario.Cargo.ATENDENTE)
        atendente.groups.add(Group.objects.get(name="GymInsight Atendimento"))
        self.client.force_authenticate(atendente)
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=timezone.localdate())
        rota = f"/api/matriculas/{matricula.pk}/cancelar/"
        self.assertEqual(self.client.post(rota, {"motivo_cancelamento": "Pedido", "decisao": "cancelar",
                                                 "justificativa": "Tentativa"}).status_code, 400)
        matricula.refresh_from_db()
        self.assertEqual(matricula.status, Matricula.Status.ATIVA)
        self.assertEqual(self.client.post(rota, {"motivo_cancelamento": "Pedido", "decisao": "manter"}).status_code, 200)
        self.assertEqual(matricula.pagamentos.get().status, Pagamento.Status.PENDENTE)

    def test_reembolso_nao_faz_parte_do_fluxo_financeiro(self):
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=timezone.localdate())
        pagamento = matricula.pagamentos.get()
        pagamento.status = Pagamento.Status.PAGO
        pagamento.pago_em = timezone.now()
        pagamento.save()
        rota = f"/api/matriculas/{matricula.pk}/cancelar/"
        resposta = self.client.post(rota, {"motivo_cancelamento": "Solicitado", "decisao": "reembolsar",
                                          "justificativa": "Devolução integral aprovada"})
        self.assertEqual(resposta.status_code, 400, resposta.data)
        url = f"/api/pagamentos/faturamento/?competencia={timezone.localdate():%Y-%m}"
        self.assertNotIn("reembolsado_da_competencia", self.client.get(url).data)
        self.assertEqual(self.client.post(f"/api/matriculas/{matricula.pk}/confirmar-reembolso/").status_code, 404)
        self.assertFalse(AcertoCancelamento.objects.filter(matricula=matricula).exists())

    def test_matriculados_situacao_financeira_filtro_e_unidade(self):
        hoje = timezone.localdate()
        sem_cobranca = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=hoje)
        outro = criar_matricula(aluno=self.aluno_b, plano=self.plano_b, inicio=hoje)
        Pagamento.objects.filter(matricula=sem_cobranca).delete()  # Simula contrato legado sem cobrança emitida.
        Pagamento.objects.create(matricula=outro, valor="99.00", vencimento=hoje - timedelta(days=1))
        url = "/api/matriculas/matriculados/"
        resposta = self.client.get(url)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data["count"], 1)
        self.assertEqual(resposta.data["results"][0]["id"], sem_cobranca.pk)
        self.assertEqual(resposta.data["results"][0]["situacao_financeira"], "sem_cobranca")
        self.assertEqual(resposta.data["totais"]["atrasada"], 0)
        Pagamento.objects.create(matricula=sem_cobranca, valor="99.00", vencimento=hoje - timedelta(days=1))
        self.assertEqual(self.client.get(url).data["results"][0]["situacao_financeira"], "atrasada")
        self.assertEqual(self.client.get(url, {"situacao": "em_dia"}).data["count"], 0)
        self.assertEqual(self.client.get(url, {"situacao": "atrasada", "busca": "local"}).data["count"], 1)
        self.assertEqual(self.client.get(url, {"situacao": "incorreta"}).status_code, 400)
        sem_cobranca.status = Matricula.Status.CANCELADA
        sem_cobranca.motivo_cancelamento = "Solicitação do aluno"
        sem_cobranca.save()
        self.assertEqual(self.client.get(url).data["results"][0]["situacao_financeira"], "cancelada")

    def test_matriculados_so_exibe_sem_pendencias_quando_tudo_esta_pago(self):
        hoje = timezone.localdate()
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=hoje)
        Pagamento.objects.create(matricula=matricula, valor="99.00", vencimento=hoje + timedelta(days=3))
        resposta = self.client.get("/api/matriculas/matriculados/")
        self.assertEqual(resposta.data["results"][0]["situacao_financeira"], "a_vencer")
        Pagamento.objects.filter(matricula=matricula).update(status=Pagamento.Status.PAGO, pago_em=timezone.now())
        self.assertEqual(self.client.get("/api/matriculas/matriculados/").data["results"][0]["situacao_financeira"], "em_dia")

    def test_matriculados_mostra_competencias_antigas_em_aberto(self):
        hoje = timezone.localdate()
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=hoje)
        Pagamento.objects.filter(matricula=matricula).update(status=Pagamento.Status.PAGO, pago_em=timezone.now())
        anterior = Matricula.objects.create(aluno=self.aluno_a, plano=self.plano_a, inicio=hoje - timedelta(days=65),
                                            fim=hoje - timedelta(days=35), status=Matricula.Status.ENCERRADA)
        competencia = (hoje - timedelta(days=65)).replace(day=1)
        Pagamento.objects.create(matricula=anterior, valor="99.00", competencia=competencia,
                                 vencimento=hoje - timedelta(days=40))
        item = next(m for m in self.client.get("/api/matriculas/matriculados/").data["results"] if m["id"] == matricula.pk)
        self.assertEqual(item["situacao_financeira"], "atrasada")
        self.assertEqual(item["pendencias"][0]["competencia"], competencia.strftime("%Y-%m"))
        self.assertEqual(self.client.get("/api/matriculas/matriculados/", {"situacao": "em_dia"}).data["count"], 0)

    def test_geracao_mensal_idempotente_atraso_e_faturamento_da_unidade(self):
        from decimal import Decimal
        hoje = timezone.localdate()
        competencia = hoje.replace(day=1)
        inicio = max(competencia, hoje - timedelta(days=2))
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=inicio)
        outra = criar_matricula(aluno=self.aluno_b, plano=self.plano_b, inicio=inicio)
        Pagamento.objects.filter(matricula=matricula).delete()  # Recuperação de cobrança não emitida.
        url = "/api/pagamentos/gerar-mensalidades/"
        self.assertEqual(self.client.post(url, {"competencia": competencia.strftime("%Y-%m")}).data["cobrancas_criadas"], 1)
        self.assertEqual(self.client.post(url, {"competencia": competencia.strftime("%Y-%m")}).data["cobrancas_criadas"], 0)
        pagamento = Pagamento.objects.get(matricula=matricula)
        self.assertEqual(pagamento.competencia, competencia)
        self.assertEqual(pagamento.valor, Decimal("99.00"))
        self.assertEqual(Pagamento.objects.filter(matricula=outra).count(), 1)
        pagamento.vencimento = hoje - timedelta(days=1)
        pagamento.save(update_fields=["vencimento"])
        self.assertEqual(self.client.get("/api/pagamentos/", {"competencia": competencia.strftime("%Y-%m")}).data["results"][0]["situacao"], "atrasada")
        resumo = self.client.get("/api/pagamentos/faturamento/", {"competencia": competencia.strftime("%Y-%m")}).data
        self.assertEqual(resumo["em_aberto"], Decimal("99.00"))
        self.assertEqual(resumo["vencido_em_aberto"], Decimal("99.00"))
        self.assertEqual(resumo["recebido_da_competencia"], Decimal("0.00"))
        self.assertEqual(resumo["faturamento_previsto"], resumo["recebido_da_competencia"] + resumo["em_aberto"])
        pagamento.status = Pagamento.Status.PAGO
        pagamento.pago_em = timezone.now()
        pagamento.save()
        resumo = self.client.get("/api/pagamentos/faturamento/", {"competencia": competencia.strftime("%Y-%m")}).data
        self.assertEqual(resumo["em_aberto"], Decimal("0.00"))
        self.assertEqual(resumo["recebido_da_competencia"], Decimal("99.00"))
        self.assertEqual(resumo["recebido_no_mes"], Decimal("99.00"))
        self.assertEqual(resumo["faturamento_previsto"], resumo["recebido_da_competencia"] + resumo["em_aberto"])

    def test_geracao_financeira_so_para_gerente(self):
        self.user.groups.clear()
        self.user.groups.add(Group.objects.get(name="GymInsight Atendimento"))
        self.user.funcionario_academia.cargo = Funcionario.Cargo.ATENDENTE
        self.user.funcionario_academia.save()
        mes = timezone.localdate().strftime("%Y-%m")
        self.assertEqual(self.client.post("/api/pagamentos/gerar-mensalidades/", {"competencia": mes}).status_code, 403)
        self.assertEqual(self.client.get("/api/pagamentos/faturamento/", {"competencia": mes}).status_code, 403)
        self.assertEqual(self.client.get("/api/pagamentos/consolidado/", {"competencia": mes}).status_code, 403)

    def test_consolidado_da_rede_soma_somente_unidades_autorizadas(self):
        from decimal import Decimal
        hoje = timezone.localdate()
        competencia = hoje.replace(day=1)
        inicio = max(competencia, hoje - timedelta(days=2))
        matricula_a = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=inicio)
        self.plano_b.preco = "150.00"
        self.plano_b.save(update_fields=["preco"])
        matricula_b = criar_matricula(aluno=self.aluno_b, plano=self.plano_b, inicio=inicio)
        sem_cobranca = Aluno.objects.create(nome="Sem faturar", unidade=self.a)
        sem_cobranca_matricula = criar_matricula(aluno=sem_cobranca, plano=self.plano_a, inicio=inicio)
        Pagamento.objects.filter(matricula=sem_cobranca_matricula).delete()
        Pagamento.objects.filter(matricula=matricula_b).update(status=Pagamento.Status.PAGO, pago_em=timezone.now())
        outra_unidade = Unidade.objects.create(nome="Sem acesso")
        aluno_externo = Aluno.objects.create(nome="Externo", unidade=outra_unidade)
        plano_externo = Plano.objects.create(unidade=outra_unidade, nome="Externo", preco="999.00", duracao_dias=30)
        matricula_externa = criar_matricula(aluno=aluno_externo, plano=plano_externo, inicio=inicio)
        url = "/api/pagamentos/consolidado/"
        filtro = {"competencia": competencia.strftime("%Y-%m")}
        inicial = self.client.get(url, filtro)
        self.assertEqual(inicial.status_code, 200)
        self.assertEqual([linha["id"] for linha in inicial.data["unidades"]], [self.a.pk])
        self.assertEqual(inicial.data["total_rede"]["previsto"], Decimal("99.00"))
        self.assertEqual(inicial.data["total_rede"]["matriculas_sem_cobranca"], 1)
        self.user.funcionario_academia.unidades_acesso.add(self.b)
        rede = self.client.get(url, filtro).data
        self.assertEqual({linha["id"] for linha in rede["unidades"]}, {self.a.pk, self.b.pk})
        self.assertEqual(rede["total_rede"]["previsto"], Decimal("249.00"))
        self.assertEqual(rede["total_rede"]["recebido"], Decimal("150.00"))
        self.assertEqual(rede["total_rede"]["em_aberto"], Decimal("99.00"))
        self.assertEqual(rede["unidade_selecionada"], self.a.pk)
        self.assertEqual(self.client.post(f"/api/unidades/{self.b.pk}/selecionar/").status_code, 200)
        self.assertEqual(self.client.get(url, filtro).data["unidade_selecionada"], self.b.pk)

    def test_periodo_de_trinta_dias_nao_cobra_novamente_na_virada_do_mes(self):
        from datetime import date
        hoje = timezone.localdate()
        mes_futuro = (hoje.replace(day=28) + timedelta(days=4)).replace(day=1)
        inicio = hoje.replace(day=28) if hoje.day <= 28 else mes_futuro.replace(day=28)
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=inicio)
        self.assertNotEqual((matricula.fim.year, matricula.fim.month), (inicio.year, inicio.month))
        if inicio > hoje:
            self.assertFalse(Pagamento.objects.filter(matricula=matricula).exists())
            from .financeiro import emitir_cobranca_contratual
            emitir_cobranca_contratual(matricula)  # Verifica a cobrança que a rotina criará ao iniciar o período.
        cobranca = Pagamento.objects.get(matricula=matricula)
        self.assertEqual(cobranca.vencimento, inicio)
        self.assertEqual(cobranca.competencia, date(inicio.year, inicio.month, 1))
        self.assertEqual(str(matricula.valor_contratado), str(self.plano_a.preco))
        self.plano_a.preco = "175.00"
        self.plano_a.save(update_fields=["preco"])
        matricula.refresh_from_db()
        self.assertEqual(matricula.valor_contratado, cobranca.valor)
        self.assertEqual(Pagamento.objects.filter(matricula=matricula).count(), 1)

    def test_renovacao_cria_novo_periodo_cobranca_e_valor_contratado(self):
        hoje = timezone.localdate()
        antiga = Matricula.objects.create(aluno=self.aluno_a, plano=self.plano_a,
                                          inicio=hoje - timedelta(days=30), fim=hoje - timedelta(days=1),
                                          status=Matricula.Status.ENCERRADA)
        from .financeiro import emitir_cobranca_contratual
        cobranca_antiga, _ = emitir_cobranca_contratual(antiga)
        self.plano_a.preco = "150.00"
        self.plano_a.save(update_fields=["preco"])
        resposta = self.client.post(f"/api/matriculas/{antiga.pk}/renovar/", data={})
        self.assertEqual(resposta.status_code, 201, resposta.data)
        nova = Matricula.objects.get(pk=resposta.data["id"])
        self.assertEqual(nova.inicio, hoje)
        self.assertEqual(nova.fim, hoje + timedelta(days=29))
        self.assertEqual(nova.matricula_anterior_id, antiga.pk)
        self.assertEqual(nova.valor_contratado, nova.pagamentos.get().valor)
        self.assertEqual(nova.valor_contratado, 150)
        self.assertEqual(str(cobranca_antiga.valor), "99.00")
        self.assertEqual(str(antiga.valor_contratado), "99.00")
        self.assertEqual(self.client.post(f"/api/matriculas/{antiga.pk}/renovar/", data={}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/matriculas/{nova.pk}/renovar/", data={}).status_code, 400)

    def test_valor_historico_exige_confirmacao_do_gerente(self):
        hoje = timezone.localdate()
        antiga = Matricula.objects.create(aluno=self.aluno_a, plano=self.plano_a,
                                          inicio=hoje - timedelta(days=5), fim=hoje + timedelta(days=24))
        Matricula.objects.filter(pk=antiga.pk).update(valor_contratado=None)
        antiga.refresh_from_db()
        url = f"/api/matriculas/{antiga.pk}/confirmar-valor/"
        atendente = get_user_model().objects.create_user(username="atendente_valor", password="senha-testes")
        criar_funcionario(usuario=atendente, unidade=self.a)
        atendente.groups.add(Group.objects.get(name="GymInsight Atendimento"))
        self.client.force_authenticate(atendente)
        self.assertEqual(self.client.post(url, {"valor": "95.00"}).status_code, 403)
        self.client.force_authenticate(self.user)
        resposta = self.client.post(url, {"valor": "95.00"})
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(str(resposta.data["valor_contratado"]), "95.00")
        self.assertEqual(self.client.post(url, {"valor": "150.00"}).status_code, 400)

    def test_conciliacao_associa_pagamento_historico_sem_criar_duplicata(self):
        hoje = timezone.localdate()
        antiga = Matricula.objects.create(aluno=self.aluno_a, plano=self.plano_a,
                                          inicio=hoje - timedelta(days=5), fim=hoje + timedelta(days=24))
        Matricula.objects.filter(pk=antiga.pk).update(valor_contratado=None)
        pago_em = timezone.now()
        antigo = Pagamento.objects.create(matricula=antiga, valor="95.00", vencimento=antiga.inicio,
                                         status=Pagamento.Status.PAGO, pago_em=pago_em)
        resposta = self.client.get("/api/matriculas/pendencias-legadas/")
        self.assertEqual([item["id"] for item in resposta.data["results"]], [antiga.pk])
        url = f"/api/pagamentos/{antigo.pk}/conciliar/"
        self.assertEqual(self.client.post(url, {"destino": "associado", "justificativa": "Recibo"}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/matriculas/{antiga.pk}/confirmar-valor/", {"valor": "95.00"}).status_code, 200)
        self.assertEqual(self.client.post(url, {"destino": "associado", "justificativa": "Recibo arquivado"}).status_code, 200)
        antigo.refresh_from_db()
        self.assertEqual(antigo.competencia, antiga.inicio.replace(day=1))
        self.assertEqual(antigo.pago_em, pago_em)
        self.assertEqual(antigo.vencimento, antiga.inicio)
        self.assertEqual(antigo.conciliacao_legado.destino, ConciliacaoLegado.Destino.ASSOCIADO)
        self.assertEqual(self.client.post(url, {"destino": "associado", "justificativa": "Duplo"}).status_code, 400)
        self.assertEqual(emitir_cobrancas_devidas()["criadas"], 0)
        self.assertEqual(Pagamento.objects.filter(matricula=antiga).count(), 1)
        self.assertEqual(self.client.get("/api/matriculas/pendencias-legadas/").data["count"], 0)

    def test_legados_avulsos_e_descartados_exigem_decisao_antes_de_emissao(self):
        hoje = timezone.localdate()
        antiga = Matricula.objects.create(aluno=self.aluno_a, plano=self.plano_a,
                                          inicio=hoje - timedelta(days=5), fim=hoje + timedelta(days=24))
        valor_avulso = Pagamento.objects.create(matricula=antiga, valor="10.00", vencimento=antiga.inicio,
                                               status=Pagamento.Status.PAGO, pago_em=timezone.now())
        cobranca_velha = Pagamento.objects.create(matricula=antiga, valor="12.00", vencimento=antiga.inicio)
        self.assertEqual(emitir_cobrancas_devidas()["pagamentos_legados"], 1)
        self.assertEqual(self.client.post(f"/api/pagamentos/{valor_avulso.pk}/conciliar/", {
            "destino": "descartado", "justificativa": "Incorreto",
        }).status_code, 400)
        self.assertEqual(self.client.post(f"/api/pagamentos/{valor_avulso.pk}/conciliar/", {
            "destino": "avulso", "justificativa": "Taxa separada comprovada",
        }).status_code, 200)
        self.assertEqual(emitir_cobrancas_devidas()["pagamentos_legados"], 1)
        self.assertEqual(self.client.post(f"/api/pagamentos/{cobranca_velha.pk}/conciliar/", {
            "destino": "descartado", "justificativa": "Lançamento antigo duplicado",
        }).status_code, 200)
        cobranca_velha.refresh_from_db()
        self.assertEqual(cobranca_velha.status, Pagamento.Status.CANCELADO)
        self.assertEqual(emitir_cobrancas_devidas()["criadas"], 1)
        self.assertEqual(Pagamento.objects.filter(matricula=antiga).count(), 3)
        self.assertEqual(emitir_cobrancas_devidas()["criadas"], 0)

    def test_conciliacao_respeita_perfil_unidade_e_nao_substitui_cobranca(self):
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=timezone.localdate())
        legado = Pagamento.objects.create(matricula=matricula, valor="99.00", vencimento=matricula.inicio)
        outra = Pagamento.objects.create(matricula=Matricula.objects.create(
            aluno=self.aluno_b, plano=self.plano_b, inicio=timezone.localdate(),
            fim=timezone.localdate() + timedelta(days=29)), valor="99.00", vencimento=timezone.localdate())
        body = {"destino": "associado", "justificativa": "Contrato encontrado"}
        self.assertEqual(self.client.post(f"/api/pagamentos/{outra.pk}/conciliar/", body).status_code, 404)
        self.assertEqual(self.client.post(f"/api/pagamentos/{legado.pk}/conciliar/", body).status_code, 400)
        recepcao = get_user_model().objects.create_user(username="recepcao_legado", password="teste")
        Funcionario.objects.create(usuario=recepcao, unidade=self.a, nome="Recepção", cargo="atendente")
        recepcao.groups.add(Group.objects.get(name="GymInsight Atendimento"))
        self.client.force_authenticate(recepcao)
        self.assertEqual(self.client.get("/api/matriculas/pendencias-legadas/").status_code, 403)
        self.assertEqual(self.client.post(f"/api/pagamentos/{legado.pk}/conciliar/", body).status_code, 403)

    def test_emissor_diario_recupera_faltantes_sem_duplicar_nem_antecipar(self):
        hoje = timezone.localdate()
        plano = self.plano_a
        antiga = Matricula.objects.create(
            aluno=self.aluno_a, plano=plano, inicio=hoje - timedelta(days=31),
            fim=hoje - timedelta(days=2), status=Matricula.Status.ENCERRADA,
        )
        outra = Matricula.objects.create(
            aluno=self.aluno_b, plano=self.plano_b, inicio=hoje - timedelta(days=31),
            fim=hoje - timedelta(days=2), status=Matricula.Status.ENCERRADA,
        )
        Pagamento.objects.create(matricula=outra, valor="99.00", vencimento=outra.inicio)
        futuro_aluno = Aluno.objects.create(nome="Futuro", unidade=self.a)
        futura = criar_matricula(aluno=futuro_aluno, plano=plano, inicio=hoje + timedelta(days=1))
        self.assertFalse(Pagamento.objects.filter(matricula=futura).exists())
        sem_valor_aluno = Aluno.objects.create(nome="Histórico sem preço", unidade=self.a)
        sem_valor = Matricula.objects.create(
            aluno=sem_valor_aluno, plano=plano, inicio=hoje - timedelta(days=32),
            fim=hoje - timedelta(days=3), status=Matricula.Status.ENCERRADA,
        )
        Matricula.objects.filter(pk=sem_valor.pk).update(valor_contratado=None)
        primeira = emitir_cobrancas_devidas()
        self.assertEqual(primeira["criadas"], 1)
        self.assertEqual(primeira["pagamentos_legados"], 1)
        self.assertEqual(primeira["sem_valor"], 1)
        self.assertEqual(Pagamento.objects.get(matricula=antiga).competencia, antiga.inicio.replace(day=1))
        self.assertEqual(Pagamento.objects.filter(matricula=futura).count(), 0)
        self.assertEqual(emitir_cobrancas_devidas()["criadas"], 0)
        saida = StringIO()
        call_command("emitir_mensalidades", stdout=saida)
        self.assertIn("0 cobrança(s) criada(s)", saida.getvalue())
        self.assertEqual(self.client.post("/api/pagamentos/gerar-mensalidades/", {
            "competencia": outra.inicio.strftime("%Y-%m"),
        }).status_code, 400)
        with self.assertRaises(ValidationError):
            emitir_cobrancas_devidas(data_referencia=hoje + timedelta(days=1))

    def test_relatorio_frequencia_filtra_periodo_unidade_e_pagina(self):
        hoje = timezone.localdate()
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=hoje - timedelta(days=3))
        registrar_entrada(matricula=matricula, usuario=self.user, instante=timezone.now() - timedelta(days=1))
        registrar_entrada(matricula=matricula, usuario=self.user)
        registrar_entrada(matricula=matricula, usuario=self.user)
        sem_entrada = Aluno.objects.create(unidade=self.a, nome="Aluno sem presença")
        matricula_b = criar_matricula(aluno=self.aluno_b, plano=self.plano_b, inicio=hoje)
        Frequencia.objects.create(matricula=matricula_b, entrada_em=timezone.now())
        url = "/api/alunos/relatorio-frequencia/"
        geral = self.client.get(url)
        self.assertEqual(geral.status_code, 200)
        self.assertEqual(geral.data["resumo"], {"total_alunos": 2, "total_entradas": 3, "alunos_com_presenca": 1})
        self.assertEqual(geral.data["results"][0]["dias_com_presenca"], 2)
        self.assertEqual(geral.data["results"][1]["aluno_id"], sem_entrada.pk)
        self.assertEqual(geral.data["results"][1]["total_entradas"], 0)
        filtrado = self.client.get(url, {"inicio": hoje.isoformat(), "fim": hoje.isoformat()})
        self.assertEqual(filtrado.data["resumo"]["total_entradas"], 2)
        self.assertEqual(filtrado.data["results"][0]["dias_com_presenca"], 1)
        self.assertEqual(self.client.get(url, {"inicio": "inválida"}).status_code, 400)
        self.assertEqual(self.client.get(url, {
            "inicio": hoje.isoformat(), "fim": (hoje - timedelta(days=1)).isoformat(),
        }).status_code, 400)
        Aluno.objects.bulk_create([Aluno(unidade=self.a, nome=f"Aluno {i}") for i in range(25)])
        segunda = self.client.get(url, {"page": 2})
        self.assertEqual(segunda.data["count"], 27)
        self.assertEqual(len(segunda.data["results"]), 2)
        self.assertEqual(segunda.data["resumo"]["total_entradas"], 3)
        limitado = get_user_model().objects.create_user(username="somente_alunos", password="senha-testes")
        criar_funcionario(usuario=limitado, unidade=self.a)
        limitado.user_permissions.add(Permission.objects.get(codename="view_aluno"))
        self.client.force_authenticate(limitado)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_dados_pessoais_aparecem_apenas_para_perfis_autorizados(self):
        self.aluno_a.email = "aluno@exemplo.com"
        self.aluno_a.telefone = "11999999999"
        self.aluno_a.save()
        professor = Funcionario.objects.create(cargo=Funcionario.Cargo.PROFESSOR, unidade=self.a, nome="Docente", email="professor@exemplo.com")
        consulta = get_user_model().objects.create_user(username="consulta_dados", password="senha-testes")
        criar_funcionario(usuario=consulta, unidade=self.a)
        consulta.groups.add(Group.objects.get_or_create(name="GymInsight Consulta")[0])
        self.client.force_authenticate(consulta)
        self.assertEqual(self.client.get("/api/alunos/").status_code, 403)
        self.assertEqual(self.client.get(f"/api/funcionarios/{professor.pk}/").status_code, 403)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(f"/api/alunos/{self.aluno_a.pk}/").data["email"], "aluno@exemplo.com")
        self.assertEqual(self.client.get(f"/api/funcionarios/{professor.pk}/").data["email"], "professor@exemplo.com")

    def test_extrato_lgpd_restringe_acesso_unidade_e_registra_auditoria(self):
        self.aluno_a.email = "aluno@exemplo.com"
        self.aluno_a.save()
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=timezone.localdate())
        resposta = self.client.get(f"/api/alunos/{self.aluno_a.pk}/dados-pessoais/")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["Cache-Control"], "no-store")
        self.assertEqual(resposta.data["aluno"]["email"], "aluno@exemplo.com")
        self.assertEqual(resposta.data["matriculas"][0]["id"], matricula.pk)
        log = LogAuditoria.objects.get(entidade="aluno", objeto_id=str(self.aluno_a.pk), acao="exportado")
        self.assertEqual(log.usuario, self.user)
        self.assertNotIn("aluno@exemplo.com", str(log.campos_alterados))
        self.assertEqual(self.client.get(f"/api/alunos/{self.aluno_b.pk}/dados-pessoais/").status_code, 404)
        consulta = get_user_model().objects.create_user(username="consulta_lgpd", password="senha-testes")
        criar_funcionario(usuario=consulta, unidade=self.a)
        consulta.groups.add(Group.objects.get_or_create(name="GymInsight Consulta")[0])
        self.client.force_authenticate(consulta)
        self.assertEqual(self.client.get(f"/api/alunos/{self.aluno_a.pk}/dados-pessoais/").status_code, 403)
        matricula.status = Matricula.Status.CANCELADA
        matricula.motivo_cancelamento = "Motivo privado"
        matricula.save(update_fields=["status", "motivo_cancelamento"])
        self.assertEqual(self.client.get(f"/api/matriculas/{matricula.pk}/").status_code, 403)

    def test_isolamento_de_leitura_e_escrita(self):
        self.assertEqual(self.client.get(f"/api/alunos/{self.aluno_b.pk}/").status_code, 404)
        self.assertEqual(self.client.get("/api/alunos/").json()["count"], 1)
        response = self.client.post("/api/matriculas/", {
            "aluno": self.aluno_b.pk, "plano": self.plano_a.pk,
            "inicio": "2026-09-24", "fim": "2026-10-24",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.patch(f"/api/planos/{self.plano_b.pk}/", {"nome": "Alterado"}).status_code, 404)

    def test_api_nao_reativa_matricula_encerrada_por_patch(self):
        hoje = timezone.localdate()
        matricula = Matricula.objects.create(
            aluno=self.aluno_a, plano=self.plano_a,
            inicio=hoje - timedelta(days=30), fim=hoje - timedelta(days=1),
            status=Matricula.Status.ENCERRADA,
        )
        resposta = self.client.patch(f"/api/matriculas/{matricula.pk}/", {"status": "ativa"})
        self.assertEqual(resposta.status_code, 400, resposta.data)
        matricula.refresh_from_db()
        self.assertEqual(matricula.status, Matricula.Status.ENCERRADA)

    def test_cancelamento_e_entrada(self):
        hoje = timezone.localdate()
        response = self.client.post("/api/matriculas/", {
            "aluno": self.aluno_a.pk, "plano": self.plano_a.pk,
            "inicio": hoje.isoformat(), "fim": (hoje + timedelta(days=29)).isoformat(),
        })
        self.assertEqual(response.status_code, 201, response.data)
        matricula = Matricula.objects.get(pk=response.data["id"])
        self.assertEqual(self.client.post("/api/frequencias/", {"matricula": matricula.pk}).status_code, 201)
        self.assertEqual(self.client.patch(f"/api/matriculas/{matricula.pk}/", {"status": "cancelada"}).status_code, 400)
        self.assertEqual(self.client.patch(f"/api/matriculas/{matricula.pk}/", {
            "status": "cancelada", "motivo_cancelamento": "Mudança de cidade",
        }).status_code, 200)
        self.assertEqual(self.client.post("/api/frequencias/", {"matricula": matricula.pk}).status_code, 400)

    def test_exige_login_e_perfil(self):
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get("/api/alunos/").status_code, (401, 403))
        sem_perfil = get_user_model().objects.create_user(username="sem_perfil", password="senha-testes")
        self.client.force_authenticate(sem_perfil)
        self.assertEqual(self.client.get("/api/alunos/").status_code, 403)

    def test_matricula_calcula_vencimento_e_exibe_nomes(self):
        inicio = timezone.localdate()
        response = self.client.post("/api/matriculas/", {
            "aluno": self.aluno_a.pk, "plano": self.plano_a.pk, "inicio": inicio.isoformat(),
        })
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["fim"], (inicio + timedelta(days=29)).isoformat())
        self.assertEqual(response.data["aluno_nome"], "Aluno local")
        self.assertEqual(response.data["plano_nome"], "Mensal")
        self.assertEqual(self.client.post("/api/matriculas/", {
            "aluno": self.aluno_a.pk, "plano": self.plano_a.pk, "inicio": inicio.isoformat(),
        }).status_code, 400)

    def test_serializer_valida_plano_e_pagamento(self):
        self.plano_a.ativo = False
        self.plano_a.save()
        hoje = timezone.localdate()
        self.assertEqual(self.client.post("/api/matriculas/", {
            "aluno": self.aluno_a.pk, "plano": self.plano_a.pk, "inicio": hoje.isoformat(),
        }).status_code, 400)
        self.plano_a.ativo = True
        self.plano_a.save()
        response = self.client.post("/api/matriculas/", {
            "aluno": self.aluno_a.pk, "plano": self.plano_a.pk, "inicio": hoje.isoformat(),
        })
        self.assertEqual(response.status_code, 201, response.data)
        matricula_id = response.data["id"]
        response = self.client.post("/api/pagamentos/", {
            "matricula": matricula_id, "valor": "99.00", "vencimento": hoje.isoformat(),
            "status": "pago",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post("/api/pagamentos/", {
            "matricula": self.plano_b.pk + 99999, "valor": "99.00", "vencimento": hoje.isoformat(),
        }).status_code, 400)
        self.assertEqual(self.client.post("/api/pagamentos/", {
            "matricula": matricula_id, "competencia": hoje.replace(day=1).isoformat(),
            "valor": "99.00", "vencimento": hoje.isoformat(),
            "status": "pago", "pago_em": timezone.now().isoformat(),
        }).status_code, 400)
        cobranca = Pagamento.objects.get(matricula_id=matricula_id)
        self.assertEqual(self.client.patch(f"/api/pagamentos/{cobranca.pk}/", {
            "status": "pago", "pago_em": timezone.now().isoformat(), "forma_pagamento": "pix",
        }).status_code, 200)

    def test_datas_invalidas_e_plano_duplicado(self):
        hoje = timezone.localdate()
        response = self.client.post("/api/matriculas/", {
            "aluno": self.aluno_a.pk, "plano": self.plano_a.pk,
            "inicio": hoje.isoformat(), "fim": (hoje - timedelta(days=1)).isoformat(),
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("fim", response.data)
        self.assertEqual(self.client.post("/api/planos/", {
            "nome": "Mensal", "duracao_dias": 30, "preco": "120.00",
        }).status_code, 400)

    def test_cadastro_cria_aluno_e_matricula_na_mesma_requisicao(self):
        hoje = timezone.localdate()
        self.assertEqual(self.client.post("/api/alunos/", {"nome": "Sem plano"}).status_code, 400)
        self.assertFalse(Aluno.objects.filter(nome="Sem plano").exists())
        response = self.client.post("/api/alunos/", {
            "nome": "Novo aluno", "plano": self.plano_a.pk, "inicio": hoje.isoformat(),
        })
        self.assertEqual(response.status_code, 201, response.data)
        aluno = Aluno.objects.get(pk=response.data["id"])
        matricula = aluno.matriculas.get()
        self.assertEqual(aluno.status, Aluno.Status.ATIVO)
        self.assertEqual(matricula.plano, self.plano_a)
        self.assertEqual(matricula.fim, hoje + timedelta(days=29))
        self.assertEqual(response.data["matricula_ativa_id"], matricula.pk)

    def test_servico_reverte_falha_e_rejeita_outra_unidade(self):
        antes = Aluno.objects.count()
        with self.assertRaises(ValidationError):
            cadastrar_aluno_com_matricula(
                unidade=self.a, plano=self.plano_b, inicio=timezone.localdate(),
                dados_aluno={"nome": "Não permitido"},
            )
        self.assertEqual(Aluno.objects.count(), antes)
        self.assertEqual(self.client.post("/api/alunos/", {
            "nome": "Não permitido", "plano": self.plano_b.pk,
            "inicio": timezone.localdate().isoformat(),
        }).status_code, 400)

    def test_nao_remove_ultima_matricula_nem_transfere_aluno(self):
        hoje = timezone.localdate()
        response = self.client.post("/api/alunos/", {
            "nome": "Com matrícula", "plano": self.plano_a.pk, "inicio": hoje.isoformat(),
        })
        self.assertEqual(response.status_code, 201, response.data)
        aluno_id = response.data["id"]
        matricula_id = response.data["matricula_ativa_id"]
        self.assertEqual(self.client.delete(f"/api/matriculas/{matricula_id}/").status_code, 400)
        self.assertEqual(self.client.patch(f"/api/matriculas/{matricula_id}/", {
            "aluno": self.aluno_a.pk,
        }).status_code, 400)
        self.assertEqual(self.client.delete(f"/api/alunos/{aluno_id}/").status_code, 403)
        self.assertTrue(Matricula.objects.filter(pk=matricula_id, aluno_id=aluno_id).exists())

    def test_servico_exige_plano_valido_e_vincula_matricula(self):
        hoje = timezone.localdate()
        for plano in (None, self.plano_b):
            with self.assertRaises(ValidationError):
                criar_matricula(aluno=self.aluno_a, plano=plano, inicio=hoje)
        self.plano_a.ativo = False
        self.plano_a.save()
        with self.assertRaises(ValidationError):
            criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=hoje)
        self.plano_a.ativo = True
        self.plano_a.save()
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=hoje)
        self.assertEqual(matricula.plano_id, self.plano_a.pk)
        self.assertEqual(matricula.fim, hoje + timedelta(days=29))
        with self.assertRaises(ValidationError):
            criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=hoje)

    def test_api_exige_plano_e_banco_impede_matricula_sem_plano(self):
        hoje = timezone.localdate()
        response = self.client.post("/api/matriculas/", {
            "aluno": self.aluno_a.pk, "inicio": hoje.isoformat(),
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("plano", response.data)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Matricula.objects.create(aluno=self.aluno_a, inicio=hoje, fim=hoje, plano=None)
        self.assertFalse(self.aluno_a.matriculas.exists())

    def test_plano_define_ultimo_dia_e_rejeita_prazo_arbitrario(self):
        hoje = timezone.localdate()
        self.assertEqual(calcular_fim_plano(plano=self.plano_a, inicio=hoje), hoje + timedelta(days=29))
        with self.assertRaises(ValidationError):
            criar_matricula(
                aluno=self.aluno_a, plano=self.plano_a, inicio=hoje,
                fim=hoje + timedelta(days=30),
            )
        response = self.client.post("/api/matriculas/", {
            "aluno": self.aluno_a.pk, "plano": self.plano_a.pk,
            "inicio": hoje.isoformat(), "fim": (hoje + timedelta(days=30)).isoformat(),
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("fim", response.data)
        self.assertFalse(self.aluno_a.matriculas.exists())

    def test_vencimento_encerra_e_permite_renovar(self):
        hoje = timezone.localdate()
        antiga = Matricula.objects.create(
            aluno=self.aluno_a, plano=self.plano_a,
            inicio=hoje - timedelta(days=30), fim=hoje - timedelta(days=1),
        )
        self.aluno_a.status = Aluno.Status.ATIVO
        self.aluno_a.save()
        self.assertEqual(encerrar_matriculas_vencidas(data_referencia=hoje), 1)
        antiga.refresh_from_db()
        self.aluno_a.refresh_from_db()
        self.assertEqual(antiga.status, Matricula.Status.ENCERRADA)
        self.assertEqual(self.aluno_a.status, Aluno.Status.INATIVO)
        self.assertEqual(encerrar_matriculas_vencidas(data_referencia=hoje), 0)
        nova = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=hoje)
        self.aluno_a.refresh_from_db()
        self.assertEqual(self.aluno_a.status, Aluno.Status.ATIVO)
        self.assertEqual(nova.fim, hoje + timedelta(days=29))

    def test_renovacao_fecha_vencida_ainda_ativa(self):
        hoje = timezone.localdate()
        antiga = Matricula.objects.create(
            aluno=self.aluno_a, plano=self.plano_a,
            inicio=hoje - timedelta(days=30), fim=hoje - timedelta(days=1),
        )
        resposta = self.client.post("/api/matriculas/", {
            "aluno": self.aluno_a.pk, "plano": self.plano_a.pk, "inicio": hoje.isoformat(),
        })
        self.assertEqual(resposta.status_code, 201, resposta.data)
        antiga.refresh_from_db()
        self.assertEqual(antiga.status, Matricula.Status.ENCERRADA)

    def test_comando_respeita_o_ultimo_dia_de_validade(self):
        hoje = timezone.localdate()
        matricula = Matricula.objects.create(
            aluno=self.aluno_a, plano=self.plano_a,
            inicio=hoje - timedelta(days=29), fim=hoje,
        )
        saida = StringIO()
        call_command("encerrar_matriculas", stdout=saida)
        matricula.refresh_from_db()
        self.assertEqual(matricula.status, Matricula.Status.ATIVA)
        self.assertIn("0 matrícula(s)", saida.getvalue())

    def test_comando_informa_quantos_alunos_tiveram_status_atualizado(self):
        hoje = timezone.localdate()
        Matricula.objects.create(aluno=self.aluno_a, plano=self.plano_a, inicio=hoje, fim=hoje + timedelta(days=29))
        saida = StringIO()
        call_command("encerrar_matriculas", stdout=saida)
        self.aluno_a.refresh_from_db()
        self.assertEqual(self.aluno_a.status, Aluno.Status.ATIVO)
        self.assertIn("1 aluno(s) atualizado(s)", saida.getvalue())

    def test_cada_chamada_da_api_registra_uma_entrada_separada(self):
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=timezone.localdate())
        primeira = self.client.post("/api/frequencias/", {"matricula": matricula.pk})
        segunda = self.client.post("/api/frequencias/", {"matricula": matricula.pk})
        self.assertEqual(primeira.status_code, 201, primeira.data)
        self.assertEqual(segunda.status_code, 201, segunda.data)
        self.assertNotEqual(primeira.data["id"], segunda.data["id"])
        self.assertEqual(Frequencia.objects.filter(matricula=matricula).count(), 2)
        self.assertEqual(Frequencia.objects.get(pk=primeira.data["id"]).registrada_por, self.user)
        self.assertEqual(self.client.get(f"/api/alunos/{self.aluno_a.pk}/frequencia/").data["total_entradas"], 2)
        self.assertEqual(self.client.delete(f"/api/frequencias/{primeira.data['id']}/").status_code, 403)
        self.assertEqual(self.client.patch(f"/api/frequencias/{primeira.data['id']}/", {"matricula": matricula.pk}).status_code, 403)

    def test_servico_bloqueia_outra_unidade_e_matricula_vencida(self):
        hoje = timezone.localdate()
        outra = Matricula.objects.create(
            aluno=self.aluno_b, plano=self.plano_b, inicio=hoje, fim=hoje + timedelta(days=29),
        )
        with self.assertRaises(ValidationError):
            registrar_entrada(matricula=outra, usuario=self.user)
        self.assertEqual(self.client.post("/api/frequencias/", {"matricula": outra.pk}).status_code, 400)
        vencida = Matricula.objects.create(
            aluno=self.aluno_a, plano=self.plano_a,
            inicio=hoje - timedelta(days=30), fim=hoje - timedelta(days=1),
        )
        with self.assertRaises(ValidationError):
            registrar_entrada(matricula=vencida, usuario=self.user)
        self.assertEqual(self.client.post("/api/frequencias/", {"matricula": vencida.pk}).status_code, 400)
        self.assertEqual(Frequencia.objects.count(), 0)

    def test_servico_bloqueia_horario_futuro_e_matricula_cancelada(self):
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=timezone.localdate())
        with self.assertRaises(ValidationError):
            registrar_entrada(matricula=matricula, usuario=self.user, instante=timezone.now() + timedelta(days=1))
        matricula.status = Matricula.Status.CANCELADA
        matricula.motivo_cancelamento = "Solicitado pelo aluno"
        matricula.save()
        with self.assertRaises(ValidationError):
            registrar_entrada(matricula=matricula, usuario=self.user)
        self.assertEqual(Frequencia.objects.count(), 0)

    def test_cancelamento_exige_motivo_e_atualiza_aluno(self):
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=timezone.localdate())
        registro = registrar_entrada(matricula=matricula, usuario=self.user)
        for motivo in (None, "", "   "):
            with self.assertRaises(ValidationError):
                cancelar_matricula(matricula=matricula, motivo=motivo, usuario=self.user)
        self.assertEqual(self.client.post(f"/api/matriculas/{matricula.pk}/cancelar/", {
            "motivo_cancelamento": "    ",
        }).status_code, 400)
        matricula.refresh_from_db()
        self.assertEqual(matricula.status, Matricula.Status.ATIVA)
        resposta = self.client.post(f"/api/matriculas/{matricula.pk}/cancelar/", {
            "motivo_cancelamento": " Mudança de cidade ",
        })
        self.assertEqual(resposta.status_code, 200, resposta.data)
        matricula.refresh_from_db()
        self.aluno_a.refresh_from_db()
        self.assertEqual(matricula.motivo_cancelamento, "Mudança de cidade")
        self.assertEqual(matricula.status, Matricula.Status.CANCELADA)
        self.assertEqual(self.aluno_a.status, Aluno.Status.CANCELADO)
        self.assertTrue(Frequencia.objects.filter(pk=registro.pk).exists())
        self.assertEqual(self.client.post("/api/frequencias/", {"matricula": matricula.pk}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/matriculas/{matricula.pk}/cancelar/", {
            "motivo_cancelamento": "Outro motivo",
        }).status_code, 400)

    def test_cancelamento_nao_pode_ser_contornado_pela_api(self):
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=timezone.localdate())
        self.assertEqual(self.client.patch(f"/api/alunos/{self.aluno_a.pk}/", {
            "status": "cancelado",
        }).status_code, 400)
        self.assertEqual(self.client.patch(f"/api/matriculas/{matricula.pk}/", {
            "status": "cancelada", "motivo_cancelamento": "   ",
        }).status_code, 400)
        self.assertEqual(self.client.post(f"/api/matriculas/{matricula.pk}/cancelar/", {
            "motivo_cancelamento": "Solicitação do aluno",
        }).status_code, 200)
        self.assertEqual(self.client.patch(f"/api/matriculas/{matricula.pk}/", {
            "status": "ativa",
        }).status_code, 400)
        self.assertEqual(self.client.patch(f"/api/matriculas/{matricula.pk}/", {
            "motivo_cancelamento": "Alteração",
        }).status_code, 400)

    def test_cancelamento_restringe_unidade_e_matricula_encerrada(self):
        hoje = timezone.localdate()
        outra = Matricula.objects.create(
            aluno=self.aluno_b, plano=self.plano_b, inicio=hoje, fim=hoje + timedelta(days=29),
        )
        self.assertEqual(self.client.post(f"/api/matriculas/{outra.pk}/cancelar/", {
            "motivo_cancelamento": "Teste",
        }).status_code, 404)
        encerrada = Matricula.objects.create(
            aluno=self.aluno_a, plano=self.plano_a,
            inicio=hoje - timedelta(days=30), fim=hoje - timedelta(days=1),
            status=Matricula.Status.ENCERRADA,
        )
        with self.assertRaises(ValidationError):
            cancelar_matricula(matricula=encerrada, motivo="Teste", usuario=self.user)
        self.assertEqual(self.client.post(f"/api/matriculas/{encerrada.pk}/cancelar/", {
            "motivo_cancelamento": "Teste",
        }).status_code, 400)

    def test_frequencia_calculada_automaticamente_por_periodo(self):
        hoje = timezone.localdate()
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=hoje - timedelta(days=1))
        ontem = timezone.now() - timedelta(days=1)
        registrar_entrada(matricula=matricula, usuario=self.user, instante=ontem)
        registrar_entrada(matricula=matricula, usuario=self.user)
        registrar_entrada(matricula=matricula, usuario=self.user)
        url = f"/api/alunos/{self.aluno_a.pk}/frequencia/"
        geral = self.client.get(url)
        self.assertEqual(geral.status_code, 200)
        self.assertEqual(geral.data["total_entradas"], 3)
        self.assertEqual(geral.data["dias_com_presenca"], 2)
        self.assertEqual([d["entradas"] for d in geral.data["por_dia"]], [1, 2])
        filtrado = self.client.get(url, {"inicio": hoje.isoformat(), "fim": hoje.isoformat()})
        self.assertEqual(filtrado.data["total_entradas"], 2)
        self.assertEqual(filtrado.data["dias_com_presenca"], 1)
        self.assertEqual(self.client.get(url, {"inicio": "data-ruim"}).status_code, 400)
        self.assertEqual(self.client.get(url, {
            "inicio": hoje.isoformat(), "fim": (hoje - timedelta(days=1)).isoformat(),
        }).status_code, 400)

    def test_frequencia_vazia_e_historico_apos_cancelamento(self):
        url = f"/api/alunos/{self.aluno_a.pk}/frequencia/"
        self.assertEqual(self.client.get(url).data["total_entradas"], 0)
        self.assertEqual(self.client.get(url).data["por_dia"], [])
        self.assertEqual(self.client.get(f"/api/alunos/{self.aluno_b.pk}/frequencia/").status_code, 404)
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=timezone.localdate())
        registrar_entrada(matricula=matricula, usuario=self.user)
        cancelar_matricula(matricula=matricula, motivo="Mudança", usuario=self.user)
        self.assertEqual(calcular_frequencia(aluno=self.aluno_a)["total_entradas"], 1)
        self.assertEqual(self.client.get(url).data["total_entradas"], 1)

    def test_status_derivado_de_matriculas_vigentes_e_canceladas(self):
        hoje = timezone.localdate()
        self.assertEqual(sincronizar_status_aluno(aluno=self.aluno_a), Aluno.Status.INATIVO)
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=hoje)
        self.aluno_a.refresh_from_db()
        self.assertEqual(self.aluno_a.status, Aluno.Status.ATIVO)
        cancelar_matricula(matricula=matricula, motivo="Mudança", usuario=self.user)
        self.aluno_a.refresh_from_db()
        self.assertEqual(self.aluno_a.status, Aluno.Status.CANCELADO)
        criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=hoje)
        self.aluno_a.refresh_from_db()
        self.assertEqual(self.aluno_a.status, Aluno.Status.ATIVO)

    def test_matricula_futura_fica_inativa_ate_inicio(self):
        hoje = timezone.localdate()
        futuro = hoje + timedelta(days=2)
        response = self.client.post("/api/alunos/", {
            "nome": "Início futuro", "plano": self.plano_a.pk, "inicio": futuro.isoformat(),
        })
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], Aluno.Status.INATIVO)
        aluno = Aluno.objects.get(pk=response.data["id"])
        self.assertEqual(sincronizar_status_aluno(aluno=aluno, data_referencia=futuro), Aluno.Status.ATIVO)
        self.assertEqual(self.client.get(f"/api/alunos/{aluno.pk}/").data["status"], Aluno.Status.ATIVO)

    def test_api_nao_permite_alterar_status_manual(self):
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=timezone.localdate())
        for status in Aluno.Status.values:
            self.assertEqual(self.client.patch(f"/api/alunos/{self.aluno_a.pk}/", {
                "status": status,
            }).status_code, 400)
        self.aluno_a.refresh_from_db()
        self.assertEqual(self.aluno_a.status, Aluno.Status.ATIVO)
        self.assertEqual(matricula.status, Matricula.Status.ATIVA)

    def test_perfis_controlam_leitura_escrita_e_cancelamento(self):
        hoje = timezone.localdate()
        sem_grupo = get_user_model().objects.create_user(username="sem_grupo", password="senha-testes")
        criar_funcionario(usuario=sem_grupo, unidade=self.a)
        self.client.force_authenticate(sem_grupo)
        self.assertEqual(self.client.get("/api/alunos/").status_code, 403)

        sem_grupo.groups.add(Group.objects.get_or_create(name="GymInsight Consulta")[0])
        sem_grupo = get_user_model().objects.get(pk=sem_grupo.pk)
        self.client.force_authenticate(sem_grupo)
        self.assertEqual(self.client.get("/api/alunos/").status_code, 403)
        self.assertEqual(self.client.get("/api/pagamentos/").status_code, 403)
        self.assertEqual(self.client.post("/api/alunos/", {
            "nome": "Recusado", "plano": self.plano_a.pk, "inicio": hoje.isoformat(),
        }).status_code, 403)

        atendimento = get_user_model().objects.create_user(username="atendimento", password="senha-testes")
        criar_funcionario(usuario=atendimento, unidade=self.a)
        atendimento.groups.add(Group.objects.get(name="GymInsight Atendimento"))
        self.client.force_authenticate(atendimento)
        resposta = self.client.post("/api/alunos/", {
            "nome": "Permitido", "plano": self.plano_a.pk, "inicio": hoje.isoformat(),
        })
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertEqual(self.client.post("/api/frequencias/", {
            "matricula": resposta.data["matricula_ativa_id"],
        }).status_code, 201)
        self.assertEqual(self.client.get("/api/pagamentos/").status_code, 403)
        self.assertEqual(self.client.post(f"/api/matriculas/{resposta.data['matricula_ativa_id']}/cancelar/", {
            "motivo_cancelamento": "Solicitação",
        }).status_code, 200)

    def test_unidade_ou_usuario_inativo_nao_acessa_api(self):
        self.assertTrue(usuario_tem_permissao(usuario=self.user, model=Aluno, acao="list"))
        self.assertFalse(usuario_tem_permissao(usuario=self.user, model=Aluno, acao="acao_nova"))
        self.a.ativa = False
        self.a.save()
        self.assertEqual(self.client.get("/api/alunos/").status_code, 403)
        self.a.ativa = True
        self.a.save()
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.client.get("/api/alunos/").status_code, 403)

    def test_registro_direto_exige_permissao_e_admin_restrito(self):
        hoje = timezone.localdate()
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=hoje)
        consulta = get_user_model().objects.create_user(
            username="consulta_staff", password="senha-testes", is_staff=True,
        )
        criar_funcionario(usuario=consulta, unidade=self.a)
        consulta.groups.add(Group.objects.get_or_create(name="GymInsight Consulta")[0])
        with self.assertRaises(ValidationError):
            registrar_entrada(matricula=matricula, usuario=consulta)
        self.client.force_authenticate(user=None)
        self.client.login(username="consulta_staff", password="senha-testes")
        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_configuracao_grupos_pode_ser_repetida(self):
        call_command("configurar_grupos", stdout=StringIO())
        call_command("configurar_grupos", stdout=StringIO())
        self.assertEqual(Group.objects.filter(name__startswith="GymInsight ").count(), 2)

    def test_funcionarios_por_cargo_e_unidade_sem_login_para_professor_ou_faxineiro(self):
        criado = self.client.post("/api/funcionarios/", {
            "nome": "Maria Silva", "cargo": "faxineiro", "email": "maria@example.invalid", "ativo": True,
        })
        self.assertEqual(criado.status_code, 201, criado.data)
        self.assertEqual(criado.data["unidade"], self.a.pk)
        professor = self.client.post("/api/funcionarios/", {"nome": "Paulo", "cargo": "professor"})
        self.assertEqual(professor.status_code, 201, professor.data)
        self.assertEqual(self.client.get("/api/professores/").status_code, 404)
        self.assertEqual(self.client.get("/api/funcionarios/").data["count"], 3)
        self.assertEqual(self.client.patch(f"/api/funcionarios/{criado.data['id']}/", {"ativo": False}).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/funcionarios/{criado.data['id']}/").status_code, 403)
        outra_unidade = Funcionario.objects.create(unidade=self.b, nome="Outro", cargo="faxineiro")
        self.assertEqual(self.client.get(f"/api/funcionarios/{outra_unidade.pk}/").status_code, 404)

        atendente = get_user_model().objects.create_user(username="atendente_equipe")
        criar_funcionario(usuario=atendente, unidade=self.a)
        atendente.groups.add(Group.objects.get(name="GymInsight Atendimento"))
        self.client.force_authenticate(atendente)
        self.assertEqual(self.client.get("/api/funcionarios/").status_code, 200)
        self.assertNotIn("email", self.client.get(f"/api/funcionarios/{professor.data['id']}/").data)
        self.assertEqual(self.client.post("/api/funcionarios/", {"nome": "Não permitido", "cargo": "professor"}).status_code, 403)

    def test_cargo_impede_acesso_mesmo_com_grupo_privilegiado(self):
        self.user.funcionario_academia.cargo = Funcionario.Cargo.PROFESSOR
        self.user.funcionario_academia.save(update_fields=["cargo"])
        self.assertEqual(self.client.get("/api/alunos/").status_code, 403)
        self.assertEqual(Client().get("/api/professores/").status_code, 404)

    def test_vinculo_de_conta_exige_cargo_e_grupo_correspondentes(self):
        conta = get_user_model().objects.create_user(username="nova_atendente", password="senha-testes")
        conta.groups.add(Group.objects.get(name="GymInsight Atendimento"))
        recusado = self.client.post("/api/funcionarios/", {
            "nome": "Cargo sem acesso", "cargo": "faxineiro", "usuario": conta.pk,
        })
        self.assertEqual(recusado.status_code, 400)
        recusado = self.client.post("/api/funcionarios/", {
            "nome": "Grupo divergente", "cargo": "gerente", "usuario": conta.pk,
        })
        self.assertEqual(recusado.status_code, 400)
        aceito = self.client.post("/api/funcionarios/", {
            "nome": "Nova atendente", "cargo": "atendente", "usuario": conta.pk,
        })
        self.assertEqual(aceito.status_code, 201, aceito.data)
        self.client.force_authenticate(conta)
        self.assertEqual(self.client.get("/api/alunos/").status_code, 200)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.patch(f"/api/funcionarios/{aceito.data['id']}/", {"ativo": False}).status_code, 200)
        self.client.force_authenticate(get_user_model().objects.get(pk=conta.pk))
        self.assertEqual(self.client.get("/api/alunos/").status_code, 403)

    def test_migracao_de_grupos_preserva_gerente_e_revoga_perfis_antigos(self):
        gestor = Group.objects.create(name="GymInsight Gestor")
        leitor = Group.objects.create(name="GymInsight Consulta")
        avaliador = Group.objects.create(name="GymInsight Avaliador")
        gerente_antigo = get_user_model().objects.create_user(username="gerente_antigo")
        leitor_antigo = get_user_model().objects.create_user(username="leitor_antigo")
        gerente_antigo.groups.add(gestor)
        leitor_antigo.groups.add(leitor, avaliador)
        configurar_grupos_padrao()
        self.assertTrue(gerente_antigo.groups.filter(name="GymInsight Gerente").exists())
        self.assertFalse(leitor_antigo.groups.exists())
        self.assertFalse(Group.objects.filter(name__in=["GymInsight Gestor", "GymInsight Consulta", "GymInsight Avaliador"]).exists())

    def test_cadastro_exige_permissao_para_aluno_e_matricula(self):
        usuario = get_user_model().objects.create_user(username="parcial", password="senha-testes")
        criar_funcionario(usuario=usuario, unidade=self.a)
        usuario.user_permissions.add(Permission.objects.get(codename="add_aluno"))
        self.client.force_authenticate(usuario)
        self.assertEqual(self.client.post("/api/alunos/", {
            "nome": "Sem autorização de matrícula", "plano": self.plano_a.pk,
            "inicio": timezone.localdate().isoformat(),
        }).status_code, 403)
        self.assertFalse(Aluno.objects.filter(nome="Sem autorização de matrícula").exists())

    def test_cancelamento_exige_permissao_especifica_nas_duas_rotas(self):
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=timezone.localdate())
        usuario = get_user_model().objects.create_user(username="editor", password="senha-testes")
        criar_funcionario(usuario=usuario, unidade=self.a)
        usuario.user_permissions.add(
            Permission.objects.get(codename="change_matricula"),
            Permission.objects.get(codename="view_matricula"),
        )
        self.client.force_authenticate(usuario)
        self.assertEqual(self.client.post(f"/api/matriculas/{matricula.pk}/cancelar/", {
            "motivo_cancelamento": "Solicitado",
        }).status_code, 403)
        self.assertEqual(self.client.patch(f"/api/matriculas/{matricula.pk}/", {
            "status": "cancelada", "motivo_cancelamento": "Solicitado",
        }).status_code, 403)
        with self.assertRaises(ValidationError):
            cancelar_matricula(matricula=matricula, motivo="Solicitado", usuario=usuario)
        matricula.refresh_from_db()
        self.assertEqual(matricula.status, Matricula.Status.ATIVA)
        usuario.user_permissions.add(Permission.objects.get(codename="cancelar_matricula"))
        usuario.groups.add(Group.objects.get(name="GymInsight Atendimento"))
        self.client.force_authenticate(get_user_model().objects.get(pk=usuario.pk))
        self.assertEqual(self.client.post(f"/api/matriculas/{matricula.pk}/cancelar/", {
            "motivo_cancelamento": "Solicitado",
        }).status_code, 200)

    def test_servico_de_cancelamento_rejeita_usuario_de_outra_unidade(self):
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=timezone.localdate())
        usuario = get_user_model().objects.create_user(username="outro_gestor", password="senha-testes")
        criar_funcionario(usuario=usuario, unidade=self.b)
        usuario.groups.add(Group.objects.get(name="GymInsight Gerente"))
        with self.assertRaises(ValidationError):
            cancelar_matricula(matricula=matricula, motivo="Sem autorização", usuario=usuario)
        matricula.refresh_from_db()
        self.assertEqual(matricula.status, Matricula.Status.ATIVA)

    def test_registro_entrada_exige_permissao_especifica(self):
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=timezone.localdate())
        usuario = get_user_model().objects.create_user(username="operador", password="senha-testes")
        criar_funcionario(usuario=usuario, unidade=self.a)
        usuario.user_permissions.add(
            Permission.objects.get(codename="add_frequencia"),
            Permission.objects.get(codename="view_matricula"),
        )
        self.client.force_authenticate(usuario)
        self.assertEqual(self.client.post("/api/frequencias/", {"matricula": matricula.pk}).status_code, 403)
        with self.assertRaises(ValidationError):
            registrar_entrada(matricula=matricula, usuario=usuario)
        usuario.user_permissions.add(Permission.objects.get(codename="registrar_frequencia"))
        usuario.groups.add(Group.objects.get(name="GymInsight Atendimento"))
        self.client.force_authenticate(get_user_model().objects.get(pk=usuario.pk))
        self.assertEqual(self.client.post("/api/frequencias/", {"matricula": matricula.pk}).status_code, 201)

    def test_remover_grupo_revoga_acesso_na_proxima_requisicao(self):
        self.assertEqual(self.client.get("/api/alunos/").status_code, 200)
        self.user.groups.clear()
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.assertEqual(self.client.get("/api/alunos/").status_code, 403)

    def test_servicos_consultam_unidade_real_da_matricula(self):
        hoje = timezone.localdate()
        real = Matricula.objects.create(
            aluno=self.aluno_b, plano=self.plano_b, inicio=hoje, fim=hoje + timedelta(days=29),
        )
        forjada = Matricula(
            pk=real.pk, aluno=self.aluno_a, plano=self.plano_a,
            inicio=hoje, fim=hoje + timedelta(days=29),
        )
        with self.assertRaises(ValidationError):
            cancelar_matricula(matricula=forjada, motivo="Tentativa", usuario=self.user)
        with self.assertRaises(ValidationError):
            registrar_entrada(matricula=forjada, usuario=self.user)
        real.refresh_from_db()
        self.assertEqual(real.status, Matricula.Status.ATIVA)
        self.assertFalse(Frequencia.objects.filter(matricula=real).exists())

    def test_logs_guardam_usuario_acao_e_campos_sem_valores_pessoais(self):
        resposta = self.client.post("/api/alunos/", {
            "nome": "Pessoa de teste", "email": "teste@example.com",
            "plano": self.plano_a.pk, "inicio": timezone.localdate().isoformat(),
        })
        self.assertEqual(resposta.status_code, 201, resposta.data)
        aluno_id = resposta.data["id"]
        self.assertEqual(self.client.patch(f"/api/alunos/{aluno_id}/", {
            "nome": "Nome corrigido",
        }).status_code, 200)
        criacao = LogAuditoria.objects.get(entidade="aluno", objeto_id=str(aluno_id), acao="criado")
        alteracao = LogAuditoria.objects.get(entidade="aluno", objeto_id=str(aluno_id), acao="alterado", campos_alterados=["nome"])
        self.assertEqual(criacao.usuario, self.user)
        self.assertEqual(alteracao.unidade, self.a)
        self.assertNotIn("Pessoa de teste", str(list(LogAuditoria.objects.values())))
        self.assertNotIn("teste@example.com", str(list(LogAuditoria.objects.values())))

    def test_logs_de_entrada_cancelamento_e_permissoes(self):
        matricula = criar_matricula(aluno=self.aluno_a, plano=self.plano_a, inicio=timezone.localdate())
        registro = registrar_entrada(matricula=matricula, usuario=self.user)
        entrada = LogAuditoria.objects.get(entidade="frequencia", objeto_id=str(registro.pk), acao="criado")
        self.assertEqual(entrada.usuario, self.user)
        cancelar_matricula(matricula=matricula, motivo="Motivo particular", usuario=self.user)
        cancelamento = LogAuditoria.objects.get(entidade="matricula", objeto_id=str(matricula.pk), acao="alterado")
        self.assertIn("status", cancelamento.campos_alterados)
        self.assertIn("motivo_cancelamento", cancelamento.campos_alterados)
        self.assertNotIn("Motivo particular", str(list(LogAuditoria.objects.values())))
        outro = get_user_model().objects.create_user(username="novo_membro", password="senha-testes")
        perfil = criar_funcionario(usuario=outro, unidade=self.a)
        with ator_da_operacao(self.user):
            outro.groups.add(Group.objects.get_or_create(name="GymInsight Consulta")[0])
        permissao = LogAuditoria.objects.filter(entidade="funcionario", objeto_id=str(perfil.pk), campos_alterados=["grupos"]).latest("pk")
        self.assertEqual(permissao.usuario, self.user)

    def test_auditoria_restringe_unidade_e_apenas_gestor_consulta(self):
        resposta = self.client.get("/api/auditoria/")
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(all(item["unidade"] == self.a.pk for item in resposta.data["results"]))
        self.assertEqual(self.client.post("/api/auditoria/", {}).status_code, 403)
        consulta = get_user_model().objects.create_user(username="consulta_logs", password="senha-testes")
        criar_funcionario(usuario=consulta, unidade=self.a)
        consulta.groups.add(Group.objects.get_or_create(name="GymInsight Consulta")[0])
        self.client.force_authenticate(consulta)
        self.assertEqual(self.client.get("/api/auditoria/").status_code, 403)

    def test_rollback_remove_tambem_o_log(self):
        antes = LogAuditoria.objects.filter(entidade="plano", acao="criado").count()
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                Plano.objects.create(unidade=self.a, nome="Plano revertido", duracao_dias=5, preco="50.00")
                raise RuntimeError("Falha simulada")
        self.assertFalse(Plano.objects.filter(nome="Plano revertido").exists())
        self.assertEqual(LogAuditoria.objects.filter(entidade="plano", acao="criado").count(), antes)
