"""Processa encerramento, renovação e emissão na mesma execução."""

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Encerra matrículas, renova as quitadas e emite cobranças devidas, nesta ordem."

    def handle(self, *args, **options):
        self.stdout.write("Iniciando encerramento das matrículas e atualização dos alunos.")
        call_command("encerrar_matriculas", stdout=self.stdout, stderr=self.stderr)
        self.stdout.write("Iniciando renovação automática dos períodos quitados.")
        call_command("renovar_matriculas", stdout=self.stdout, stderr=self.stderr)
        self.stdout.write("Iniciando emissão das cobranças devidas.")
        call_command("emitir_mensalidades", stdout=self.stdout, stderr=self.stderr)
        self.stdout.write(self.style.SUCCESS("Rotina diária concluída."))
