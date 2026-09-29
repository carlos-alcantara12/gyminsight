from django.contrib.auth import get_user_model
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import receiver
from contextvars import ContextVar

from .audit_context import ator_atual
from .models import AcertoCancelamento, Aluno, ConciliacaoLegado, ConfiguracaoRede, Feriado, Frequencia, LogAuditoria, Matricula, Pagamento, Funcionario, Plano, Unidade


MODELOS_AUDITADOS = (Unidade, Aluno, Plano, Matricula, Frequencia, Pagamento, Funcionario, Feriado, AcertoCancelamento, ConciliacaoLegado)
_sincronizando_planos = ContextVar("sincronizando_planos", default=False)


def unidade_do_objeto(obj):
    if isinstance(obj, Unidade):
        return obj.pk
    if isinstance(obj, (Aluno, Plano, Funcionario, Feriado)):
        return obj.unidade_id
    if isinstance(obj, Matricula):
        return obj.aluno.unidade_id
    if isinstance(obj, (Frequencia, Pagamento, AcertoCancelamento)):
        return obj.matricula.aluno.unidade_id
    if isinstance(obj, ConciliacaoLegado):
        return obj.pagamento.matricula.aluno.unidade_id
    raise TypeError("Entidade sem unidade de auditoria")


def registrar(obj, acao, campos=()):
    usuario = ator_atual()
    LogAuditoria.objects.create(
        unidade_id=unidade_do_objeto(obj),
        usuario=usuario if usuario and usuario.pk else None,
        acao=acao,
        entidade=obj._meta.model_name,
        objeto_id=str(obj.pk),
        campos_alterados=sorted(campos),
    )


@receiver(pre_save)
def capturar_campos_alterados(sender, instance, **kwargs):
    if sender not in MODELOS_AUDITADOS or not instance.pk:
        return
    nomes = [campo.attname for campo in sender._meta.concrete_fields if not campo.primary_key]
    anterior = sender.objects.filter(pk=instance.pk).values(*nomes).first()
    instance._audit_campos_alterados = (
        [nome for nome in nomes if anterior[nome] != getattr(instance, nome)]
        if anterior is not None else []
    )


@receiver(post_save)
def registrar_salvamento(sender, instance, created, **kwargs):
    if sender not in MODELOS_AUDITADOS:
        return
    campos = getattr(instance, "_audit_campos_alterados", [])
    if created:
        registrar(instance, "criado")
    elif campos:
        registrar(instance, "alterado", campos)


@receiver(post_save, sender=Unidade)
def provisionar_planos_rede(sender, instance, created, **kwargs):
    if not created or not ConfiguracaoRede.habilitada():
        return
    referencia = Unidade.objects.exclude(pk=instance.pk).order_by("pk").first()
    if referencia:
        for original in Plano.objects.filter(unidade=referencia, nome__in=("Tradicional", "Premium", "Diamante")):
            Plano.objects.get_or_create(unidade=instance, nome=original.nome, defaults={
                "categoria": original.categoria, "duracao_dias": original.duracao_dias,
                "preco": original.preco, "ativo": original.ativo,
                "acesso_tradicional_rede": original.acesso_tradicional_rede,
            })


@receiver(post_save, sender=Plano)
def sincronizar_catalogo_rede(sender, instance, **kwargs):
    if _sincronizando_planos.get() or instance.nome not in ("Tradicional", "Premium", "Diamante") or not ConfiguracaoRede.habilitada():
        return
    campos = {"categoria": instance.categoria, "duracao_dias": instance.duracao_dias,
              "preco": instance.preco, "ativo": instance.ativo,
              "acesso_tradicional_rede": instance.acesso_tradicional_rede}
    token = _sincronizando_planos.set(True)
    try:
        for unidade in Unidade.objects.exclude(pk=instance.unidade_id):
            Plano.objects.update_or_create(unidade=unidade, nome=instance.nome, defaults=campos)
    finally:
        _sincronizando_planos.reset(token)


@receiver(post_delete)
def registrar_exclusao(sender, instance, **kwargs):
    if sender in MODELOS_AUDITADOS:
        registrar(instance, "excluido")


Usuario = get_user_model()


@receiver(m2m_changed, sender=Usuario.groups.through)
@receiver(m2m_changed, sender=Usuario.user_permissions.through)
def registrar_permissoes_usuario(sender, instance, action, reverse, **kwargs):
    if reverse or action not in ("post_add", "post_remove", "post_clear"):
        return
    perfil = Funcionario.objects.filter(usuario=instance).first()
    if perfil:
        campo = "grupos" if sender == Usuario.groups.through else "permissoes_diretas"
        registrar(perfil, "alterado", (campo,))


@receiver(m2m_changed, sender=Funcionario.unidades_acesso.through)
def registrar_acesso_unidades(sender, instance, action, reverse, **kwargs):
    if not reverse and action in ("post_add", "post_remove", "post_clear"):
        registrar(instance, "alterado", ("unidades_acesso",))
