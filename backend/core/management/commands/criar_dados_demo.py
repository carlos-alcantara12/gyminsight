"""Cria matrículas e frequências fictícias para testar o GymInsight."""

from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import Aluno, Frequencia, Matricula, Funcionario, Plano, Unidade
from core.services import cadastrar_aluno_com_matricula, criar_matricula, encerrar_matriculas_vencidas, registrar_entrada


class Command(BaseCommand):
    help = "Cria uma unidade, dez alunos fictícios, dez matrículas e dez entradas. Pode ser repetido."

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            grupo = Group.objects.get(name="GymInsight Atendimento")
        except Group.DoesNotExist as exc:
            raise CommandError("Execute migrate e configurar_grupos antes de criar os dados de demonstração.") from exc

        nome_usuario = "gyminsight_demo_operador"
        operador = get_user_model().objects.filter(username=nome_usuario).first()
        if operador is not None and (operador.has_usable_password() or operador.is_staff or operador.is_superuser):
            raise CommandError("O usuário reservado para demonstração já existe com acesso; nenhum dado foi criado.")

        unidade, _ = Unidade.objects.get_or_create(nome="GymInsight - Unidade Demonstracao", defaults={
            "ativa": True, "abre_domingo": True, "domingo_inicio": time(0, 0), "domingo_fim": time(23, 59),
        })
        if not unidade.ativa:
            raise CommandError("A unidade de demonstração está inativa; nenhum dado foi criado.")
        if operador is None:
            operador = get_user_model().objects.create_user(username=nome_usuario, password=None)
        funcionario, _ = Funcionario.objects.get_or_create(usuario=operador, defaults={
            "unidade": unidade, "nome": "Operador da demonstração", "cargo": Funcionario.Cargo.ATENDENTE,
        })
        if funcionario.unidade_id != unidade.pk or funcionario.cargo != Funcionario.Cargo.ATENDENTE:
            raise CommandError("O operador reservado pertence a outra unidade; nenhum dado foi criado.")
        operador.groups.add(grupo)

        plano, _ = Plano.objects.get_or_create(
            unidade=unidade, nome="Mensal demonstracao", defaults={"duracao_dias": 30, "preco": "90.00"},
        )
        if not plano.ativo or plano.duracao_dias < 15:
            raise CommandError("O plano de demonstração foi alterado; nenhum dado foi criado.")

        hoje = timezone.localdate()
        criadas = 0
        entradas = 0
        for nome, email, dias_atras in (
            ("Ana Demo", "ana.demo@example.invalid", 9),
            ("Bruno Demo", "bruno.demo@example.invalid", 8),
            ("Carla Demo", "carla.demo@example.invalid", 7),
            ("Daniela Demo", "daniela.demo@example.invalid", 6),
            ("Eduardo Demo", "eduardo.demo@example.invalid", 5),
            ("Fernanda Demo", "fernanda.demo@example.invalid", 4),
            ("Gabriel Demo", "gabriel.demo@example.invalid", 3),
            ("Helena Demo", "helena.demo@example.invalid", 2),
            ("Igor Demo", "igor.demo@example.invalid", 1),
            ("Julia Demo", "julia.demo@example.invalid", 0),
        ):
            matricula_criada = False
            aluno = Aluno.objects.filter(unidade=unidade, email=email).first()
            if aluno is None:
                aluno, matricula = cadastrar_aluno_com_matricula(
                    unidade=unidade, plano=plano, inicio=hoje - timedelta(days=14),
                    dados_aluno={"nome": nome, "email": email},
                )
                criadas += 1
                matricula_criada = True
            else:
                encerrar_matriculas_vencidas(aluno=aluno)
                matricula = aluno.matriculas.filter(status=Matricula.Status.ATIVA).first()
                if matricula is None:
                    matricula = criar_matricula(aluno=aluno, plano=plano, inicio=hoje)
                    criadas += 1
                    matricula_criada = True
            if not matricula_criada:
                continue
            dia = hoje - timedelta(days=dias_atras)
            if not matricula.inicio <= dia <= matricula.fim:
                continue  # Uma renovação futura não reescreve frequências antigas.
            if Frequencia.objects.filter(matricula=matricula, entrada_em__date=dia).exists():
                continue
            instante = (
                timezone.now() - timedelta(seconds=1)
                if dias_atras == 0
                else timezone.make_aware(datetime.combine(dia, time(12, 0)))
            )
            registrar_entrada(matricula=matricula, usuario=operador, instante=instante)
            entradas += 1
        self.stdout.write(self.style.SUCCESS(
            f"Unidade {unidade.pk}: 10 alunos demonstrativos; {criadas} matrícula(s) criada(s); "
            f"{entradas} entrada(s) criada(s)."
        ))
