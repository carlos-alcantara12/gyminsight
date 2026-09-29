from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from decimal import Decimal
from datetime import time
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Unidade(models.Model):
    class Categoria(models.TextChoices):
        TRADICIONAL = "tradicional", "Tradicional"
        PREMIUM = "premium", "Premium"
        DIAMANTE = "diamante", "Diamante"

    nome = models.CharField(max_length=150)
    endereco = models.CharField(max_length=255, blank=True)
    ativa = models.BooleanField(default=True)
    categoria = models.CharField(max_length=12, choices=Categoria.choices, default=Categoria.TRADICIONAL)
    abre_domingo = models.BooleanField(default=False)
    domingo_inicio = models.TimeField(null=True, blank=True)
    domingo_fim = models.TimeField(null=True, blank=True)
    abre_feriado = models.BooleanField(default=True)
    feriado_inicio = models.TimeField(default=time(8, 0), null=True, blank=True)
    feriado_fim = models.TimeField(default=time(14, 0), null=True, blank=True)
    semana_inicio = models.TimeField(default=time(5, 0))
    semana_fim = models.TimeField(default=time(23, 0))
    sabado_inicio = models.TimeField(default=time(5, 0))
    sabado_fim = models.TimeField(default=time(18, 0))

    def clean(self):
        super().clean()
        erros = {}
        for tipo, abre in (("domingo", self.abre_domingo), ("feriado", self.abre_feriado)):
            inicio, fim = getattr(self, f"{tipo}_inicio"), getattr(self, f"{tipo}_fim")
            if abre and (inicio is None or fim is None or inicio >= fim):
                erros[f"{tipo}_inicio"] = "Informe horários de abertura e fechamento válidos."
            if not abre and (inicio is not None or fim is not None):
                erros[f"{tipo}_inicio"] = "Retire os horários quando a unidade não abre."
        for tipo in ("semana", "sabado"):
            if getattr(self, f"{tipo}_inicio") >= getattr(self, f"{tipo}_fim"):
                erros[f"{tipo}_inicio"] = "A abertura deve anteceder o fechamento."
        if erros:
            raise ValidationError(erros)

    def funcionamento_em(self, data):
        """Exceção cadastrada vence domingo; dias comuns usam o status da unidade."""
        feriado = self.feriados.filter(data=data).first() if self.pk else None
        if not self.ativa:
            return {"abre": False, "tipo": "inativa", "inicio": None, "fim": None}
        if feriado is not None:
            abre = self.abre_feriado if feriado.abre is None else feriado.abre
            inicio = (feriado.inicio or self.feriado_inicio) if abre else None
            fim = (feriado.fim or self.feriado_fim) if abre else None
            return {"abre": abre, "tipo": "feriado", "inicio": inicio,
                    "fim": fim, "nome": feriado.nome}
        if data.weekday() == 6:
            return {"abre": self.abre_domingo, "tipo": "domingo", "inicio": self.domingo_inicio if self.abre_domingo else None,
                    "fim": self.domingo_fim if self.abre_domingo else None}
        tipo = "sabado" if data.weekday() == 5 else "dia_comum"
        faixa = "sabado" if tipo == "sabado" else "semana"
        return {"abre": True, "tipo": tipo, "inicio": getattr(self, f"{faixa}_inicio"),
                "fim": getattr(self, f"{faixa}_fim")}

    def __str__(self):
        return self.nome


class ConfiguracaoRede(models.Model):
    """Ativa o catálogo compartilhado após preparar os dados da rede."""
    ativa = models.BooleanField(default=False)

    @classmethod
    def habilitada(cls):
        return cls.objects.filter(pk=1, ativa=True).exists()


