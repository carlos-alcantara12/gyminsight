from contextlib import contextmanager
from contextvars import ContextVar


_ator = ContextVar("gyminsight_audit_actor", default=None)


def ator_atual():
    usuario = _ator.get()
    return usuario if usuario is not None and usuario.is_authenticated else None


def definir_ator(usuario):
    """Usado após a autenticação do DRF, que ocorre depois do middleware."""
    _ator.set(usuario)


@contextmanager
def ator_da_operacao(usuario):
    token = _ator.set(usuario)
    try:
        yield
    finally:
        _ator.reset(token)


class AuditActorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with ator_da_operacao(request.user):
            return self.get_response(request)
