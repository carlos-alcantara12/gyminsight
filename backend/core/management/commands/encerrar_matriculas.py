from django.core.management.base import BaseCommand

from core.services import encerrar_matriculas_vencidas, sincronizar_status_alunos


class Command(BaseCommand):
    help = "Encerra matrículas vencidas e atualiza o status dos alunos."

    def handle(self, *args, **options):
        total = encerrar_matriculas_vencidas()
        alterados = sincronizar_status_alunos()
        self.stdout.write(self.style.SUCCESS(f"{total} matrícula(s) encerrada(s); {alterados} aluno(s) atualizado(s)."))
