from rest_framework import mixins, permissions, viewsets
from django.core.exceptions import ValidationError as DjangoValidationError
from datetime import timedelta
from django.db import transaction
from django.db.models import Count, Max, Exists, OuterRef, Case, When, Value, CharField, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError as ApiValidationError
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import serializers

from .models import AcertoCancelamento, Aluno, ConfiguracaoRede, Feriado, Frequencia, LogAuditoria, Matricula, Pagamento, Plano, Funcionario, Unidade
from .access import unidade_atual, unidade_permitida, unidades_permitidas, usuario_tem_permissao
from .audit_context import definir_ator
from .serializers import (
    AlunoSerializer, CancelamentoSerializer, ConciliacaoSerializer, FrequenciaSerializer, LogAuditoriaSerializer, MatriculaSerializer, PagamentoSerializer,
    PeriodoFrequenciaSerializer, PlanoSerializer, FuncionarioSerializer, FeriadoSerializer, UnidadeSerializer,
)
from .services import calcular_frequencia, cancelar_matricula, excluir_matricula, pendencia_para_renovacao, renovar_matricula
from .financeiro import gerar_mensalidades, resumo_faturamento, faturamento_consolidado
from .conciliacao import conciliar_pagamento


class TemUnidade(permissions.BasePermission):
    def has_permission(self, request, view):
        definir_ator(request.user)
        if not usuario_tem_permissao(usuario=request.user, model=view.queryset.model, acao=view.action):
            return False
        return view.queryset.model == Unidade or unidade_permitida(request.user, unidade_atual(request).pk)


class UnidadeViewSet(viewsets.ModelViewSet):
    queryset = Unidade.objects.all()
    serializer_class = UnidadeSerializer
    permission_classes = [TemUnidade]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def get_queryset(self):
        return unidades_permitidas(self.request.user).order_by("pk")

    def perform_create(self, serializer):
        unidade = serializer.save()
        self.request.user.funcionario_academia.unidades_acesso.add(unidade)

    def perform_update(self, serializer):
        if serializer.instance.pk == self.request.user.funcionario_academia.unidade_id and serializer.validated_data.get("ativa") is False:
            raise ApiValidationError({"ativa": "Transfira a lotação do gerente antes de inativar esta unidade."})
        serializer.save()

    @action(detail=True, methods=["get"])
    def funcionamento(self, request, pk=None):
        unidade = self.get_object()
        data = serializers.DateField().run_validation(request.query_params.get("data", timezone.localdate().isoformat()))
        return Response({"unidade": unidade.pk, "data": data, **unidade.funcionamento_em(data)})

    @action(detail=True, methods=["post"])
    def selecionar(self, request, pk=None):
        unidade = self.get_object()
        if not unidade.ativa:
            raise ApiValidationError({"unidade": "Selecione uma unidade ativa."})
        request.session["unidade_atual_id"] = unidade.pk
        return Response({"unidade": unidade.pk, "nome": unidade.nome})

    @action(detail=False, methods=["get"])
    def selecionada(self, request):
        unidade = unidade_atual(request)
        return Response({"unidade": unidade.pk, "nome": unidade.nome})

    @action(detail=False, methods=["get"])
    def resumo(self, request):
        hoje = timezone.localdate()
        resultado = []
        for unidade in self.get_queryset():
            resultado.append({
                "id": unidade.pk, "nome": unidade.nome, "categoria": unidade.categoria,
                "ativa": unidade.ativa, "funcionamento_hoje": unidade.funcionamento_em(hoje),
                "alunos": Aluno.objects.filter(unidade=unidade).count(),
                "matriculas_ativas": Matricula.objects.filter(aluno__unidade=unidade, status=Matricula.Status.ATIVA,
                                                              inicio__lte=hoje, fim__gte=hoje).count(),
                "funcionarios_ativos": Funcionario.objects.filter(unidade=unidade, ativo=True).count(),
            })
        return Response({"data": hoje, "unidades": resultado})


class FeriadoViewSet(viewsets.ModelViewSet):
    queryset = Feriado.objects.all()
    serializer_class = FeriadoSerializer
    permission_classes = [TemUnidade]

    def get_queryset(self):
        return self.queryset.filter(unidade=unidade_atual(self.request)).order_by("data", "pk")

    def perform_create(self, serializer):
        serializer.save(unidade=unidade_atual(self.request))


class UnidadeScopedViewSet(viewsets.ModelViewSet):
    permission_classes = [TemUnidade]
    unidade_lookup = "unidade_id"

    def get_queryset(self):
        return self.queryset.filter(**{self.unidade_lookup: unidade_atual(self.request).pk}).order_by("pk")

    def perform_create(self, serializer):
        serializer.save(unidade=unidade_atual(self.request))


