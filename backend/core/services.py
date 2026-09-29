"""Operações de matrícula que precisam manter aluno e matrícula consistentes."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Max
from django.db.models.functions import TruncDate
from django.utils import timezone

from .models import AcertoCancelamento, Aluno, Frequencia, Matricula, Pagamento, Plano, Unidade
from .access import unidade_permitida, usuario_tem_permissao
from .audit_context import ator_da_operacao


@transaction.atomic
def sincronizar_status_aluno(*, aluno: Aluno, data_referencia=None) -> str:
    """Deriva o status das matrículas: vigente, última cancelada ou sem vigência."""
    if aluno is None or aluno.pk is None:
        raise ValidationError({"aluno": "Informe um aluno cadastrado."})
    data_referencia = data_referencia or timezone.localdate()
    referencia = aluno
    aluno = Aluno.objects.select_for_update().get(pk=aluno.pk)
    matriculas = Matricula.objects.filter(aluno=aluno)
    if matriculas.filter(
        status=Matricula.Status.ATIVA, inicio__lte=data_referencia, fim__gte=data_referencia,
    ).exists():
        novo_status = Aluno.Status.ATIVO
    else:
        ultima = matriculas.order_by("-criada_em", "-pk").first()
        novo_status = (
            Aluno.Status.CANCELADO if ultima and ultima.status == Matricula.Status.CANCELADA
            else Aluno.Status.INATIVO
        )
    if aluno.status != novo_status:
        aluno.status = novo_status
        aluno.save(update_fields=["status"])
    referencia.status = novo_status
    return novo_status


def sincronizar_status_alunos(*, data_referencia=None) -> int:
    """Atualiza todos os alunos após uma mudança de dia; retorna quantos mudaram."""
    alterados = 0
    for aluno in Aluno.objects.only("id", "status").iterator():
        status_anterior = aluno.status
        if sincronizar_status_aluno(aluno=aluno, data_referencia=data_referencia) != status_anterior:
            alterados += 1
    return alterados


def calcular_fim_plano(*, plano: Plano, inicio):
    """O primeiro dia conta: plano de 30 dias iniciado no dia 1 vence no dia 30."""
    if inicio is None:
        raise ValidationError({"inicio": "Informe a data de início."})
    if plano is None or plano.pk is None:
        raise ValidationError({"plano": "Informe um plano cadastrado."})
    if plano.duracao_dias < 1:
        raise ValidationError({"plano": "A duração do plano deve ser de ao menos um dia."})
    return inicio + timedelta(days=plano.duracao_dias - 1)


@transaction.atomic
def encerrar_matriculas_vencidas(*, data_referencia=None, aluno=None) -> int:
    """Encerra matrículas cujo último dia já passou e inativa alunos sem matrícula ativa."""
    data_referencia = data_referencia or timezone.localdate()
    vencidas = Matricula.objects.select_for_update().filter(status=Matricula.Status.ATIVA, fim__lt=data_referencia)
    if aluno is not None:
        vencidas = vencidas.filter(aluno=aluno)
    matriculas = list(vencidas)
    alunos_ids = {matricula.aluno_id for matricula in matriculas}
    for matricula in matriculas:
        matricula.status = Matricula.Status.ENCERRADA
        matricula.save(update_fields=["status"])
    total = len(matriculas)
    for aluno_id in alunos_ids:
        sincronizar_status_aluno(aluno=Aluno.objects.get(pk=aluno_id), data_referencia=data_referencia)
    return total


@transaction.atomic
def criar_matricula(
    *, aluno: Aluno, plano: Plano, inicio, fim=None,
    status=Matricula.Status.ATIVA, motivo_cancelamento="", matricula_anterior=None,
) -> Matricula:
    """Cria matrícula associada obrigatoriamente a um plano da unidade do aluno."""
    if aluno.pk is None:
        raise ValidationError({"aluno": "O aluno deve estar cadastrado."})
    if plano is None or plano.pk is None:
        raise ValidationError({"plano": "Informe um plano cadastrado."})
    fim_previsto = calcular_fim_plano(plano=plano, inicio=inicio)
    if plano.unidade_id != aluno.unidade_id:
        raise ValidationError({"plano": "O plano deve pertencer à unidade do aluno."})
    if status != Matricula.Status.ATIVA:
        raise ValidationError({"status": "A nova matrícula deve começar ativa; use o serviço de cancelamento."})
    if not plano.ativo:
        raise ValidationError({"plano": "Não é possível contratar um plano inativo."})
    if fim is not None and fim != fim_previsto:
        raise ValidationError({"fim": "O fim deve corresponder à duração do plano."})
    if status == Matricula.Status.ATIVA and fim_previsto < timezone.localdate():
        raise ValidationError({"inicio": "Não é possível criar matrícula ativa já vencida."})
    encerrar_matriculas_vencidas(aluno=aluno)
    if status == Matricula.Status.ATIVA and aluno.matriculas.filter(status=Matricula.Status.ATIVA).exists():
        raise ValidationError({"status": "O aluno já possui matrícula ativa."})

    matricula = Matricula(
        aluno=aluno,
        plano=plano,
        valor_contratado=plano.preco,
        matricula_anterior=matricula_anterior,
        categoria_acesso=plano.categoria,
        acesso_tradicional_rede=plano.acesso_tradicional_rede,
        inicio=inicio,
        fim=fim_previsto,
        status=status,
        motivo_cancelamento=motivo_cancelamento,
    )
    matricula.full_clean()
    matricula.save()
    if inicio <= timezone.localdate():
        from .financeiro import emitir_cobranca_contratual
        emitir_cobranca_contratual(matricula)
    sincronizar_status_aluno(aluno=aluno)
    return matricula


@transaction.atomic
def renovar_matricula(*, matricula: Matricula, usuario, plano=None) -> Matricula:
    """Renova um período encerrado; início e cobrança seguem o fim anterior."""
    if matricula is None or matricula.pk is None:
        raise ValidationError({"matricula": "Informe a matrícula anterior."})
    anterior = Matricula.objects.select_for_update().select_related("aluno", "plano").get(pk=matricula.pk)
    if not usuario_tem_permissao(usuario=usuario, model=Matricula, acao="create", unidade_id=anterior.aluno.unidade_id):
        raise ValidationError({"usuario": "Sem permissão para renovar nesta unidade."})
    if anterior.status == Matricula.Status.CANCELADA:
        raise ValidationError({"matricula": "Matrículas canceladas exigem uma nova contratação."})
    if anterior.fim >= timezone.localdate():
        raise ValidationError({"matricula": f"Este período termina em {anterior.fim:%d/%m/%Y}. Renove após o vencimento."})
    if Matricula.objects.filter(matricula_anterior=anterior).exists():
        raise ValidationError({"matricula": "Este período já foi renovado."})
    novo_plano = plano or anterior.plano
    if novo_plano.unidade_id != anterior.aluno.unidade_id:
        raise ValidationError({"plano": "O plano deve pertencer à unidade sede do aluno."})
    inicio = max(anterior.fim + timedelta(days=1), timezone.localdate())
    return criar_matricula(aluno=anterior.aluno, plano=novo_plano, inicio=inicio,
                           matricula_anterior=anterior)


def pendencia_para_renovacao(aluno):
    """Bloqueia renovação automática por dívidas ou lançamentos históricos incertos."""
    if Pagamento.objects.filter(matricula__aluno=aluno, status=Pagamento.Status.PENDENTE).exists():
        return "Há cobranças pendentes no histórico do aluno."
    if Pagamento.objects.filter(matricula__aluno=aluno, competencia__isnull=True,
                                conciliacao_legado__isnull=True).exclude(status=Pagamento.Status.CANCELADO).exists():
        return "Há pagamentos antigos sem conciliação."
    if Matricula.objects.filter(aluno=aluno, valor_contratado__isnull=True).exclude(status=Matricula.Status.CANCELADA).exists():
        return "Confirme o valor de contratos antigos."
    for contrato in Matricula.objects.filter(aluno=aluno).exclude(status=Matricula.Status.CANCELADA):
        if not contrato.pagamentos.filter(status=Pagamento.Status.PAGO, competencia=contrato.inicio.replace(day=1)).exists():
            return "Há período contratado sem pagamento quitado."
    return None


def renovar_matriculas_automaticamente(*, data_referencia=None):
    """Renova apenas contratos terminados, quitados e ainda sem período seguinte."""
    hoje = timezone.localdate()
    data_referencia = data_referencia or hoje
    if data_referencia > hoje:
        raise ValidationError({"data_referencia": "Não antecipe a renovação para datas futuras."})
    ids = list(Matricula.objects.filter(
        status=Matricula.Status.ENCERRADA, fim__lt=data_referencia, renovacao__isnull=True,
    ).values_list("pk", flat=True))
    resumo = {"renovadas": 0, "pendencias": 0, "inaptas": 0}
    for pk in ids:
        with transaction.atomic():
            anterior = Matricula.objects.select_for_update().select_related("aluno", "plano", "aluno__unidade").get(pk=pk)
            if anterior.status != Matricula.Status.ENCERRADA or anterior.fim >= data_referencia or Matricula.objects.filter(matricula_anterior=anterior).exists():
                continue
            if (not anterior.plano.ativo or not anterior.aluno.unidade.ativa or
                Matricula.objects.filter(aluno=anterior.aluno, status=Matricula.Status.ATIVA).exists() or
                Matricula.objects.filter(aluno=anterior.aluno, fim__gt=anterior.fim).exists() or
                Matricula.objects.filter(aluno=anterior.aluno, criada_em__gt=anterior.criada_em).exists()):
                resumo["inaptas"] += 1
                continue
            if pendencia_para_renovacao(anterior.aluno):
                resumo["pendencias"] += 1
                continue
            criar_matricula(aluno=anterior.aluno, plano=anterior.plano,
                           inicio=max(anterior.fim + timedelta(days=1), data_referencia),
                           matricula_anterior=anterior)
            resumo["renovadas"] += 1
    return resumo


@transaction.atomic
def cadastrar_aluno_com_matricula(*, unidade, plano: Plano, inicio, dados_aluno: dict) -> tuple[Aluno, Matricula]:
    """Cria os dois registros juntos; qualquer falha desfaz o cadastro do aluno."""
    if plano.unidade_id != unidade.pk:
        raise ValidationError({"plano": "O plano deve pertencer à unidade do aluno."})
    if not plano.ativo:
        raise ValidationError({"plano": "Não é possível contratar um plano inativo."})
    if not unidade.ativa:
        raise ValidationError({"unidade": "A unidade está inativa."})

    aluno = Aluno(unidade=unidade, status=Aluno.Status.INATIVO, **dados_aluno)
    aluno.full_clean()
    aluno.save()

    matricula = criar_matricula(aluno=aluno, plano=plano, inicio=inicio)
    return aluno, matricula


@transaction.atomic
def excluir_matricula(matricula: Matricula) -> None:
    """Mantém ao menos uma matrícula no histórico de cada aluno."""
    aluno = Aluno.objects.select_for_update().get(pk=matricula.aluno_id)
    if not aluno.matriculas.exclude(pk=matricula.pk).exists():
        raise ValidationError({"matricula": "Não é possível excluir a única matrícula do aluno."})
    matricula.delete()
    sincronizar_status_aluno(aluno=aluno)


@transaction.atomic
def cancelar_matricula(*, matricula: Matricula, motivo: str, usuario,
                       decisao="manter", justificativa="") -> Matricula:
    """Exige motivo, preserva o histórico e atualiza o aluno na mesma transação."""
    if matricula is None or matricula.pk is None:
        raise ValidationError({"matricula": "Informe uma matrícula cadastrada."})
    try:
        matricula = Matricula.objects.select_for_update().select_related("aluno__unidade").get(pk=matricula.pk)
    except Matricula.DoesNotExist as exc:
        raise ValidationError({"matricula": "Matrícula não encontrada."}) from exc
    if not usuario_tem_permissao(
        usuario=usuario, model=Matricula, acao="cancelar", unidade_id=matricula.aluno.unidade_id,
    ):
        raise ValidationError({"usuario": "O usuário não tem permissão para cancelar esta matrícula."})
    motivo = motivo.strip() if isinstance(motivo, str) else ""
    if not motivo:
        raise ValidationError({"motivo_cancelamento": "Informe o motivo do cancelamento."})

    if matricula.status != Matricula.Status.ATIVA:
        raise ValidationError({"status": "Somente matrículas ativas podem ser canceladas."})
    if decisao not in (AcertoCancelamento.Decisao.MANTER, AcertoCancelamento.Decisao.CANCELAR):
        raise ValidationError({"decisao": "Escolha manter ou cancelar a cobrança."})
    cobrancas = list(Pagamento.objects.select_for_update().filter(matricula=matricula))
    pagamento = next((item for item in cobrancas if item.status != Pagamento.Status.CANCELADO), None)
    if decisao != AcertoCancelamento.Decisao.MANTER:
        if not usuario_tem_permissao(usuario=usuario, model=Pagamento, acao="update",
                                     unidade_id=matricula.aluno.unidade_id):
            raise ValidationError({"decisao": "Somente o gerente pode fazer ajustes financeiros."})
        if not justificativa or not justificativa.strip():
            raise ValidationError({"justificativa": "Justifique o ajuste financeiro."})
        if len(cobrancas) != 1 or pagamento is None:
            raise ValidationError({"decisao": "Concilie os pagamentos anteriores antes de fazer este ajuste."})
        if pagamento.status != Pagamento.Status.PENDENTE:
            raise ValidationError({"decisao": "A cobrança não está na situação necessária para este ajuste."})
    with ator_da_operacao(usuario):
        if decisao == AcertoCancelamento.Decisao.CANCELAR:
            pagamento.status = Pagamento.Status.CANCELADO
            pagamento.save(update_fields=["status"])
        acerto = AcertoCancelamento(
            matricula=matricula, pagamento=pagamento, decisao=decisao,
            valor_reembolso=0,
            justificativa=justificativa.strip() if justificativa else motivo, decidido_por=usuario,
        )
        acerto.full_clean()
        acerto.save()
        matricula.status = Matricula.Status.CANCELADA
        matricula.motivo_cancelamento = motivo
        matricula.full_clean()
        matricula.save(update_fields=["status", "motivo_cancelamento"])
        sincronizar_status_aluno(aluno=matricula.aluno)
    return matricula


def plano_permita_unidade(matricula, unidade, data):
    """Regras contratadas: sede sempre; Premium até Premium; Diamante toda a rede."""
    if unidade.pk == matricula.aluno.unidade_id:
        return True
    if data.weekday() == 6 or unidade.feriados.filter(data=data).exists():
        return matricula.categoria_acesso == Unidade.Categoria.DIAMANTE
    if matricula.categoria_acesso == Unidade.Categoria.DIAMANTE:
        return True
    if matricula.categoria_acesso == Unidade.Categoria.PREMIUM:
        return unidade.categoria in (Unidade.Categoria.TRADICIONAL, Unidade.Categoria.PREMIUM)
    return matricula.acesso_tradicional_rede and unidade.categoria == Unidade.Categoria.TRADICIONAL


@transaction.atomic
def registrar_entrada(*, matricula: Matricula, usuario, instante=None, unidade=None) -> Frequencia:
    """Uma chamada aceita cria exatamente um registro de entrada auditável."""
    if matricula is None or matricula.pk is None:
        raise ValidationError({"matricula": "Informe uma matrícula cadastrada."})
    try:
        matricula = Matricula.objects.select_for_update().select_related("aluno__unidade").get(pk=matricula.pk)
    except Matricula.DoesNotExist as exc:
        raise ValidationError({"matricula": "Matrícula não encontrada."}) from exc
    if not usuario or not usuario.is_authenticated or not hasattr(usuario, "funcionario_academia"):
        raise ValidationError({"usuario": "O registro exige um usuário vinculado a uma unidade."})
    unidade = unidade or usuario.funcionario_academia.unidade
    if not usuario_tem_permissao(usuario=usuario, model=Frequencia, acao="create", unidade_id=unidade.pk):
        raise ValidationError({"usuario": "O usuário não tem permissão para registrar entradas."})
    if not unidade_permitida(usuario, unidade.pk):
        raise ValidationError({"unidade": "O usuário não pode registrar entradas nesta unidade."})
    if not unidade.ativa:
        raise ValidationError({"unidade": "A unidade está inativa."})
    if matricula.status != Matricula.Status.ATIVA:
        raise ValidationError({"matricula": "A matrícula não está ativa."})
    instante = instante if instante is not None else timezone.now()
    if timezone.is_naive(instante):
        raise ValidationError({"entrada_em": "Informe uma data e hora com fuso horário."})
    if instante > timezone.now():
        raise ValidationError({"entrada_em": "Não é possível registrar entrada futura."})
    data_local = timezone.localtime(instante).date()
    if not matricula.inicio <= data_local <= matricula.fim:
        raise ValidationError({"matricula": "A matrícula não está dentro da validade."})
    if not plano_permita_unidade(matricula, unidade, data_local):
        raise ValidationError({"unidade": "O plano contratado não permite entrada nesta unidade e data."})
    funcionamento = unidade.funcionamento_em(data_local)
    if not funcionamento["abre"]:
        raise ValidationError({"unidade": "A unidade está fechada nesta data."})
    horario_local = timezone.localtime(instante).time()
    if funcionamento["inicio"] is not None and not funcionamento["inicio"] <= horario_local < funcionamento["fim"]:
        raise ValidationError({"entrada_em": "A unidade está fora do horário de funcionamento."})

    with ator_da_operacao(usuario):
        registro = Frequencia(matricula=matricula, unidade=unidade, entrada_em=instante, registrada_por=usuario)
        registro.full_clean()
        registro.save()
    return registro


def calcular_frequencia(*, aluno: Aluno, inicio=None, fim=None) -> dict:
    """Calcula presenças a partir das entradas salvas, inclusive matrículas antigas."""
    if aluno is None or aluno.pk is None:
        raise ValidationError({"aluno": "Informe um aluno cadastrado."})
    if inicio is not None and fim is not None and inicio > fim:
        raise ValidationError({"fim": "O fim do período não pode anteceder o início."})

    registros = Frequencia.objects.filter(matricula__aluno=aluno)
    if inicio is not None:
        registros = registros.filter(entrada_em__date__gte=inicio)
    if fim is not None:
        registros = registros.filter(entrada_em__date__lte=fim)
    resumo = registros.aggregate(total_entradas=Count("id"), ultima_entrada=Max("entrada_em"))
    por_dia = list(
        registros.annotate(data=TruncDate("entrada_em", tzinfo=timezone.get_current_timezone()))
        .values("data")
        .annotate(entradas=Count("id"))
        .order_by("data")
    )
    return {
        "aluno": aluno.pk,
        "periodo": {"inicio": inicio, "fim": fim},
        "total_entradas": resumo["total_entradas"],
        "dias_com_presenca": len(por_dia),
        "ultima_entrada": resumo["ultima_entrada"],
        "por_dia": por_dia,
    }