class Funcionario(models.Model):
    """Cadastro da equipe; somente gerente e atendimento podem receber acesso."""

    class Cargo(models.TextChoices):
        GERENTE = "gerente", "Gerente"
        ATENDENTE = "atendente", "Atendente"
        PROFESSOR = "professor", "Professor"
        FAXINEIRO = "faxineiro", "Faxineiro"
        OUTRO = "outro", "Outro"

    unidade = models.ForeignKey(Unidade, on_delete=models.PROTECT, related_name="funcionarios")
    unidades_acesso = models.ManyToManyField(Unidade, blank=True, related_name="gerentes_autorizados")
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="funcionario_academia")
    nome = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    cargo = models.CharField(max_length=12, choices=Cargo.choices)
    ativo = models.BooleanField(default=True)

    class Meta:
        permissions = [("ver_contato_funcionario", "Pode consultar contato do funcionário")]

    def clean(self):
        super().clean()
        if self.usuario_id and self.cargo not in (self.Cargo.GERENTE, self.Cargo.ATENDENTE):
            raise ValidationError({"usuario": "Somente gerente ou atendente pode possuir acesso."})

    def __str__(self):
        return f"{self.nome} — {self.get_cargo_display()}"


class Feriado(models.Model):
    unidade = models.ForeignKey(Unidade, on_delete=models.CASCADE, related_name="feriados")
    data = models.DateField()
    nome = models.CharField(max_length=100)
    abre = models.BooleanField(null=True, blank=True, default=None)
    inicio = models.TimeField(null=True, blank=True)
    fim = models.TimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["unidade", "data"], name="feriado_unico_por_unidade_data")]
        ordering = ["data", "id"]

    def clean(self):
        super().clean()
        if self.abre is not True and (self.inicio is not None or self.fim is not None):
            raise ValidationError({"inicio": "Horários específicos exigem abertura excepcional."})
        if self.abre is True and ((self.inicio is None) != (self.fim is None) or
                                  self.inicio is not None and self.inicio >= self.fim):
            raise ValidationError({"inicio": "Informe ambos os horários válidos ou use o horário padrão de feriado."})
        if self.abre is True and self.inicio is None and self.unidade_id and not self.unidade.abre_feriado:
            raise ValidationError({"inicio": "Informe horários para abrir excepcionalmente nesta data."})

    def __str__(self):
        return f"{self.nome} — {self.unidade} ({self.data})"


class Aluno(models.Model):
    class Status(models.TextChoices):
        ATIVO = "ativo", "Ativo"
        INATIVO = "inativo", "Inativo"
        CANCELADO = "cancelado", "Cancelado"

    unidade = models.ForeignKey(Unidade, on_delete=models.PROTECT, related_name="alunos")
    nome = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    telefone = models.CharField(max_length=25, blank=True)
    data_nascimento = models.DateField(null=True, blank=True)
    cadastrado_em = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.INATIVO)

    class Meta:
        permissions = [
            ("ver_contato_aluno", "Pode consultar dados de contato e nascimento do aluno"),
            ("exportar_dados_aluno", "Pode exportar dados pessoais do aluno"),
        ]

    def __str__(self):
        return self.nome


class Plano(models.Model):
    categoria = models.CharField(max_length=12, choices=Unidade.Categoria.choices, default=Unidade.Categoria.TRADICIONAL)
    acesso_tradicional_rede = models.BooleanField(default=False, help_text="Plano Tradicional também permite outras unidades Tradicionais.")
    unidade = models.ForeignKey(Unidade, on_delete=models.PROTECT, related_name="planos")
    nome = models.CharField(max_length=100)
    duracao_dias = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    preco = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    ativo = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["unidade", "nome"], name="plano_nome_unico_por_unidade")]

    def clean(self):
        super().clean()
        if ConfiguracaoRede.habilitada() and self.ativo and self.nome not in ("Tradicional", "Premium", "Diamante"):
            raise ValidationError({"nome": "Na rede, os planos ativos são Tradicional, Premium e Diamante."})
        if ConfiguracaoRede.habilitada() and self.nome in ("Tradicional", "Premium", "Diamante"):
            if self.categoria != self.nome.lower():
                raise ValidationError({"categoria": "A categoria deve corresponder ao nome do plano."})
        if ConfiguracaoRede.habilitada() and self.pk:
            anterior_nome = Plano.objects.filter(pk=self.pk).values_list("nome", flat=True).first()
            if anterior_nome in ("Tradicional", "Premium", "Diamante") and anterior_nome != self.nome:
                raise ValidationError({"nome": "Não renomeie um plano compartilhado com a rede."})
        if self.acesso_tradicional_rede and self.categoria != Unidade.Categoria.TRADICIONAL:
            raise ValidationError({"acesso_tradicional_rede": "Esta opção pertence apenas ao plano Tradicional."})
        if self.pk and Matricula.objects.filter(plano_id=self.pk).exists():
            anterior = Plano.objects.get(pk=self.pk)
            if anterior.categoria != self.categoria or anterior.acesso_tradicional_rede != self.acesso_tradicional_rede:
                raise ValidationError({"categoria": "Regras de acesso de planos já contratados não podem ser alteradas; crie um novo plano."})

    def __str__(self):
        return f"{self.nome} ({self.unidade})"


