from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.access import configurar_grupos_padrao
from core.models import ConfiguracaoRede, Funcionario, Unidade


class Command(BaseCommand):
    help = "Vincula um superusuário existente à unidade e ao grupo Gerente para acesso inicial ao Admin."

    def add_arguments(self, parser):
        parser.add_argument("--usuario", required=True)
        parser.add_argument("--unidade", required=True, help="Nome da unidade inicial")

    @transaction.atomic
    def handle(self, *args, **options):
        usuario = get_user_model().objects.filter(username=options["usuario"], is_superuser=True, is_active=True).first()
        if not usuario:
            raise CommandError("Informe um superusuário ativo já criado por createsuperuser.")
        configurar_grupos_padrao()
        unidade, _ = Unidade.objects.get_or_create(nome=options["unidade"])
        if not unidade.ativa:
            raise CommandError("A unidade informada está inativa.")
        funcionario, _ = Funcionario.objects.update_or_create(usuario=usuario, defaults={
            "unidade": unidade, "nome": usuario.get_full_name() or usuario.username,
            "email": usuario.email or "", "cargo": Funcionario.Cargo.GERENTE, "ativo": True,
        })
        if ConfiguracaoRede.habilitada():
            funcionario.unidades_acesso.add(*Unidade.objects.filter(ativa=True).exclude(pk=unidade.pk))
        usuario.groups.add(Group.objects.get(name="GymInsight Gerente"))
        self.stdout.write(self.style.SUCCESS("Gerente vinculado à unidade."))
