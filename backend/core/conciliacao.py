"""Conciliação explícita de pagamentos anteriores ao controle por competência."""

from django.core.exceptions import ValidationError
from django.db import transaction

from .access import usuario_tem_permissao
from .audit_context import ator_da_operacao
from .models import ConciliacaoLegado, Matricula, Pagamento


@transaction.atomic
def conciliar_pagamento(*, pagamento, destino, justificativa, usuario):
    """Classifica um pagamento legado sem perder seu valor, data ou vínculo original."""
    matricula_id = Pagamento.objects.values_list("matricula_id", flat=True).get(pk=pagamento.pk)
    matricula = Matricula.objects.select_for_update().get(pk=matricula_id)
    pagamento = Pagamento.objects.select_for_update().select_related("matricula__aluno").get(pk=pagamento.pk)
    if pagamento.matricula_id != matricula.pk:
        raise ValidationError({"pagamento": "O vínculo deste pagamento mudou; tente novamente."})
    if not usuario_tem_permissao(usuario=usuario, model=Pagamento, acao="update",
                                 unidade_id=pagamento.matricula.aluno.unidade_id):
        raise ValidationError({"usuario": "Somente o gerente da unidade pode conciliar pagamentos."})
    if not justificativa or not justificativa.strip():
        raise ValidationError({"justificativa": "Registre por que este lançamento recebeu esta classificação."})
    if pagamento.competencia is not None or hasattr(pagamento, "conciliacao_legado"):
        raise ValidationError({"pagamento": "Este lançamento já foi conciliado."})
    if hasattr(matricula, "acerto_cancelamento"):
        raise ValidationError({"matricula": "Matrículas com acerto de cancelamento exigem análise individual."})
    if destino == ConciliacaoLegado.Destino.ASSOCIADO:
        if pagamento.status == Pagamento.Status.CANCELADO:
            raise ValidationError({"pagamento": "Cobrança cancelada não pode ser associada."})
        if matricula.valor_contratado is None:
            raise ValidationError({"valor_contratado": "Confirme o preço acordado antes de associar o pagamento."})
        if pagamento.valor != matricula.valor_contratado:
            raise ValidationError({"valor": "O valor do pagamento difere do preço acordado; concilie a diferença antes."})
        competencia = matricula.inicio.replace(day=1)
        if Pagamento.objects.filter(matricula=matricula, competencia=competencia).exists():
            raise ValidationError({"competencia": "Este período já possui uma cobrança associada."})
        if Pagamento.objects.filter(matricula=matricula, competencia__isnull=False).exists():
            raise ValidationError({"competencia": "Revise a outra competência já vinculada a esta matrícula."})
    elif destino == ConciliacaoLegado.Destino.AVULSO:
        if pagamento.status != Pagamento.Status.PAGO or pagamento.pago_em is None:
            raise ValidationError({"destino": "Somente valores efetivamente pagos podem ser classificados como avulsos."})
    elif destino == ConciliacaoLegado.Destino.DESCARTADO:
        if pagamento.status != Pagamento.Status.PENDENTE:
            raise ValidationError({"destino": "Somente uma cobrança pendente pode ser descartada."})
    else:
        raise ValidationError({"destino": "Selecione uma classificação válida."})
    with ator_da_operacao(usuario):
        if destino == ConciliacaoLegado.Destino.ASSOCIADO:
            pagamento.competencia = competencia
            pagamento.save(update_fields=["competencia"])
        elif destino == ConciliacaoLegado.Destino.DESCARTADO:
            pagamento.status = Pagamento.Status.CANCELADO
            pagamento.save(update_fields=["status"])
        conciliacao = ConciliacaoLegado.objects.create(
            pagamento=pagamento, destino=destino, justificativa=justificativa.strip(), responsavel=usuario,
        )
    return conciliacao
