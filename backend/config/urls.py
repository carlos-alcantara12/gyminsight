from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.urls import include, path
from core.models import Funcionario
from core.access import unidade_atual


def painel(request):
    funcionario = getattr(request.user, "funcionario_academia", None)
    papel = {Funcionario.Cargo.GERENTE: "GymInsight Gerente", Funcionario.Cargo.ATENDENTE: "GymInsight Atendimento"}.get(
        funcionario.cargo if funcionario else None
    )
    if not (funcionario and funcionario.ativo and funcionario.unidade.ativa and papel and request.user.groups.filter(name=papel).exists()):
        raise PermissionDenied("Acesso reservado a gerente e atendente ativos de uma unidade ativa.")
    return render(request, "core/dashboard.html", {"unidade_atual": unidade_atual(request)})


urlpatterns = [
    path("", login_required(painel), name="painel"),
    path("contas/", include("django.contrib.auth.urls")),
    path("admin/", admin.site.urls),
    path("api/auth/", include("rest_framework.urls")),
    path("api/", include("core.urls")),
]
