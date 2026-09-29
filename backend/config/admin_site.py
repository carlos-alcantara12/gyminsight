from django.contrib.admin import AdminSite


class GymInsightAdminSite(AdminSite):
    """Admin reservado ao gerente superusuário com unidade ativa."""

    def has_permission(self, request):
        usuario = request.user
        if not (usuario.is_active and usuario.is_superuser):
            return False
        funcionario = getattr(usuario, "funcionario_academia", None)
        return bool(funcionario and funcionario.ativo and funcionario.cargo == "gerente" and
                    funcionario.unidade.ativa and usuario.groups.filter(name="GymInsight Gerente").exists())
