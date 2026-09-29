"""Autorização por usuário, unidade e permissão nativa do Django."""

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from .models import Aluno, Feriado, Frequencia, LogAuditoria, Matricula, Pagamento, Plano, Funcionario, Unidade


ACOES = {"list": "view", "retrieve": "view", "metadata": "view", "create": "add", "update": "change", "partial_update": "change", "destroy": "delete", "frequencia": "view", "elegiveis": "view", "relatorio_frequencia": "view", "matriculados": "view", "avisos_vencimento": "view", "pendencias_legadas": "view", "conciliar": "change", "gerar_mensalidades": "add", "faturamento": "view", "consolidado": "view", "renovar": "add", "confirmar_valor": "change", "cancelar": "cancelar", "dados_pessoais": "exportar_dados", "funcionamento": "view", "selecionar": "view", "selecionada": "view", "resumo": "view"}
DEPENDENCIAS = {
    (Aluno, "create"): ((Matricula, "add"), (Plano, "view")),
    (Aluno, "frequencia"): ((Frequencia, "view"),),
    (Aluno, "relatorio_frequencia"): ((Frequencia, "view"),),
    (Aluno, "dados_pessoais"): ((Pagamento, "view"),),
    (Matricula, "create"): ((Aluno, "view"), (Plano, "view")),
    (Frequencia, "create"): ((Matricula, "view"), (Frequencia, "registrar")),
    (Matricula, "cancelar"): ((Matricula, "change"),),
    (Matricula, "renovar"): ((Aluno, "view"), (Plano, "view")),
    (Matricula, "confirmar_valor"): ((Pagamento, "change"),),
    (Matricula, "pendencias_legadas"): ((Pagamento, "change"),),
    (Pagamento, "create"): ((Matricula, "view"),),
}


def usuario_tem_permissao(*, usuario, model, acao, unidade_id=None) -> bool:
    """Só autoriza usuários ativos, vinculados a unidade ativa e com permissão adequada."""
    if not usuario or not usuario.is_authenticated or not usuario.is_active:
        return False
    funcionario = getattr(usuario, "funcionario_academia", None)
    if funcionario is None or not funcionario.ativo or not funcionario.unidade.ativa:
        return False
    papel = "GymInsight Gerente" if funcionario.cargo == Funcionario.Cargo.GERENTE else (
        "GymInsight Atendimento" if funcionario.cargo == Funcionario.Cargo.ATENDENTE else None
    )
    if not papel or not usuario.groups.filter(name=papel).exists():
        return False
    if unidade_id is not None and not unidade_permitida(usuario, unidade_id):
        return False
    verbo = ACOES.get(acao)
    if verbo is None:
        return False  # Novas ações da API ficam fechadas até serem mapeadas.
    necessarias = ((model, verbo), *DEPENDENCIAS.get((model, acao), ()))
    if not all(permissao in GRUPOS_PADRAO[papel].get(recurso, ()) for recurso, permissao in necessarias):
        return False
    return all(
        usuario.has_perm(f"{recurso._meta.app_label}.{permissao}_{recurso._meta.model_name}")
        for recurso, permissao in necessarias
    )


def unidade_permitida(usuario, unidade_id):
    funcionario = getattr(usuario, "funcionario_academia", None)
    if funcionario is None:
        return False
    return funcionario.unidade_id == unidade_id or (
        funcionario.cargo == Funcionario.Cargo.GERENTE and funcionario.unidades_acesso.filter(pk=unidade_id).exists()
    )


def unidades_permitidas(usuario):
    funcionario = usuario.funcionario_academia
    if funcionario.cargo == Funcionario.Cargo.GERENTE:
        return Unidade.objects.filter(pk__in=[funcionario.unidade_id, *funcionario.unidades_acesso.values_list("pk", flat=True)])
    return Unidade.objects.filter(pk=funcionario.unidade_id)


def unidade_atual(request):
    """Unidade ativa da sessão; atendente fica sempre na unidade de lotação."""
    funcionario = request.user.funcionario_academia
    selecionada = request.session.get("unidade_atual_id") if funcionario.cargo == Funcionario.Cargo.GERENTE else None
    if selecionada and unidade_permitida(request.user, selecionada):
        unidade = Unidade.objects.filter(pk=selecionada, ativa=True).first()
        if unidade:
            return unidade
    return funcionario.unidade


GRUPOS_PADRAO = {
    "GymInsight Gerente": {
        Unidade: ("view", "add", "change"),
        Feriado: ("view", "add", "change", "delete"),
        Aluno: ("view", "add", "change", "ver_contato", "exportar_dados"),
        Plano: ("view", "add", "change", "delete"),
        Funcionario: ("view", "add", "change", "ver_contato"),
        Matricula: ("view", "add", "change", "delete", "cancelar"),
        Frequencia: ("view", "add", "registrar"),
        Pagamento: ("view", "add", "change", "delete"),
        LogAuditoria: ("view",),
    },
    "GymInsight Atendimento": {
        Unidade: ("view",),
        Feriado: ("view",),
        Aluno: ("view", "add", "change", "ver_contato"),
        Plano: ("view",),
        Funcionario: ("view",),
        Matricula: ("view", "add", "change", "cancelar"),
        Frequencia: ("view", "add", "registrar"),
    },
}


@transaction.atomic
def configurar_grupos_padrao() -> None:
    """Mantém somente os papéis operacionais de gerente e atendimento."""
    antigo = Group.objects.filter(name="GymInsight Gestor").first()
    gerente = Group.objects.filter(name="GymInsight Gerente").first()
    if antigo and not gerente:
        antigo.name = "GymInsight Gerente"
        antigo.save(update_fields=["name"])
    elif antigo:
        gerente.user_set.add(*antigo.user_set.all())
        antigo.delete()
    Group.objects.filter(name__in=["GymInsight Consulta", "GymInsight Avaliador"]).delete()
    for nome, permissoes_por_modelo in GRUPOS_PADRAO.items():
        grupo, _ = Group.objects.get_or_create(name=nome)
        permissoes = []
        for model, verbos in permissoes_por_modelo.items():
            tipo = ContentType.objects.get_for_model(model)
            for verbo in verbos:
                permissoes.append(Permission.objects.get(
                    content_type=tipo, codename=f"{verbo}_{model._meta.model_name}",
                ))
        grupo.permissions.set(permissoes)