class Matricula(models.Model):
    class Status(models.TextChoices):
        ATIVA = "ativa", "Ativa"
        ENCERRADA = "encerrada", "Encerrada"
        CANCELADA = "cancelada", "Cancelada"

    aluno = models.ForeignKey(Aluno, on_delete=models.PROTECT, related_name="matriculas")
    plano = models.ForeignKey(Plano, on_delete=models.PROTECT, related_name="matriculas")
    valor_contratado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                           validators=[MinValueValidator(0)], editable=False)
    matricula_anterior = models.OneToOneField("self", on_delete=models.PROTECT, related_name="renovacao",
                                             null=True, blank=True, editable=False)
    categoria_acesso = models.CharField(max_length=12, choices=Unidade.Categoria.choices, default=Unidade.Categoria.TRADICIONAL, editable=False)
    acesso_tradicional_rede = models.BooleanField(default=False, editable=False)
    inicio = models.DateField()
    fim = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ATIVA)
    motivo_cancelamento = models.TextField(blank=True)
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["aluno"], condition=Q(status="ativa"), name="uma_matricula_ativa_por_aluno")]
        permissions = [("cancelar_matricula", "Pode cancelar matrícula")]

    def save(self, *args, **kwargs):
        if self._state.adding and self.plano_id:
            self.categoria_acesso = self.plano.categoria
            self.acesso_tradicional_rede = self.plano.acesso_tradicional_rede
            if self.valor_contratado is None:
                self.valor_contratado = self.plano.preco
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        if self.inicio and self.fim and self.fim < self.inicio:
            errors["fim"] = "O fim não pode anteceder o início."
        if self.status == self.Status.CANCELADA and not self.motivo_cancelamento.strip():
            errors["motivo_cancelamento"] = "Informe o motivo do cancelamento."
        if self.aluno_id and self.plano_id and self.aluno.unidade_id != self.plano.unidade_id:
            errors["plano"] = "O plano deve pertencer à unidade do aluno."
        if self.matricula_anterior_id and self.aluno_id:
            anterior = self.matricula_anterior
            if anterior.aluno_id != self.aluno_id or self.inicio and self.inicio <= anterior.fim:
                errors["matricula_anterior"] = "A renovação deve ser do mesmo aluno e começar após o fim do período anterior."
        elif self._state.adding and self.plano_id and not self.plano.ativo:
            errors["plano"] = "Não é possível contratar um plano inativo."
        if self._state.adding and self.plano_id and self.inicio and self.fim:
            from .services import calcular_fim_plano

            if self.fim != calcular_fim_plano(plano=self.plano, inicio=self.inicio):
                errors["fim"] = "O fim deve corresponder à duração do plano."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.aluno} — {self.plano}"


class Frequencia(models.Model):
    """Uma linha por entrada; relatórios contam linhas por aluno e período."""

    matricula = models.ForeignKey(Matricula, on_delete=models.PROTECT, related_name="frequencias")
    unidade = models.ForeignKey(Unidade, on_delete=models.PROTECT, related_name="entradas", null=True, blank=True,
                               help_text="Unidade onde ocorreu a entrada; registros antigos recebem a unidade sede.")
    entrada_em = models.DateTimeField(default=timezone.now)
    registrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        permissions = [("registrar_frequencia", "Pode registrar entrada")]

    def clean(self):
        super().clean()
        if not self.matricula_id or not self.entrada_em:
            return
        data = timezone.localtime(self.entrada_em).date() if timezone.is_aware(self.entrada_em) else self.entrada_em.date()
        if self.matricula.status != Matricula.Status.ATIVA or not self.matricula.inicio <= data <= self.matricula.fim:
            raise ValidationError("A entrada exige matrícula ativa e dentro da validade.")
        if self.unidade_id:
            from .services import plano_permita_unidade
            if not plano_permita_unidade(self.matricula, self.unidade, data):
                raise ValidationError({"unidade": "O plano não permite entrada nesta unidade e data."})

    def __str__(self):
        return f"{self.matricula.aluno} — {self.entrada_em:%d/%m/%Y %H:%M}"


