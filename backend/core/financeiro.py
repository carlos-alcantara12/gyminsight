"""Mensalidades por mês de competência e posição financeira por unidade."""
import calendar
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum, Count, Q, Exists, OuterRef
from django.utils import timezone

from .models import ConciliacaoLegado, Matricula, Pagamento


def primeiro_dia(valor):
    if valor.day != 1:
        raise ValidationError({"competencia": "Use o primeiro dia do mês (AAAA-MM-01)."})
    return valor


def ultimo_dia(competencia):
    return date(competencia.year, competencia.month, calendar.monthrange(competencia.year, competencia.month)[1])


def emitir_cobranca_contratual(matricula):
    """Cada matrícula paga um período contratado; virar o mês não cria nova parcela."""
    if matricula.valor_contratado is None:
        raise ValidationError({"valor_contratado": f"Confirme o valor da matrícula {matricula.pk} antes de gerar sua cobrança histórica."})
    competencia = matricula.inicio.replace(day=1)
    existente = Pagamento.objects.filter(matricula=matricula, competencia=competencia).first()
    if existente:
        return existente, False
    if Pagamento.objects.filter(matricula=matricula, competencia__isnull=True,
                                conciliacao_legado__isnull=True).exclude(status=Pagamento.Status.CANCELADO).exists():
        raise ValidationError({"matricula": f"A matrícula {matricula.pk} já possui pagamentos sem vínculo com este ciclo. Concilie o histórico antes de emitir outra cobrança."})
    if Pagamento.objects.filter(matricula=matricula, competencia__isnull=False).exists():
        raise ValidationError({"matricula": "Já há uma cobrança de outra competência vinculada a esta matrícula. Revise o histórico."})
    return Pagamento.objects.get_or_create(
        matricula=matricula, competencia=competencia,
        defaults={"valor": matricula.valor_contratado, "vencimento": matricula.inicio},
    )


def emitir_cobrancas_devidas(*, data_referencia=None):
    """Recupera faturas ausentes até hoje, sem antecipar períodos ou duplicar legados."""
    hoje = timezone.localdate()
    data_referencia = data_referencia or hoje
    if data_referencia > hoje:
        raise ValidationError({"data_referencia": "Não é permitido emitir antecipadamente períodos futuros."})
    qualquer_pagamento = Pagamento.objects.filter(matricula_id=OuterRef("pk"))
    pagamento_pendente_conciliacao = qualquer_pagamento.filter(
        competencia__isnull=True, conciliacao_legado__isnull=True,
    ).exclude(status=Pagamento.Status.CANCELADO)
    cobranca_do_periodo = qualquer_pagamento.filter(competencia__year=OuterRef("inicio__year"),
                                                    competencia__month=OuterRef("inicio__month"))
    outra_competencia = qualquer_pagamento.filter(competencia__isnull=False).exclude(
        competencia__year=OuterRef("inicio__year"), competencia__month=OuterRef("inicio__month"),
    )
    contratos = Matricula.objects.filter(
        status__in=(Matricula.Status.ATIVA, Matricula.Status.ENCERRADA),
        inicio__lte=data_referencia,
    ).annotate(tem_pagamento=Exists(pagamento_pendente_conciliacao),
               tem_outra_competencia=Exists(outra_competencia), tem_cobranca=Exists(cobranca_do_periodo))
    totais = {"criadas": 0, "ja_emitidas": 0, "sem_valor": 0, "pagamentos_legados": 0}
    for matricula in contratos.iterator(chunk_size=500):
        if matricula.tem_cobranca:
            totais["ja_emitidas"] += 1
        elif matricula.tem_pagamento or matricula.tem_outra_competencia:
            totais["pagamentos_legados"] += 1
        elif matricula.valor_contratado is None:
            totais["sem_valor"] += 1
        else:
            _, criada = emitir_cobranca_contratual(matricula)
            totais["criadas" if criada else "ja_emitidas"] += 1
    return totais


@transaction.atomic
def gerar_mensalidades(*, unidade, competencia):
    """Emite apenas para contratos iniciados no mês, nunca por mero cruzamento de meses."""
    competencia = primeiro_dia(competencia)
    if competencia > date(timezone.localdate().year, timezone.localdate().month, 1):
        raise ValidationError({"competencia": "Não gere cobranças para meses futuros."})
    criadas = 0
    matriculas = Matricula.objects.select_for_update().select_related("plano").filter(
        aluno__unidade=unidade, status__in=(Matricula.Status.ATIVA, Matricula.Status.ENCERRADA),
        inicio__gte=competencia, inicio__lte=ultimo_dia(competencia),
    )
    for matricula in matriculas:
        _, criada = emitir_cobranca_contratual(matricula)
        criadas += int(criada)
    return criadas


