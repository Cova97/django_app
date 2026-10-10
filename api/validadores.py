import re

from django.utils import timezone
from rest_framework import serializers

_HTML = re.compile(r'<[^>]*>')
_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_NOMBRE = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ' .-]+$")


def texto_seguro(valor):
    """Rechaza etiquetas HTML y caracteres de control (defensa contra XSS en el frontend)."""
    if _HTML.search(valor):
        raise serializers.ValidationError('No se permiten etiquetas HTML.')
    if _CONTROL.search(valor):
        raise serializers.ValidationError('Contiene caracteres no permitidos.')
    return valor


def nombre_persona(valor):
    if not _NOMBRE.match(valor):
        raise serializers.ValidationError('Solo se permiten letras, espacios, puntos, guiones y apóstrofos.')
    return valor


def no_futura(fecha):
    hoy = timezone.localdate()
    dia = timezone.localdate(fecha) if hasattr(fecha, 'hour') else fecha
    if dia > hoy:
        raise serializers.ValidationError('La fecha no puede ser futura.')
    return fecha


def parametro(request, nombre, campo):
    """Lee y valida un parámetro de la URL (?nombre=valor) con un campo de DRF.

    Nunca se usa el texto crudo: se convierte al tipo esperado o se responde 400.
    """
    valor = request.query_params.get(nombre)
    if valor in (None, ''):
        return None
    try:
        return campo.run_validation(valor)
    except serializers.ValidationError as error:
        raise serializers.ValidationError({nombre: error.detail})