class Pagamento(models.Model):
    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        PAGO = "pago", "Pago"
        CANCELADO = "cancelado", "Cancelado"

    class Forma(models.TextChoices):
        PIX = "pix", "Pix"
        CARTAO = "cartao", "Cartão"

    matricula = models.ForeignKey(Matricula, on_delete=models.PROTECT, related_name="pagamentos")
    competencia = models.DateField(null=True, blank=True, help_text="Primeiro dia do mês da mensalidade; vazio para registros anteriores.")
    valor = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    vencimento = models.DateField()
    pago_em = models.DateTimeField(null=True, blank=True)
    forma_pagamento = models.CharField(max_length=8, choices=Forma.choices, null=True, blank=True,
                                      help_text="Vazio em cobranças pendentes e pagamentos históricos sem informação.")
    confirmado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name="pagamentos_confirmados")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDENTE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["matricula", "competencia"], condition=Q(competencia__isnull=False), name="uma_mensalidade_por_competencia")]

    def clean(self):
        super().clean()
        if self.competencia and self.competencia.day != 1:
            raise ValidationError({"competencia": "Informe o primeiro dia do mês da competência."})
        if self.status == self.Status.PAGO and not self.pago_em:
            raise ValidationError({"pago_em": "Informe quando o pagamento ocorreu."})
        if self.status != self.Status.PAGO and self.forma_pagamento:
            raise ValidationError({"forma_pagamento": "A forma de pagamento só pode ser registrada ao quitar a cobrança."})

    def __str__(self):
        return f"{self.matricula.aluno} — {self.valor}"


class ConciliacaoLegado(models.Model):
    """Decisão irrevogável sobre um pagamento anterior às competências."""

    class Destino(models.TextChoices):
        ASSOCIADO = "associado", "Associado ao período"
        AVULSO = "avulso", "Recebimento fora do período"
        DESCARTADO = "descartado", "Cobrança antiga descartada"

    pagamento = models.OneToOneField(Pagamento, on_delete=models.PROTECT, related_name="conciliacao_legado")
    destino = models.CharField(max_length=12, choices=Destino.choices)
    justificativa = models.TextField()
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    registrado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Conciliação do pagamento {self.pagamento_id}: {self.get_destino_display()}"


class AcertoCancelamento(models.Model):
    """Decisão financeira e eventual devolução, preservando a cobrança original."""

    class Decisao(models.TextChoices):
        MANTER = "manter", "Manter dívida ou pagamento"
        CANCELAR = "cancelar", "Cancelar cobrança pendente"
        REEMBOLSAR = "reembolsar", "Reembolsar pagamento"

    matricula = models.OneToOneField(Matricula, on_delete=models.PROTECT, related_name="acerto_cancelamento")
    pagamento = models.ForeignKey(Pagamento, on_delete=models.PROTECT, null=True, blank=True)
    decisao = models.CharField(max_length=12, choices=Decisao.choices)
    valor_reembolso = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    justificativa = models.TextField()
    decidido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="acertos_decididos")
    decidido_em = models.DateTimeField(auto_now_add=True)
    reembolsado_em = models.DateTimeField(null=True, blank=True)
    reembolsado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                      related_name="acertos_reembolsados")

    def __str__(self):
        return f"Acerto da matrícula {self.matricula_id}: {self.get_decisao_display()}"


class LogAuditoria(models.Model):
    """Metadados de mudanças, sem cópia dos valores de dados pessoais."""

    unidade = models.ForeignKey(Unidade, on_delete=models.PROTECT, related_name="logs_auditoria")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    ocorrido_em = models.DateTimeField(auto_now_add=True)
    acao = models.CharField(max_length=12)
    entidade = models.CharField(max_length=60)
    objeto_id = models.CharField(max_length=40)
    campos_alterados = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-ocorrido_em", "-id"]

    def __str__(self):
        return f"{self.entidade} {self.objeto_id}: {self.acao}"
