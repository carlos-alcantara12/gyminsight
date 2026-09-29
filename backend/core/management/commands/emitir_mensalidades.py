"""Rotina diária para cobrança de períodos contratados já iniciados."""
from django.core.management.base import BaseCommand

from core.financeiro import emitir_cobrancas_devidas


class Command(BaseCommand):
    help = "Emite cobranças de matrículas iniciadas até hoje sem pagamento anterior; pode rodar repetidamente."

    def handle(self, *args, **options):
        totais = emitir_cobrancas_devidas()
        self.stdout.write(self.style.SUCCESS(
            f"{totais['criadas']} cobrança(s) criada(s); "
            f"{totais['ja_emitidas']} já emitida(s); "
            f"{totais['sem_valor']} matrícula(s) sem valor contratado; "
            f"{totais['pagamentos_legados']} matrícula(s) com pagamento antigo para conciliar."
        ))
