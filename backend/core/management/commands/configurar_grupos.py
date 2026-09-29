from django.core.management.base import BaseCommand

from core.access import configurar_grupos_padrao


class Command(BaseCommand):
    help = "Cria ou atualiza os grupos de acesso do GymInsight. Execute após migrate."

    def handle(self, *args, **options):
        configurar_grupos_padrao()
        self.stdout.write(self.style.SUCCESS("Grupos do GymInsight configurados."))
