"""Backup consistente do SQLite por meio da API de backup do próprio banco."""

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


def verificar_backup(arquivo):
    arquivo = Path(arquivo)
    manifesto = arquivo.with_name(arquivo.name + ".json")
    try:
        dados = json.loads(manifesto.read_text(encoding="utf-8"))
        if dados["arquivo"] != arquivo.name:
            raise ValueError("O manifesto não corresponde ao arquivo.")
        resumo = hash_arquivo(arquivo)
        if dados["sha256"] != resumo:
            raise ValueError("O SHA-256 do backup não confere.")
        with sqlite3.connect(f"file:{arquivo.resolve().as_posix()}?mode=ro", uri=True) as banco:
            if banco.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("O banco do backup está corrompido.")
    except (OSError, ValueError, KeyError, sqlite3.DatabaseError) as exc:
        raise CommandError(f"Backup inválido: {exc}") from exc
    return dados


def hash_arquivo(arquivo):
    digest = hashlib.sha256()
    with Path(arquivo).open("rb") as entrada:
        for bloco in iter(lambda: entrada.read(1024 * 1024), b""):
            digest.update(bloco)
    return digest.hexdigest()


class Command(BaseCommand):
    help = "Cria ou verifica backup consistente do banco SQLite. Não envia arquivos para armazenamento externo."

    def add_arguments(self, parser):
        parser.add_argument("--diretorio", type=Path, help="Pasta de destino (obrigatória ao criar).")
        parser.add_argument("--verificar", type=Path, help="Confere integridade e SHA-256 de um backup existente.")

    def handle(self, *args, **options):
        if connection.vendor != "sqlite":
            raise CommandError("Este comando aceita apenas SQLite; use a ferramenta nativa de backup do seu banco.")
        if options["verificar"]:
            verificar_backup(options["verificar"])
            self.stdout.write(self.style.SUCCESS("Backup íntegro e SHA-256 confirmado."))
            return
        diretorio = options["diretorio"]
        if diretorio is None:
            raise CommandError("Informe --diretorio para criar o backup.")
        diretorio = diretorio.resolve()
        banco_original = Path(settings.DATABASES["default"]["NAME"]).resolve()
        raiz_projeto = Path(settings.BASE_DIR).parent.resolve()
        if diretorio == raiz_projeto or diretorio.is_relative_to(raiz_projeto):
            raise CommandError("Guarde os backups fora da pasta do projeto e do banco.")
        diretorio.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            os.chmod(diretorio, 0o700)
        nome = f"gyminsight-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.sqlite3"
        destino = diretorio / nome
        fd, temporario = tempfile.mkstemp(prefix=".backup-", suffix=".sqlite3", dir=diretorio)
        try:
            if os.name != "nt":
                os.fchmod(fd, 0o600)
            os.close(fd)
            # SQLite mantém um snapshot consistente mesmo durante escritas concorrentes.
            connection.ensure_connection()
            with sqlite3.connect(temporario) as copia:
                connection.connection.backup(copia)
                if copia.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise CommandError("O banco copiado falhou na verificação de integridade.")
            resumo = hash_arquivo(temporario)
            os.replace(temporario, destino)
            manifesto = destino.with_name(destino.name + ".json")
            fd_manifesto = os.open(manifesto, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd_manifesto, "w", encoding="utf-8") as saida:
                json.dump({"arquivo": nome, "sha256": resumo, "criado_em_utc": datetime.now(timezone.utc).isoformat()}, saida)
            verificar_backup(destino)
        except (OSError, sqlite3.DatabaseError) as exc:
            destino.unlink(missing_ok=True)
            raise CommandError(f"Falha ao criar backup: {exc}") from exc
        finally:
            Path(temporario).unlink(missing_ok=True)
        self.stdout.write(self.style.SUCCESS(f"Backup verificado: {destino}"))
