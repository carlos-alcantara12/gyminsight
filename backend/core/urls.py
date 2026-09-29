from rest_framework.routers import DefaultRouter

from .views import AlunoViewSet, FeriadoViewSet, FrequenciaViewSet, FuncionarioViewSet, LogAuditoriaViewSet, MatriculaViewSet, PagamentoViewSet, PlanoViewSet, UnidadeViewSet

router = DefaultRouter()
router.register("unidades", UnidadeViewSet, basename="unidade")
router.register("feriados", FeriadoViewSet, basename="feriado")
router.register("alunos", AlunoViewSet, basename="aluno")
router.register("planos", PlanoViewSet, basename="plano")
router.register("funcionarios", FuncionarioViewSet, basename="funcionario")
router.register("matriculas", MatriculaViewSet, basename="matricula")
router.register("frequencias", FrequenciaViewSet, basename="frequencia")
router.register("pagamentos", PagamentoViewSet, basename="pagamento")
router.register("auditoria", LogAuditoriaViewSet, basename="auditoria")
urlpatterns = router.urls
