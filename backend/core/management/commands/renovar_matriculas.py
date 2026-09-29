from django.core.management.base import BaseCommand

from core.services import renovar_matriculas_automaticamente


class Command(BaseCommand):
    help = "Renova somente matrículas vencidas com todos os períodos anteriores quitados."

    def handle(self, *args, **options):
        totais = renovar_matriculas_automaticamente()
        self.stdout.write(self.style.SUCCESS(
            f"{totais['renovadas']} matrícula(s) renovada(s); "
            f"{totais['pendencias']} bloqueada(s) por pendências financeiras; "
            f"{totais['inaptas']} inapta(s) por plano, unidade ou contratação posterior."
        ))
