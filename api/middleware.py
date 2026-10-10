import logging

from rest_framework.response import Response

from .errores import respuesta_json_error

logger = logging.getLogger('api')


class ErroresJsonApiMiddleware:
    """Garantiza respuestas JSON en /api/ aun cuando el error ocurre fuera de DRF.

    Por ejemplo, una ruta que no existe (/api/no-existe/) normalmente devuelve
    la página HTML de error de Django; aquí se convierte al formato de la API.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        respuesta = self.get_response(request)
        if (
            self._es_api(request)
            and respuesta.status_code >= 400
            and not isinstance(respuesta, Response)  # las de DRF ya vienen formateadas
            and not respuesta.get('Content-Type', '').startswith('application/json')
        ):
            return respuesta_json_error(respuesta.status_code)
        return respuesta

    def process_exception(self, request, exception):
        if self._es_api(request):
            logger.exception('Error no controlado en %s', request.path)
            return respuesta_json_error(500)
        return None

    @staticmethod
    def _es_api(request):
        return request.path.startswith('/api/')