def resumo_faturamento(*, unidade, competencia):
    competencia = primeiro_dia(competencia)
    hoje = timezone.localdate()
    fim = ultimo_dia(competencia)
    cobrancas = Pagamento.objects.filter(matricula__aluno__unidade=unidade, competencia=competencia).exclude(status=Pagamento.Status.CANCELADO)
    recebidas = cobrancas.filter(status=Pagamento.Status.PAGO)
    pendentes = cobrancas.filter(status=Pagamento.Status.PENDENTE)
    vencidas = pendentes.filter(vencimento__lt=hoje)
    def soma(queryset):
        return queryset.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    def por_forma(queryset, forma):
        filtro = queryset.filter(forma_pagamento=forma) if forma else queryset.filter(forma_pagamento__isnull=True)
        return soma(filtro)
    # Fluxo de caixa do mês: inclui pagamentos de outras competências recebidos no período.
    caixa = Pagamento.objects.filter(
        matricula__aluno__unidade=unidade, status=Pagamento.Status.PAGO,
        pago_em__date__gte=competencia, pago_em__date__lte=fim,
    )
    return {
        "competencia": competencia,
        "cobrancas": cobrancas.count(),
        "faturamento_previsto": soma(cobrancas),
        "recebido_da_competencia": soma(recebidas),
        "recebido_pix": por_forma(recebidas, Pagamento.Forma.PIX),
        "recebido_cartao": por_forma(recebidas, Pagamento.Forma.CARTAO),
        "recebido_sem_forma": por_forma(recebidas, None),
        "em_aberto": soma(pendentes),
        "vencido_em_aberto": soma(vencidas),
        "recebido_no_mes": soma(caixa),
        "caixa_pix": por_forma(caixa, Pagamento.Forma.PIX),
        "caixa_cartao": por_forma(caixa, Pagamento.Forma.CARTAO),
        "caixa_sem_forma": por_forma(caixa, None),
    }


def faturamento_consolidado(*, unidades, competencia, unidade_selecionada):
    """Consolida as cobranças emitidas e a cobertura das matrículas por unidade autorizada."""
    competencia = primeiro_dia(competencia)
    lista = list(unidades.order_by("nome", "pk").values("id", "nome", "categoria"))
    ids = [unidade["id"] for unidade in lista]
    hoje = timezone.localdate()
    iniciadas = Q(inicio__gte=competencia, inicio__lte=ultimo_dia(competencia)) & ~Q(status=Matricula.Status.CANCELADA)
    matriculas = {
        linha["aluno__unidade_id"]: linha["total"]
        for linha in Matricula.objects.filter(aluno__unidade_id__in=ids).filter(iniciadas)
        .values("aluno__unidade_id").annotate(total=Count("pk"))
    }
    base = Pagamento.objects.filter(
        matricula__aluno__unidade_id__in=ids, competencia=competencia,
    ).exclude(status=Pagamento.Status.CANCELADO)
    cobrancas = {
        linha["matricula__aluno__unidade_id"]: linha
        for linha in base.values("matricula__aluno__unidade_id").annotate(
            quantidade=Count("pk"),
            matriculas_cobradas=Count("matricula_id", distinct=True, filter=Q(
                matricula__inicio__gte=competencia, matricula__inicio__lte=ultimo_dia(competencia),
            ) & ~Q(
                matricula__status=Matricula.Status.CANCELADA,
            )),
            previsto=Sum("valor"),
            recebido=Sum("valor", filter=Q(status=Pagamento.Status.PAGO)),
            pix=Sum("valor", filter=Q(status=Pagamento.Status.PAGO, forma_pagamento=Pagamento.Forma.PIX)),
            cartao=Sum("valor", filter=Q(status=Pagamento.Status.PAGO, forma_pagamento=Pagamento.Forma.CARTAO)),
            sem_forma=Sum("valor", filter=Q(status=Pagamento.Status.PAGO, forma_pagamento__isnull=True)),
            pix_qtd=Count("pk", filter=Q(status=Pagamento.Status.PAGO, forma_pagamento=Pagamento.Forma.PIX)),
            cartao_qtd=Count("pk", filter=Q(status=Pagamento.Status.PAGO, forma_pagamento=Pagamento.Forma.CARTAO)),
            sem_forma_qtd=Count("pk", filter=Q(status=Pagamento.Status.PAGO, forma_pagamento__isnull=True)),
            em_aberto=Sum("valor", filter=Q(status=Pagamento.Status.PENDENTE)),
            vencido=Sum("valor", filter=Q(status=Pagamento.Status.PENDENTE, vencimento__lt=hoje)),
        )
    }
    campos = ("matriculas_iniciadas", "matriculas_sem_cobranca", "cobrancas", "previsto", "recebido", "pix", "cartao", "sem_forma", "pix_qtd", "cartao_qtd", "sem_forma_qtd", "em_aberto", "vencido")
    totais = {chave: Decimal("0.00") if chave in ("previsto", "recebido", "pix", "cartao", "sem_forma", "em_aberto", "vencido") else 0 for chave in campos}
    linhas = []
    for unidade in lista:
        item = cobrancas.get(unidade["id"], {})
        matriculas_iniciadas = matriculas.get(unidade["id"], 0)
        linha = {
            **unidade,
            "matriculas_iniciadas": matriculas_iniciadas,
            "matriculas_sem_cobranca": max(0, matriculas_iniciadas - (item.get("matriculas_cobradas") or 0)),
            "cobrancas": item.get("quantidade") or 0,
            "previsto": item.get("previsto") or Decimal("0.00"),
            "recebido": item.get("recebido") or Decimal("0.00"),
            "pix": item.get("pix") or Decimal("0.00"),
            "cartao": item.get("cartao") or Decimal("0.00"),
            "sem_forma": item.get("sem_forma") or Decimal("0.00"),
            "pix_qtd": item.get("pix_qtd") or 0,
            "cartao_qtd": item.get("cartao_qtd") or 0,
            "sem_forma_qtd": item.get("sem_forma_qtd") or 0,
            "em_aberto": item.get("em_aberto") or Decimal("0.00"),
            "vencido": item.get("vencido") or Decimal("0.00"),
        }
        for chave in campos:
            totais[chave] += linha[chave]
        linhas.append(linha)
    return {"competencia": competencia, "unidade_selecionada": unidade_selecionada,
            "unidades": linhas, "total_rede": totais}
