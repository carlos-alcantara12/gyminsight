from datetime import date, time

from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import Aluno, ConfiguracaoRede, Feriado, Matricula, Pagamento, Plano, Unidade


class RedeDemonstracaoTests(TestCase):
    def test_rede_planos_alunos_feriados_e_horarios(self):
        call_command("configurar_grupos", verbosity=0)
        call_command("criar_rede_demo", verbosity=0)
        call_command("criar_rede_demo", verbosity=0)
        self.assertTrue(ConfiguracaoRede.habilitada())
        self.assertEqual(Unidade.objects.count(), 5)
        self.assertEqual(Aluno.objects.count(), 50)
        self.assertEqual(Plano.objects.count(), 15)
        self.assertEqual(Feriado.objects.count(), 50)
        self.assertEqual(Matricula.objects.filter(status="cancelada").count(), 10)
        self.assertEqual(Pagamento.objects.filter(status="pago").count(), 10)
        self.assertEqual(Pagamento.objects.filter(status="pendente", vencimento__lt=timezone.localdate()).count(), 15)
        for unidade in Unidade.objects.all():
            self.assertEqual(unidade.alunos.count(), 10)
            self.assertEqual(set(unidade.planos.values_list("nome", flat=True)), {"Tradicional", "Premium", "Diamante"})
            self.assertEqual(unidade.funcionamento_em(date(2026, 9, 28))["inicio"], time(5))
            self.assertEqual(unidade.funcionamento_em(date(2026, 10, 3))["fim"], time(18))
            self.assertEqual(unidade.funcionamento_em(date(2026, 4, 3))["inicio"], time(8))
            self.assertEqual(unidade.funcionamento_em(date(2026, 4, 3))["fim"], time(14))

        plano = Plano.objects.get(unidade__nome="GymInsight - Zona Norte", nome="Premium")
        plano.preco = "149.90"
        plano.full_clean()
        plano.save()
        self.assertEqual(Plano.objects.filter(nome="Premium", preco="149.90").count(), 5)

        operador = get_user_model().objects.get(username="gyminsight_rede_demo")
        operador.funcionario_academia.unidades_acesso.clear()
        self.client.force_login(operador)
        resposta = self.client.patch(f"/api/planos/{plano.pk}/", {"preco": "199.90"}, content_type="application/json")
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(Plano.objects.filter(nome="Premium", preco="149.90").count(), 5)

        nova = Unidade.objects.create(nome="Unidade adicional")
        self.assertEqual(set(nova.planos.values_list("nome", flat=True)), {"Tradicional", "Premium", "Diamante"})
