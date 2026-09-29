"""Popula uma rede fictícia sem tocar em dados de unidades existentes."""

from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import Aluno, ConfiguracaoRede, Feriado, Funcionario, Matricula, Pagamento, Plano, Unidade
from core.services import cancelar_matricula, criar_matricula


ZONAS = ("Zona Norte", "Zona Sul", "Zona Oeste", "Centro-Oeste", "Zona Sudeste")
PLANOS = (("Tradicional", "tradicional", "89.90"), ("Premium", "premium", "129.90"),
          ("Diamante", "diamante", "179.90"))
FERIADOS = ((1, 1, "Confraternização Universal"), (4, 3, "Paixão de Cristo"),
            (4, 21, "Tiradentes"), (5, 1, "Dia Mundial do Trabalho"),
            (9, 7, "Independência do Brasil"), (10, 12, "Nossa Senhora Aparecida"),
            (11, 2, "Finados"), (11, 15, "Proclamação da República"),
            (11, 20, "Dia Nacional de Zumbi e da Consciência Negra"), (12, 25, "Natal"))


class Command(BaseCommand):
    help = "Cria cinco unidades fictícias, catálogo compartilhado, 50 alunos e feriados de 2026."

    def add_arguments(self, parser):
        parser.add_argument("--ano", type=int, default=2026, help="Ano dos feriados; 3 de abril é específico de 2026.")

    @transaction.atomic
    def handle(self, *args, **options):
        ano = options["ano"]
        if ano != 2026:
            raise CommandError("A Paixão de Cristo em 3 de abril corresponde a 2026. Use --ano 2026.")
        if ConfiguracaoRede.habilitada() and any(not Unidade.objects.filter(nome=f"GymInsight - {zona}").exists() for zona in ZONAS):
            raise CommandError("A rede já foi ativada com outras unidades. Não misture este exemplo com dados reais.")
        nomes = [f"GymInsight - {zona}" for zona in ZONAS]
        if Unidade.objects.exclude(nome__in=nomes).exists():
            raise CommandError("Há unidades fora da demonstração. Execute este comando em um banco de teste separado.")
        if Aluno.objects.filter(unidade__nome__in=nomes).exclude(nome__regex=r"^aluno[0-9]{2}$").exists():
            raise CommandError("Há alunos reais nas unidades de demonstração; não altere esse banco.")
        try:
            grupo = Group.objects.get(name="GymInsight Gerente")
        except Group.DoesNotExist as exc:
            raise CommandError("Execute configurar_grupos antes deste comando.") from exc

        unidades = []
        for zona in ZONAS:
            unidade, _ = Unidade.objects.get_or_create(nome=f"GymInsight - {zona}", defaults={"endereco": zona})
            unidade.ativa = True
            unidade.semana_inicio, unidade.semana_fim = time(5), time(23)
            unidade.sabado_inicio, unidade.sabado_fim = time(5), time(18)
            unidade.abre_domingo = False
            unidade.domingo_inicio = unidade.domingo_fim = None
            unidade.abre_feriado = True
            unidade.feriado_inicio, unidade.feriado_fim = time(8), time(14)
            unidade.full_clean()
            unidade.save()
            unidades.append(unidade)
            for mes, dia, nome in FERIADOS:
                Feriado.objects.get_or_create(unidade=unidade, data=date(ano, mes, dia), defaults={"nome": nome})

        # A ativação ocorre depois da preparação, evitando sincronizações parciais.
        ConfiguracaoRede.objects.update_or_create(pk=1, defaults={"ativa": False})
        for unidade in unidades:
            for nome, categoria, preco in PLANOS:
                Plano.objects.update_or_create(unidade=unidade, nome=nome, defaults={
                    "categoria": categoria, "preco": preco, "duracao_dias": 30,
                    "ativo": True, "acesso_tradicional_rede": False,
                })
            Plano.objects.filter(unidade=unidade).exclude(nome__in=[p[0] for p in PLANOS]).update(ativo=False)
        ConfiguracaoRede.objects.update_or_create(pk=1, defaults={"ativa": True})

        login = "gyminsight_rede_demo"
        operador = get_user_model().objects.filter(username=login).first()
        if operador is not None and operador.has_usable_password():
            raise CommandError("O nome de usuário da demonstração já possui senha; escolha um banco de teste.")
        if operador is None:
            operador = get_user_model().objects.create_user(username=login, password=None)
        operador.groups.add(grupo)
        funcionario, _ = Funcionario.objects.get_or_create(usuario=operador, defaults={
            "unidade": unidades[0], "nome": "Gerente fictício da rede", "cargo": Funcionario.Cargo.GERENTE,
        })
        if funcionario.cargo != Funcionario.Cargo.GERENTE or funcionario.unidade_id != unidades[0].pk:
            raise CommandError("O operador reservado pertence a outro cargo ou unidade.")
        funcionario.unidades_acesso.add(*unidades[1:])

        hoje = timezone.localdate()
        for indice in range(1, 51):
            unidade = unidades[(indice - 1) // 10]
            nome = f"aluno{indice:02d}"
            aluno, criado = Aluno.objects.get_or_create(unidade=unidade, nome=nome)
            if not criado:
                continue  # Reexecutar nunca reescreve um contrato já criado.
            plano = Plano.objects.get(unidade=unidade, nome=PLANOS[(indice - 1) % 3][0])
            posicao = (indice - 1) % 10
            inicio = hoje + timedelta(days=5) if posicao in (3, 4, 5) else hoje - timedelta(days=5)
            matricula = criar_matricula(aluno=aluno, plano=plano, inicio=inicio)
            if posicao in (6, 7):
                cancelar_matricula(matricula=matricula, motivo="Cancelamento fictício", usuario=operador,
                                   decisao="cancelar", justificativa="Dados de demonstração")
            elif posicao in (8, 9):
                cobranca = Pagamento.objects.get(matricula=matricula)
                cobranca.status = Pagamento.Status.PAGO
                cobranca.pago_em = timezone.now()
                cobranca.forma_pagamento = Pagamento.Forma.PIX
                cobranca.confirmado_por = operador
                cobranca.full_clean()
                cobranca.save()
        self.stdout.write(self.style.SUCCESS("Rede fictícia criada: 5 unidades, 3 planos compartilhados, 50 alunos e 10 feriados por unidade."))