class AlunoViewSet(UnidadeScopedViewSet):
    queryset = Aluno.objects.all()
    serializer_class = AlunoSerializer

    def perform_create(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        raise ApiValidationError({"aluno": "Para preservar o histórico, o cadastro do aluno não pode ser excluído pela API."})

    @action(detail=True, methods=["get"])
    def frequencia(self, request, pk=None):
        aluno = self.get_object()
        periodo = PeriodoFrequenciaSerializer(data=request.query_params)
        periodo.is_valid(raise_exception=True)
        return Response(calcular_frequencia(aluno=aluno, **periodo.validated_data))

    @action(detail=False, methods=["get"], url_path="relatorio-frequencia")
    def relatorio_frequencia(self, request):
        """Relatório da unidade, com alunos sem presença e métricas de todas as páginas."""
        periodo = PeriodoFrequenciaSerializer(data=request.query_params)
        periodo.is_valid(raise_exception=True)
        inicio = periodo.validated_data.get("inicio")
        fim = periodo.validated_data.get("fim")
        alunos = self.get_queryset()
        page = self.paginate_queryset(alunos)
        alunos_da_pagina = list(page if page is not None else alunos)
        entradas = Frequencia.objects.filter(matricula__aluno__unidade_id=unidade_atual(request).pk)
        if inicio is not None:
            entradas = entradas.filter(entrada_em__date__gte=inicio)
        if fim is not None:
            entradas = entradas.filter(entrada_em__date__lte=fim)
        resumo = entradas.aggregate(total_entradas=Count("id"), alunos_com_presenca=Count("matricula__aluno_id", distinct=True))
        por_aluno = {
            registro["matricula__aluno_id"]: registro
            for registro in entradas.filter(matricula__aluno_id__in=[aluno.pk for aluno in alunos_da_pagina])
            .order_by().values("matricula__aluno_id")
            .annotate(
                total_entradas=Count("id"),
                dias_com_presenca=Count(TruncDate("entrada_em", tzinfo=timezone.get_current_timezone()), distinct=True),
                ultima_entrada=Max("entrada_em"),
            )
        }
        resultados = []
        for aluno in alunos_da_pagina:
            contagem = por_aluno.get(aluno.pk, {})
            resultados.append({
                "aluno_id": aluno.pk, "nome": aluno.nome, "status": aluno.status,
                "total_entradas": contagem.get("total_entradas", 0),
                "dias_com_presenca": contagem.get("dias_com_presenca", 0),
                "ultima_entrada": contagem.get("ultima_entrada"),
            })
        resposta = self.get_paginated_response(resultados) if page is not None else Response({"results": resultados})
        resposta.data["periodo"] = {"inicio": inicio, "fim": fim}
        resposta.data["resumo"] = {"total_alunos": alunos.count(), **resumo}
        resposta["Cache-Control"] = "no-store"
        return resposta

    @action(detail=True, methods=["get"], url_path="dados-pessoais")
    def dados_pessoais(self, request, pk=None):
        """Extrato para atendimento mediado de pedido de acesso após validar identidade."""
        aluno = self.get_object()
        matriculas = Matricula.objects.filter(aluno=aluno).order_by("pk")
        dados = {
            "aluno": {
                "id": aluno.pk, "nome": aluno.nome, "email": aluno.email,
                "telefone": aluno.telefone, "data_nascimento": aluno.data_nascimento,
                "cadastrado_em": aluno.cadastrado_em, "status": aluno.status,
            },
            "matriculas": list(matriculas.values(
                "id", "plano_id", "inicio", "fim", "status", "motivo_cancelamento", "criada_em",
            )),
            "entradas": list(Frequencia.objects.filter(matricula__aluno=aluno).order_by("pk").values(
                "id", "matricula_id", "entrada_em",
            )),
            "pagamentos": list(Pagamento.objects.filter(matricula__aluno=aluno).order_by("pk").values(
                "id", "matricula_id", "valor", "vencimento", "pago_em", "status",
            )),
        }
        LogAuditoria.objects.create(
            unidade_id=aluno.unidade_id, usuario=request.user,
            acao="exportado", entidade="aluno", objeto_id=str(aluno.pk), campos_alterados=[],
        )
        resposta = Response(dados)
        resposta["Cache-Control"] = "no-store"
        resposta["Pragma"] = "no-cache"
        return resposta


class PlanoViewSet(UnidadeScopedViewSet):
    queryset = Plano.objects.all()
    serializer_class = PlanoSerializer

    def _verificar_gestao_rede(self):
        if ConfiguracaoRede.habilitada() and Unidade.objects.filter(ativa=True).exclude(
            pk__in=unidades_permitidas(self.request.user).values("pk")
        ).exists():
            raise PermissionDenied("Alterar o catálogo compartilhado exige acesso a todas as unidades ativas.")

    def perform_create(self, serializer):
        self._verificar_gestao_rede()
        super().perform_create(serializer)

    def perform_update(self, serializer):
        if serializer.instance.nome in ("Tradicional", "Premium", "Diamante"):
            self._verificar_gestao_rede()
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        if ConfiguracaoRede.habilitada() and instance.nome in ("Tradicional", "Premium", "Diamante"):
            raise ApiValidationError({"plano": "Desative o plano da rede em vez de excluí-lo."})
        super().perform_destroy(instance)


class FuncionarioViewSet(UnidadeScopedViewSet):
    queryset = Funcionario.objects.all()
    serializer_class = FuncionarioSerializer
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def perform_create(self, serializer):
        serializer.save(unidade=serializer.validated_data.get("unidade", unidade_atual(self.request)))


class RelacaoScopedViewSet(UnidadeScopedViewSet):
    unidade_lookup = "matricula__aluno__unidade_id"

    def perform_create(self, serializer):
        serializer.save()


class MatriculaViewSet(RelacaoScopedViewSet):
    queryset = Matricula.objects.all()
    serializer_class = MatriculaSerializer
    unidade_lookup = "aluno__unidade_id"

    @action(detail=False, methods=["get"], url_path="avisos-vencimento")
    def avisos_vencimento(self, request):
        hoje = timezone.localdate()
        registros = self.get_queryset().select_related("aluno", "plano").filter(
            status=Matricula.Status.ATIVA, inicio__lte=hoje, fim__gte=hoje,
            fim__lte=hoje + timedelta(days=7),
        ).order_by("fim", "aluno__nome", "pk")
        pagina = self.paginate_queryset(registros)
        dados = [{"id": item.pk, "aluno_nome": item.aluno.nome,
                  "plano_nome": item.plano.nome, "fim": item.fim,
                  "dias_restantes": (item.fim - hoje).days,
                  "renovacao_automatica": not pendencia_para_renovacao(item.aluno) and item.plano.ativo}
                 for item in pagina]
        return self.get_paginated_response(dados)

    @action(detail=False, methods=["get"], url_path="pendencias-legadas")
    def pendencias_legadas(self, request):
        pendente = Pagamento.objects.filter(matricula_id=OuterRef("pk"), competencia__isnull=True,
                                           conciliacao_legado__isnull=True).exclude(status=Pagamento.Status.CANCELADO)
        registros = self.get_queryset().filter(
            status__in=(Matricula.Status.ATIVA, Matricula.Status.ENCERRADA), inicio__lte=timezone.localdate(),
        ).annotate(tem_legado=Exists(pendente)).filter(Q(valor_contratado__isnull=True) | Q(tem_legado=True))
        registros = registros.order_by("aluno__nome", "pk")
        pagina = self.paginate_queryset(registros)
        return self.get_paginated_response(self.get_serializer(pagina, many=True).data)

    @action(detail=True, methods=["post"])
    def renovar(self, request, pk=None):
        anterior = self.get_object()
        plano_id = request.data.get("plano")
        plano = None
        if plano_id is not None:
            plano = Plano.objects.filter(pk=plano_id, unidade=unidade_atual(request)).first()
            if plano is None:
                raise ApiValidationError({"plano": "Selecione um plano da unidade."})
        try:
            nova = renovar_matricula(matricula=anterior, usuario=request.user, plano=plano)
        except DjangoValidationError as exc:
            raise ApiValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc
        return Response(self.get_serializer(nova).data, status=201)

    @action(detail=True, methods=["post"], url_path="confirmar-valor")
    def confirmar_valor(self, request, pk=None):
        valor = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0).run_validation(request.data.get("valor"))
        with transaction.atomic():
            matricula = self.get_queryset().select_for_update().get(pk=self.get_object().pk)
            if matricula.valor_contratado is not None:
                raise ApiValidationError({"valor": "O valor contratado já está confirmado e não pode ser alterado."})
            cobranca_existente = matricula.pagamentos.filter(competencia=matricula.inicio.replace(day=1)).first()
            if cobranca_existente and cobranca_existente.valor != valor:
                raise ApiValidationError({"valor": "O valor informado difere da cobrança existente. Revise o histórico antes de confirmar."})
            matricula.valor_contratado = valor
            matricula.save(update_fields=["valor_contratado"])
        return Response(self.get_serializer(matricula).data)

    @action(detail=False, methods=["get"])
    def matriculados(self, request):
        """Situação da matrícula na unidade selecionada, com base nas cobranças existentes."""
        hoje = timezone.localdate()
        cobrancas = Pagamento.objects.filter(matricula__aluno_id=OuterRef("aluno_id")).exclude(status=Pagamento.Status.CANCELADO)
        pendencias = cobrancas.filter(status=Pagamento.Status.PENDENTE, vencimento__lt=hoje)
        abertas = cobrancas.filter(status=Pagamento.Status.PENDENTE)
        registros = self.get_queryset().select_related("aluno", "plano").annotate(
            possui_cobranca=Exists(cobrancas), possui_atraso=Exists(pendencias), possui_aberta=Exists(abertas),
        ).annotate(situacao_financeira=Case(
            When(status=Matricula.Status.CANCELADA, then=Value("cancelada")),
            When(status=Matricula.Status.ENCERRADA, then=Value("encerrada")),
            When(possui_atraso=True, then=Value("atrasada")),
            When(possui_cobranca=False, then=Value("sem_cobranca")),
            When(possui_aberta=True, then=Value("a_vencer")),
            default=Value("em_dia"), output_field=CharField(),
        ))
        busca = request.query_params.get("busca", "").strip()
        if busca:
            registros = registros.filter(aluno__nome__icontains=busca[:100])
        totais = {item["situacao_financeira"]: item["total"] for item in registros.values("situacao_financeira").annotate(total=Count("pk"))}
        situacao = request.query_params.get("situacao", "")
        permitidas = {"em_dia", "a_vencer", "atrasada", "cancelada", "sem_cobranca", "encerrada"}
        if situacao and situacao not in permitidas:
            raise ApiValidationError({"situacao": "Situação inválida."})
        if situacao:
            registros = registros.filter(situacao_financeira=situacao)
        registros = registros.order_by("aluno__nome", "pk")
        pagina = self.paginate_queryset(registros)
        itens = pagina if pagina is not None else registros
        aluno_ids = [m.aluno_id for m in itens]
        pendencias_por_aluno = {aluno_id: [] for aluno_id in aluno_ids}
        for cobranca in Pagamento.objects.filter(matricula__aluno_id__in=aluno_ids, status=Pagamento.Status.PENDENTE,
                                                vencimento__lt=hoje).order_by("vencimento", "pk"):
            pendencias_por_aluno[cobranca.matricula.aluno_id].append({
                "competencia": cobranca.competencia.strftime("%Y-%m") if cobranca.competencia else None,
                "vencimento": cobranca.vencimento.isoformat(), "valor": str(cobranca.valor),
            })
        dados = [{"id": m.pk, "aluno_nome": m.aluno.nome, "plano_nome": m.plano.nome,
                  "inicio": m.inicio, "fim": m.fim, "status": m.status,
                  "situacao_financeira": m.situacao_financeira,
                  "pendencias": pendencias_por_aluno[m.aluno_id]} for m in itens]
        if pagina is not None:
            resposta = self.get_paginated_response(dados)
            resposta.data["totais"] = {chave: totais.get(chave, 0) for chave in permitidas}
            return resposta
        return Response({"results": dados, "count": len(dados), "totais": {chave: totais.get(chave, 0) for chave in permitidas}})

    def perform_update(self, serializer):
        if serializer.validated_data.get("status") == Matricula.Status.CANCELADA and serializer.instance.status != Matricula.Status.CANCELADA:
            if not usuario_tem_permissao(usuario=self.request.user, model=Matricula, acao="cancelar"):
                raise PermissionDenied("O usuário não tem permissão para cancelar matrículas.")
        serializer.save()

    @action(detail=True, methods=["post"])
    def cancelar(self, request, pk=None):
        matricula = self.get_object()
        dados = CancelamentoSerializer(data=request.data)
        dados.is_valid(raise_exception=True)
        try:
            cancelada = cancelar_matricula(
                matricula=matricula, motivo=dados.validated_data["motivo_cancelamento"], usuario=request.user,
                decisao=dados.validated_data["decisao"], justificativa=dados.validated_data["justificativa"],
            )
        except DjangoValidationError as exc:
            raise ApiValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc
        return Response(self.get_serializer(cancelada).data)

    def perform_destroy(self, instance):
        try:
            excluir_matricula(instance)
        except DjangoValidationError as exc:
            raise ApiValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc


class FrequenciaViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Frequencia.objects.all()
    serializer_class = FrequenciaSerializer
    permission_classes = [TemUnidade]

    def get_queryset(self):
        local = unidade_atual(self.request).pk
        return self.queryset.filter(Q(unidade_id=local) | Q(unidade__isnull=True, matricula__aluno__unidade_id=local)).order_by("pk")

    @action(detail=False, methods=["get"])
    def elegiveis(self, request):
        """Matrículas vigentes potencialmente aceitas no balcão desta unidade."""
        from .services import plano_permita_unidade
        local = unidade_atual(request)
        hoje = timezone.localdate()
        acesso = Q(aluno__unidade_id=local.pk) | Q(categoria_acesso=Unidade.Categoria.DIAMANTE)
        if hoje.weekday() != 6 and not local.feriados.filter(data=hoje).exists():
            if local.categoria == Unidade.Categoria.TRADICIONAL:
                acesso |= Q(categoria_acesso=Unidade.Categoria.PREMIUM)
                acesso |= Q(categoria_acesso=Unidade.Categoria.TRADICIONAL, acesso_tradicional_rede=True)
            elif local.categoria == Unidade.Categoria.PREMIUM:
                acesso |= Q(categoria_acesso=Unidade.Categoria.PREMIUM)
        registros = Matricula.objects.select_related("aluno", "plano").filter(
            status=Matricula.Status.ATIVA, inicio__lte=hoje, fim__gte=hoje,
        ).filter(acesso).order_by("aluno__nome", "pk")
        registros = [matricula for matricula in registros if plano_permita_unidade(matricula, local, hoje)]
        pagina = self.paginate_queryset(registros)
        itens = pagina if pagina is not None else registros
        dados = [{"id": matricula.pk, "aluno_nome": matricula.aluno.nome, "plano_nome": matricula.plano.nome,
                  "unidade_sede": matricula.aluno.unidade_id, "categoria_acesso": matricula.categoria_acesso,
                  "inicio": matricula.inicio, "fim": matricula.fim} for matricula in itens]
        return self.get_paginated_response(dados) if pagina is not None else Response(dados)


