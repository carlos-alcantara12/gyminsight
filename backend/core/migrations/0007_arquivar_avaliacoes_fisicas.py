from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("core", "0006_avaliacaofisica")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(
                sql="ALTER TABLE core_avaliacaofisica RENAME TO core_avaliacaofisica_arquivo",
                reverse_sql="ALTER TABLE core_avaliacaofisica_arquivo RENAME TO core_avaliacaofisica",
            )],
            state_operations=[migrations.DeleteModel(name="AvaliacaoFisica")],
        ),
    ]
