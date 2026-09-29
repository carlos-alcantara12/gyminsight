from django.contrib import admin
from django import forms
from django.utils import timezone

from .models import AcertoCancelamento, Aluno, ConciliacaoLegado, ConfiguracaoRede, Feriado, Frequencia, LogAuditoria, Matricula, Pagamento, Funcionario, Plano, Unidade
from .services import sincronizar_status_aluno


class MatriculaInline(admin.TabularInline):
    model = Matricula
    extra = 1
    min_num = 1
    validate_min = True
    autocomplete_fields = ("plano",)
    readonly_fields = ("status", "motivo_cancelamento")


@admin.register(Aluno)
class AlunoAdmin(admin.ModelAdmin):
    list_display = ("nome", "unidade", "status", "cadastrado_em")
    list_filter = ("unidade", "status")
    search_fields = ("nome", "email")
    inlines = (MatriculaInline,)
    readonly_fields = ("status",)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        sincronizar_status_aluno(aluno=form.instance)


@admin.register(Matricula)
class MatriculaAdmin(admin.ModelAdmin):
    list_display = ("aluno", "plano", "inicio", "fim", "status")
    list_filter = ("status", "plano__unidade")
    autocomplete_fields = ("aluno", "plano")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        sincronizar_status_aluno(aluno=obj.aluno)

    def get_readonly_fields(self, request, obj=None):
        return ("aluno", "plano", "inicio", "fim", "status", "motivo_cancelamento") if obj else ("status", "motivo_cancelamento")

    def has_delete_permission(self, request, obj=None):
        # Exclusões da última matrícula passam exclusivamente pelo serviço/API.
        return False


@admin.register(Plano)
class PlanoAdmin(admin.ModelAdmin):
    list_display = ("nome", "unidade", "categoria", "duracao_dias", "preco", "ativo")
    search_fields = ("nome",)

    def has_delete_permission(self, request, obj=None):
        if ConfiguracaoRede.habilitada() and (obj is None or obj.nome in ("Tradicional", "Premium", "Diamante")):
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Frequencia)
class FrequenciaAdmin(admin.ModelAdmin):
    list_display = ("matricula", "unidade", "entrada_em")
    readonly_fields = ("matricula", "unidade", "entrada_em", "registrada_por")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PagamentoAdminForm(forms.ModelForm):
    class Meta:
        model = Pagamento
        fields = "__all__"

    def clean(self):
        dados = super().clean()
        anterior = Pagamento.objects.filter(pk=self.instance.pk).first() if self.instance.pk else None
        if dados.get("status") == Pagamento.Status.PAGO and (anterior is None or anterior.status != Pagamento.Status.PAGO):
            if not dados.get("forma_pagamento"):
                self.add_error("forma_pagamento", "Escolha Pix ou cartão ao registrar a quitação.")
            dados["pago_em"] = dados.get("pago_em") or timezone.now()
        return dados


@admin.register(Pagamento)
class PagamentoAdmin(admin.ModelAdmin):
    form = PagamentoAdminForm
    list_display = ("matricula", "valor", "vencimento", "status", "forma_pagamento", "confirmado_por")
    readonly_fields = ("confirmado_por",)

    def has_add_permission(self, request):
        return False

    def get_readonly_fields(self, request, obj=None):
        campos = super().get_readonly_fields(request, obj)
        if obj:
            campos = (*campos, "matricula", "competencia", "valor", "vencimento")
            if obj.status == Pagamento.Status.PAGO:
                campos = (*campos, "status", "forma_pagamento", "pago_em")
        return campos

    def save_model(self, request, obj, form, change):
        anterior = Pagamento.objects.filter(pk=obj.pk).first() if change else None
        if obj.status == Pagamento.Status.PAGO and (anterior is None or anterior.status != Pagamento.Status.PAGO):
            obj.confirmado_por = request.user
        super().save_model(request, obj, form, change)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and not (obj and (hasattr(obj.matricula, "acerto_cancelamento") or hasattr(obj, "conciliacao_legado")))

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AcertoCancelamento)
class AcertoCancelamentoAdmin(admin.ModelAdmin):
    list_display = ("matricula", "decisao", "valor_reembolso", "decidido_em", "reembolsado_em")
    readonly_fields = ("matricula", "pagamento", "decisao", "valor_reembolso", "justificativa",
                       "decidido_por", "decidido_em", "reembolsado_em", "reembolsado_por")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ConciliacaoLegado)
class ConciliacaoLegadoAdmin(admin.ModelAdmin):
    list_display = ("pagamento", "destino", "responsavel", "registrado_em")
    readonly_fields = ("pagamento", "destino", "justificativa", "responsavel", "registrado_em")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Unidade)
class UnidadeAdmin(admin.ModelAdmin):
    list_display = ("nome", "categoria", "ativa", "abre_domingo", "abre_feriado")


@admin.register(Feriado)
class FeriadoAdmin(admin.ModelAdmin):
    list_display = ("nome", "data", "unidade", "abre")
    list_filter = ("unidade", "data")


@admin.register(Funcionario)
class FuncionarioAdmin(admin.ModelAdmin):
    list_display = ("nome", "cargo", "unidade", "ativo", "usuario")
    list_filter = ("cargo", "unidade", "ativo")
    search_fields = ("nome", "email")
    filter_horizontal = ("unidades_acesso",)


@admin.register(LogAuditoria)
class LogAuditoriaAdmin(admin.ModelAdmin):
    list_display = ("ocorrido_em", "usuario", "unidade", "acao", "entidade", "objeto_id")
    list_filter = ("unidade", "acao", "entidade")
    readonly_fields = ("unidade", "usuario", "ocorrido_em", "acao", "entidade", "objeto_id", "campos_alterados")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
