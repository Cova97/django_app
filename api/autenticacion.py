from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication


class TokenConCaducidad(TokenAuthentication):
    """Token en el header `Authorization: Token <clave>` que caduca tras API_TOKEN_HORAS."""

    def authenticate_credentials(self, key):
        usuario, token = super().authenticate_credentials(key)
        vigencia = timedelta(hours=settings.API_TOKEN_HORAS)
        if token.created < timezone.now() - vigencia:
            token.delete()
            raise exceptions.AuthenticationFailed('La sesión expiró. Inicia sesión de nuevo.')
        return usuario, token