class PagamentoViewSet(RelacaoScopedViewSet):
    queryset = Pagamento.objects.all()
    serializer_class = PagamentoSerializer

    def perform_destroy(self, instance):
        raise ApiValidationError({"pagamento": "Preserve o histórico; ajuste pelo cancelamento da matrícula."})

    @action(detail=True, methods=["post"])
    def conciliar(self, request, pk=None):
        pagamento = self.get_object()
        dados = ConciliacaoSerializer(data=request.data)
        dados.is_valid(raise_exception=True)
        try:
            conciliar_pagamento(pagamento=pagamento, usuario=request.user, **dados.validated_data)
        except DjangoValidationError as exc:
            raise ApiValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc
        pagamento.refresh_from_db()
        return Response(self.get_serializer(pagamento).data)

    def get_queryset(self):
        registros = super().get_queryset()
        if self.action == "list" and self.request.query_params.get("competencia"):
            competencia = self._competencia(self.request)
            registros = registros.filter(competencia=competencia)
        return registros

    def _competencia(self, request):
        valor = request.data.get("competencia") if request.method == "POST" else request.query_params.get("competencia")
        if not valor:
            raise ApiValidationError({"competencia": "Informe o mês no formato AAAA-MM."})
        try:
            if len(valor) != 7:
                raise ValueError()
            data = timezone.datetime.strptime(valor, "%Y-%m").date()
            return data.replace(day=1)
        except (ValueError, TypeError):
            raise ApiValidationError({"competencia": "Use o formato AAAA-MM."})

    @action(detail=False, methods=["post"], url_path="gerar-mensalidades")
    def gerar_mensalidades(self, request):
        competencia = self._competencia(request)
        try:
            criadas = gerar_mensalidades(unidade=unidade_atual(request), competencia=competencia)
        except DjangoValidationError as exc:
            raise ApiValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc
        return Response({"competencia": competencia.isoformat()[:7], "cobrancas_criadas": criadas})

    @action(detail=False, methods=["get"])
    def faturamento(self, request):
        competencia = self._competencia(request)
        return Response(resumo_faturamento(unidade=unidade_atual(request), competencia=competencia))

    @action(detail=False, methods=["get"])
    def consolidado(self, request):
        competencia = self._competencia(request)
        return Response(faturamento_consolidado(
            unidades=unidades_permitidas(request.user).filter(ativa=True),
            competencia=competencia,
            unidade_selecionada=unidade_atual(request).pk,
        ))


class LogAuditoriaViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = LogAuditoria.objects.all()
    serializer_class = LogAuditoriaSerializer
    permission_classes = [TemUnidade]

    def get_queryset(self):
        return self.queryset.filter(unidade_id=unidade_atual(self.request).pk)
