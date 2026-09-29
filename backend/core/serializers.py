from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from .models import Aluno, Feriado, Frequencia, LogAuditoria, Matricula, Pagamento, Plano, Funcionario, Unidade
from .access import unidade_atual, unidades_permitidas
from .services import cadastrar_aluno_com_matricula, calcular_fim_plano, cancelar_matricula, criar_matricula, registrar_entrada


class ValidatedModelSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        attrs = super().validate(attrs)
        # Valida uma cópia: uma tentativa inválida de PATCH não altera a instância carregada.
        instance = self.Meta.model()
        if self.instance is not None:
            for field in self.instance._meta.concrete_fields:
                setattr(instance, field.attname, getattr(self.instance, field.attname))
        elif self.Meta.model in (Aluno, Plano, Funcionario, Feriado):
            instance.unidade_id = unidade_atual(self.context["request"]).pk
        for key, value in attrs.items():
            if key != "unidades_acesso":
                setattr(instance, key, value)
        try:
            exclude = [field.name for field in instance._meta.fields if field.name not in attrs and self.instance is None and field.name != "unidade"]
            instance.full_clean(exclude=exclude, validate_unique=False, validate_constraints=False)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc
        return attrs


class UnidadeSerializer(ValidatedModelSerializer):
    class Meta:
        model = Unidade
        fields = ["id", "nome", "endereco", "categoria", "ativa", "semana_inicio", "semana_fim",
                  "sabado_inicio", "sabado_fim", "abre_domingo", "domingo_inicio", "domingo_fim",
                  "abre_feriado", "feriado_inicio", "feriado_fim"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        if self.instance is None and "ativa" not in self.initial_data:
            attrs["ativa"] = True
        if self.instance is None and attrs.get("abre_feriado") is False:
            attrs.setdefault("feriado_inicio", None)
            attrs.setdefault("feriado_fim", None)
        return super().validate(attrs)


class FeriadoSerializer(ValidatedModelSerializer):
    class Meta:
        model = Feriado
        fields = ["id", "unidade", "data", "nome", "abre", "inicio", "fim"]
        read_only_fields = ["id", "unidade"]

    def validate(self, attrs):
        dados = super().validate(attrs)
        data = dados.get("data", self.instance.data if self.instance else None)
        if data and Feriado.objects.filter(unidade=unidade_atual(self.context["request"]), data=data).exclude(
            pk=self.instance.pk if self.instance else None
        ).exists():
            raise serializers.ValidationError({"data": "Já existe um feriado registrado nesta data para a unidade."})
        return dados


class LogAuditoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = LogAuditoria
        fields = ["id", "unidade", "usuario", "ocorrido_em", "acao", "entidade", "objeto_id", "campos_alterados"]
        read_only_fields = fields


class CancelamentoSerializer(serializers.Serializer):
    motivo_cancelamento = serializers.CharField(allow_blank=False, trim_whitespace=True)
    decisao = serializers.ChoiceField(choices=("manter", "cancelar"), default="manter")
    justificativa = serializers.CharField(required=False, allow_blank=True, default="")


class ConciliacaoSerializer(serializers.Serializer):
    destino = serializers.ChoiceField(choices=("associado", "avulso", "descartado"))
    justificativa = serializers.CharField(allow_blank=False, trim_whitespace=True)


class PeriodoFrequenciaSerializer(serializers.Serializer):
    inicio = serializers.DateField(required=False)
    fim = serializers.DateField(required=False)

    def validate(self, attrs):
        if attrs.get("inicio") and attrs.get("fim") and attrs["inicio"] > attrs["fim"]:
            raise serializers.ValidationError({"fim": "O fim do período não pode anteceder o início."})
        return attrs


class AlunoSerializer(ValidatedModelSerializer):
    unidade_nome = serializers.CharField(source="unidade.nome", read_only=True)
    plano = serializers.PrimaryKeyRelatedField(queryset=Plano.objects.none(), write_only=True, required=True)
    inicio = serializers.DateField(write_only=True, required=True)
    matricula_ativa_id = serializers.SerializerMethodField()

    class Meta:
        model = Aluno
        fields = ["id", "unidade", "unidade_nome", "nome", "email", "telefone", "data_nascimento", "cadastrado_em", "status", "plano", "inicio", "matricula_ativa_id"]
        read_only_fields = ["id", "unidade", "unidade_nome", "cadastrado_em", "status", "matricula_ativa_id"]

    def get_fields(self):
        fields = super().get_fields()
        if not self.context["request"].user.has_perm("core.ver_contato_aluno"):
            for campo in ("email", "telefone", "data_nascimento"):
                fields.pop(campo, None)
        fields["plano"].queryset = Plano.objects.filter(unidade=unidade_atual(self.context["request"]))
        if self.instance is not None:
            fields["plano"].required = False
            fields["inicio"].required = False
        return fields

    def get_matricula_ativa_id(self, obj):
        return obj.matriculas.filter(status=Matricula.Status.ATIVA).values_list("id", flat=True).first()

    def validate(self, attrs):
        if "status" in self.initial_data:
            raise serializers.ValidationError({"status": "O status é calculado pelas matrículas do aluno."})
        if self.instance is not None and ("plano" in attrs or "inicio" in attrs):
            raise serializers.ValidationError("Para mudar o plano, use o recurso de matrículas.")
        if self.instance is None:
            if "plano" in attrs and not attrs["plano"].ativo:
                raise serializers.ValidationError({"plano": "Não é possível contratar um plano inativo."})
        dados = {key: value for key, value in attrs.items() if key not in ("plano", "inicio")}
        return {**super().validate(dados), **{key: attrs[key] for key in ("plano", "inicio") if key in attrs}}

    def create(self, validated_data):
        plano = validated_data.pop("plano")
        inicio = validated_data.pop("inicio")
        validated_data.pop("status", None)
        try:
            aluno, _ = cadastrar_aluno_com_matricula(
                unidade=unidade_atual(self.context["request"]),
                plano=plano,
                inicio=inicio,
                dados_aluno=validated_data,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc
        return aluno


class PlanoSerializer(ValidatedModelSerializer):
    class Meta:
        model = Plano
        fields = ["id", "unidade", "nome", "categoria", "acesso_tradicional_rede", "duracao_dias", "preco", "ativo"]
        read_only_fields = ["id", "unidade"]

    def validate_nome(self, value):
        unidade = unidade_atual(self.context["request"])
        if Plano.objects.filter(unidade=unidade, nome=value).exclude(pk=self.instance.pk if self.instance else None).exists():
            raise serializers.ValidationError("Já existe um plano com este nome nesta unidade.")
        return value


class FuncionarioSerializer(ValidatedModelSerializer):
    usuario = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.none(), required=False, allow_null=True)
    unidades_acesso = serializers.PrimaryKeyRelatedField(queryset=Unidade.objects.none(), many=True, required=False)

    class Meta:
        model = Funcionario
        fields = ["id", "unidade", "nome", "email", "cargo", "ativo", "usuario", "unidades_acesso"]
        read_only_fields = ["id"]

    def get_fields(self):
        fields = super().get_fields()
        if not self.context["request"].user.has_perm("core.ver_contato_funcionario") or self.context["request"].user.funcionario_academia.cargo != Funcionario.Cargo.GERENTE:
            fields.pop("email", None)
        if self.context["request"].user.funcionario_academia.cargo != Funcionario.Cargo.GERENTE:
            fields.pop("usuario", None)
            fields.pop("unidades_acesso", None)
            fields["unidade"].read_only = True
        else:
            fields["usuario"].queryset = get_user_model().objects.filter(is_active=True)
            fields["unidade"].queryset = unidades_permitidas(self.context["request"].user)
            fields["unidade"].required = False
            fields["unidades_acesso"].queryset = unidades_permitidas(self.context["request"].user)
        return fields

    def validate(self, attrs):
        if self.instance is None and "ativo" not in self.initial_data:
            attrs["ativo"] = True
        dados = super().validate(attrs)
        cargo = dados.get("cargo", self.instance.cargo if self.instance else None)
        usuario = dados.get("usuario", self.instance.usuario if self.instance else None)
        if "unidades_acesso" in dados and cargo != Funcionario.Cargo.GERENTE and dados["unidades_acesso"]:
            raise serializers.ValidationError({"unidades_acesso": "Somente gerentes podem acessar outras unidades."})
        if cargo != Funcionario.Cargo.GERENTE and self.instance and self.instance.unidades_acesso.exists() and "unidades_acesso" not in dados:
            raise serializers.ValidationError({"unidades_acesso": "Remova os acessos adicionais antes de mudar o cargo."})
        if usuario:
            papel = {Funcionario.Cargo.GERENTE: "GymInsight Gerente", Funcionario.Cargo.ATENDENTE: "GymInsight Atendimento"}.get(cargo)
            if not papel or not usuario.groups.filter(name=papel).exists():
                raise serializers.ValidationError({"usuario": "A conta deve pertencer ao grupo do cargo de gerente ou atendente."})
            if Funcionario.objects.filter(usuario=usuario).exclude(pk=self.instance.pk if self.instance else None).exists():
                raise serializers.ValidationError({"usuario": "Esta conta já está vinculada a um funcionário."})
        return dados


class MatriculaSerializer(ValidatedModelSerializer):
    aluno = serializers.PrimaryKeyRelatedField(queryset=Aluno.objects.none())
    plano = serializers.PrimaryKeyRelatedField(queryset=Plano.objects.none())
    aluno_nome = serializers.CharField(source="aluno.nome", read_only=True)
    plano_nome = serializers.CharField(source="plano.nome", read_only=True)
    fim = serializers.DateField(required=False)
    acerto = serializers.SerializerMethodField()
    pagamentos_legados = serializers.SerializerMethodField()

    def get_pagamentos_legados(self, obj):
        if not self.context["request"].user.has_perm("core.change_pagamento"):
            return []
        return [{"id": item.pk, "valor": item.valor, "status": item.status,
                 "vencimento": item.vencimento, "pago_em": item.pago_em}
                for item in obj.pagamentos.filter(competencia__isnull=True,
                                                  conciliacao_legado__isnull=True).exclude(status=Pagamento.Status.CANCELADO)]

    def get_acerto(self, obj):
        acerto = getattr(obj, "acerto_cancelamento", None)
        if not acerto:
            return None
        return {"id": acerto.pk, "decisao": acerto.decisao,
                "valor_reembolso": acerto.valor_reembolso, "reembolsado_em": acerto.reembolsado_em,
                "justificativa": acerto.justificativa}

    class Meta:
        model = Matricula
        fields = ["id", "aluno", "aluno_nome", "plano", "plano_nome", "valor_contratado", "matricula_anterior", "inicio", "fim", "status", "motivo_cancelamento", "acerto", "pagamentos_legados", "criada_em"]
        read_only_fields = ["id", "aluno_nome", "plano_nome", "valor_contratado", "matricula_anterior", "acerto", "pagamentos_legados", "criada_em"]

    def get_fields(self):
        fields = super().get_fields()
        if self.context["request"].method in ("GET", "HEAD", "OPTIONS") and not self.context["request"].user.has_perm("core.ver_contato_aluno"):
            fields.pop("motivo_cancelamento", None)
        unidade = unidade_atual(self.context["request"])
        fields["aluno"].queryset = Aluno.objects.filter(unidade=unidade)
        fields["plano"].queryset = Plano.objects.filter(unidade=unidade)
        return fields

    def validate(self, attrs):
        if self.instance is None and attrs.get("status", Matricula.Status.ATIVA) != Matricula.Status.ATIVA:
            raise serializers.ValidationError({"status": "A matrícula deve começar ativa."})
        if self.instance is not None and "aluno" in attrs and attrs["aluno"].pk != self.instance.aluno_id:
            raise serializers.ValidationError({"aluno": "Não é possível transferir uma matrícula para outro aluno."})
        if self.instance is not None:
            novo_status = attrs.get("status", self.instance.status)
            if "status" in attrs and novo_status != self.instance.status and novo_status != Matricula.Status.CANCELADA:
                raise serializers.ValidationError({"status": "O status é atualizado pelo serviço de vencimento ou cancelamento."})
            if self.instance.status == Matricula.Status.CANCELADA:
                if "status" in attrs and novo_status != Matricula.Status.CANCELADA:
                    raise serializers.ValidationError({"status": "O cancelamento não pode ser desfeito."})
                if "motivo_cancelamento" in attrs and attrs["motivo_cancelamento"] != self.instance.motivo_cancelamento:
                    raise serializers.ValidationError({"motivo_cancelamento": "O motivo registrado não pode ser alterado."})
            elif novo_status == Matricula.Status.ENCERRADA and self.instance.status != novo_status:
                raise serializers.ValidationError({"status": "Use o comando de vencimento para encerrar matrículas."})
            elif novo_status == Matricula.Status.CANCELADA and self.instance.status != Matricula.Status.ATIVA:
                raise serializers.ValidationError({"status": "Somente matrículas ativas podem ser canceladas."})
        if self.instance is not None and any(
            key in attrs and attrs[key] != getattr(self.instance, key) for key in ("plano", "inicio", "fim")
        ):
            raise serializers.ValidationError("Plano e datas são fixados na contratação; crie uma nova matrícula.")
        if self.instance is None and "fim" not in attrs and "inicio" in attrs and "plano" in attrs:
            attrs["fim"] = calcular_fim_plano(plano=attrs["plano"], inicio=attrs["inicio"])
        attrs = super().validate(attrs)
        aluno = attrs.get("aluno", self.instance.aluno if self.instance else None)
        plano = attrs.get("plano", self.instance.plano if self.instance else None)
        status = attrs.get("status", self.instance.status if self.instance else Matricula.Status.ATIVA)
        if self.instance is None and plano and not plano.ativo:
            raise serializers.ValidationError({"plano": "Não é possível contratar um plano inativo."})
        if aluno and status == Matricula.Status.ATIVA and Matricula.objects.filter(aluno=aluno, status="ativa", fim__gte=timezone.localdate()).exclude(pk=self.instance.pk if self.instance else None).exists():
            raise serializers.ValidationError({"status": "O aluno já possui matrícula ativa."})
        return attrs

    def create(self, validated_data):
        try:
            return criar_matricula(**validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc

    def update(self, instance, validated_data):
        if validated_data.get("status") == Matricula.Status.CANCELADA and instance.status != Matricula.Status.CANCELADA:
            try:
                return cancelar_matricula(
                    matricula=instance, motivo=validated_data.get("motivo_cancelamento", instance.motivo_cancelamento),
                    usuario=self.context["request"].user,
                )
            except DjangoValidationError as exc:
                raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc
        return super().update(instance, validated_data)


class FrequenciaSerializer(ValidatedModelSerializer):
    matricula = serializers.PrimaryKeyRelatedField(queryset=Matricula.objects.none())
    aluno_nome = serializers.CharField(source="matricula.aluno.nome", read_only=True)
    unidade_nome = serializers.CharField(source="unidade.nome", read_only=True)

    class Meta:
        model = Frequencia
        fields = ["id", "matricula", "aluno_nome", "unidade", "unidade_nome", "entrada_em", "registrada_por"]
        read_only_fields = ["id", "aluno_nome", "unidade", "unidade_nome", "entrada_em", "registrada_por"]

    def validate(self, attrs):
        if "unidade" in self.initial_data:
            raise serializers.ValidationError({"unidade": "A unidade é determinada pelo atendimento e não pode ser informada."})
        return super().validate(attrs)

    def get_fields(self):
        fields = super().get_fields()
        unidade = unidade_atual(self.context["request"])
        if self.context["request"].method == "POST":
            # A autorização do serviço confere plano, funcionamento e unidade no instante da entrada.
            fields["matricula"].queryset = Matricula.objects.filter(status=Matricula.Status.ATIVA)
        else:
            fields["matricula"].queryset = Matricula.objects.filter(frequencias__unidade=unidade).distinct()
        return fields

    def create(self, validated_data):
        try:
            return registrar_entrada(matricula=validated_data["matricula"], usuario=self.context["request"].user,
                                     unidade=unidade_atual(self.context["request"]))
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc


class PagamentoSerializer(ValidatedModelSerializer):
    matricula = serializers.PrimaryKeyRelatedField(queryset=Matricula.objects.none())
    aluno_nome = serializers.CharField(source="matricula.aluno.nome", read_only=True)
    situacao = serializers.SerializerMethodField()

    def get_situacao(self, obj):
        from django.utils import timezone
        if obj.status == Pagamento.Status.PENDENTE and obj.vencimento < timezone.localdate():
            return "atrasada"
        return obj.status

    def validate(self, attrs):
        novo_status = attrs.get("status", self.instance.status if self.instance else Pagamento.Status.PENDENTE)
        if novo_status == Pagamento.Status.PAGO and (self.instance is None or self.instance.status != Pagamento.Status.PAGO):
            if not attrs.get("forma_pagamento"):
                raise serializers.ValidationError({"forma_pagamento": "Selecione Pix ou cartão ao confirmar o pagamento integral."})
            attrs.setdefault("pago_em", timezone.now())
        attrs = super().validate(attrs)
        if self.instance is not None and any(
            campo in attrs and attrs[campo] != getattr(self.instance, campo)
            for campo in ("matricula", "valor", "vencimento")
        ):
            raise serializers.ValidationError({"pagamento": "Valor, matrícula e vencimento ficam fixos após a cobrança ser emitida."})
        if self.instance is not None and self.instance.status == Pagamento.Status.PAGO and attrs:
            raise serializers.ValidationError({"pagamento": "Pagamento já quitado não pode ser alterado."})
        if self.instance is not None and hasattr(self.instance, "conciliacao_legado"):
            raise serializers.ValidationError({"pagamento": "Pagamento legado já conciliado; preserve seu histórico."})
        if self.instance is not None and "competencia" in attrs and attrs["competencia"] != self.instance.competencia:
            raise serializers.ValidationError({"competencia": "Utilize a conciliação para vincular uma competência antiga."})
        if self.instance is not None and hasattr(self.instance.matricula, "acerto_cancelamento"):
            raise serializers.ValidationError({"pagamento": "Cobrança com acerto de cancelamento não pode ser alterada."})
        if self.instance is not None and "status" in attrs:
            anterior, novo = self.instance.status, attrs["status"]
            if anterior != novo and (anterior != Pagamento.Status.PENDENTE or novo != Pagamento.Status.PAGO):
                raise serializers.ValidationError({"status": "Para cancelar cobrança, utilize o acerto da matrícula."})
        if novo_status != Pagamento.Status.PAGO and attrs.get("forma_pagamento"):
            raise serializers.ValidationError({"forma_pagamento": "Informe a forma somente ao quitar a cobrança."})
        matricula = attrs.get("matricula", self.instance.matricula if self.instance else None)
        competencia = attrs.get("competencia", self.instance.competencia if self.instance else None)
        if self.instance is None and matricula:
            if competencia is None or competencia != matricula.inicio.replace(day=1):
                raise serializers.ValidationError({"competencia": "Informe o mês de início do período contratado."})
            if matricula.pagamentos.exists():
                raise serializers.ValidationError({"matricula": "A matrícula já possui cobrança ou pagamento; concilie antes de registrar outro."})
            if matricula.valor_contratado is None or attrs.get("valor") != matricula.valor_contratado:
                raise serializers.ValidationError({"valor": "Confirme e utilize o valor contratado na matrícula."})
        if matricula and competencia and Pagamento.objects.filter(matricula=matricula, competencia=competencia).exclude(
            pk=self.instance.pk if self.instance else None,
        ).exists():
            raise serializers.ValidationError({"competencia": "Esta matrícula já possui cobrança para esta competência."})
        return attrs

    class Meta:
        model = Pagamento
        fields = ["id", "matricula", "aluno_nome", "competencia", "valor", "vencimento", "pago_em", "forma_pagamento", "confirmado_por", "status", "situacao"]
        read_only_fields = ["id", "aluno_nome", "confirmado_por", "situacao"]

    def create(self, validated_data):
        if validated_data.get("status") == Pagamento.Status.PAGO:
            validated_data["confirmado_por"] = self.context["request"].user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if instance.status == Pagamento.Status.PENDENTE and validated_data.get("status") == Pagamento.Status.PAGO:
            validated_data["confirmado_por"] = self.context["request"].user
        return super().update(instance, validated_data)

    def get_fields(self):
        fields = super().get_fields()
        unidade = unidade_atual(self.context["request"])
        fields["matricula"].queryset = Matricula.objects.filter(aluno__unidade=unidade)
        return fields
