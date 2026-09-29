from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def migrar_equipe(apps, schema_editor):
    Professor = apps.get_model("core", "Professor")
    PerfilUsuario = apps.get_model("core", "PerfilUsuario")
    Funcionario = apps.get_model("core", "Funcionario")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    db = schema_editor.connection.alias
    for professor in Professor.objects.using(db).order_by("pk"):
        Funcionario.objects.using(db).create(
            unidade_id=professor.unidade_id, nome=professor.nome,
            email=professor.email, ativo=professor.ativo, cargo="professor",
        )
    for perfil in PerfilUsuario.objects.using(db).order_by("pk"):
        usuario = User.objects.using(db).get(pk=perfil.usuario_id)
        grupos = set(usuario.groups.using(db).values_list("name", flat=True))
        cargo = "gerente" if grupos.intersection({"GymInsight Gerente", "GymInsight Gestor"}) else (
            "atendente" if "GymInsight Atendimento" in grupos else "outro"
        )
        Funcionario.objects.using(db).create(
            unidade_id=perfil.unidade_id,
            nome=f"{usuario.first_name} {usuario.last_name}".strip() or usuario.username,
            email=usuario.email or "", cargo=cargo, ativo=usuario.is_active,
            usuario_id=usuario.pk if cargo != "outro" else None,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007_arquivar_avaliacoes_fisicas"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Funcionario",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=150)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("cargo", models.CharField(choices=[("gerente", "Gerente"), ("atendente", "Atendente"), ("professor", "Professor"), ("faxineiro", "Faxineiro"), ("outro", "Outro")], max_length=12)),
                ("ativo", models.BooleanField(default=True)),
                ("unidade", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="funcionarios", to="core.unidade")),
                ("usuario", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="funcionario_academia", to=settings.AUTH_USER_MODEL)),
            ],
            options={"permissions": [("ver_contato_funcionario", "Pode consultar contato do funcionário")]},
        ),
        migrations.RunPython(migrar_equipe),
        migrations.DeleteModel(name="Professor"),
        migrations.DeleteModel(name="PerfilUsuario"),
    ]
