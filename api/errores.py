"""Manejo global de errores de la API.

Todas las respuestas de error tienen el mismo formato:

    {"error": {"estado": 400, "codigo": "datos_invalidos",
               "mensaje": "Los datos enviados no son válidos.", "detalles": {...}}}
"""
import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.http import JsonResponse
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler, set_rollback

logger = logging.getLogger('api')

CODIGOS = {
    400: ('datos_invalidos', 'Los datos enviados no son válidos.'),
    401: ('no_autenticado', 'Debes iniciar sesión.'),
    403: ('sin_permiso', 'No tienes permiso para realizar esta acción.'),
    404: ('no_encontrado', 'El recurso solicitado no existe.'),
    405: ('metodo_no_permitido', 'Método no permitido en esta ruta.'),
    406: ('formato_no_aceptado', 'Formato de respuesta no soportado.'),
    409: ('conflicto', 'La operación entra en conflicto con el estado actual.'),
    413: ('solicitud_muy_grande', 'La solicitud es demasiado grande.'),
    415: ('tipo_no_soportado', 'Tipo de contenido no soportado. Usa application/json.'),
    429: ('demasiadas_solicitudes', 'Demasiadas solicitudes. Intenta más tarde.'),
    500: ('error_interno', 'Ocurrió un error inesperado. Intenta más tarde.'),
}


class Conflicto(exceptions.APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = CODIGOS[409][1]
    default_code = 'conflicto'


def cuerpo_error(estado, mensaje=None, detalles=None):
    codigo, mensaje_base = CODIGOS.get(estado, ('error', 'Error en la solicitud.'))
    return {'error': {
        'estado': estado,
        'codigo': codigo,
        'mensaje': mensaje or mensaje_base,
        'detalles': detalles,
    }}


def respuesta_json_error(estado, mensaje=None):
    """Para errores que ocurren fuera de las vistas de DRF (rutas inexistentes, etc.)."""
    return JsonResponse(cuerpo_error(estado, mensaje), status=estado)


def _traducir(exc):
    """Convierte excepciones de Django/BD en excepciones HTTP de DRF."""
    if isinstance(exc, DjangoValidationError):
        # Las reglas de negocio de los modelos (stock, multas, etc.) llegan aquí.
        detalle = exc.message_dict if hasattr(exc, 'error_dict') else {'no_field_errors': exc.messages}
        return exceptions.ValidationError(detalle)
    if isinstance(exc, ProtectedError):
        return Conflicto('No se puede borrar: tiene registros relacionados.')
    if isinstance(exc, IntegrityError):
        return Conflicto('Los datos chocan con un registro existente.')
    return exc


def manejador_excepciones(exc, context):
    exc = _traducir(exc)
    respuesta = exception_handler(exc, context)

    if respuesta is None:
        # Error no previsto: se registra completo en el log, pero al cliente
        # no se le muestra nada interno (ni traza, ni SQL, ni rutas).
        vista = context.get('view').__class__.__name__ if context.get('view') else '?'
        logger.exception('Error no controlado en %s', vista)
        set_rollback()
        return Response(cuerpo_error(500), status=500)

    if isinstance(exc, exceptions.ValidationError):
        detalles = respuesta.data if isinstance(respuesta.data, dict) else {'no_field_errors': respuesta.data}
        respuesta.data = cuerpo_error(respuesta.status_code, detalles=detalles)
    else:
        mensaje = respuesta.data.get('detail') if isinstance(respuesta.data, dict) else None
        respuesta.data = cuerpo_error(respuesta.status_code, mensaje=str(mensaje) if mensaje else None)
    return respuesta
