from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def moneda(valor):
    """200 -> $200.00 ; 1234.5 -> $1,234.50"""
    if valor in (None, ''):
        return '$0.00'
    try:
        return f'${Decimal(valor):,.2f}'
    except (InvalidOperation, TypeError, ValueError):
        return valor


@register.simple_tag(takes_context=True)
def url_con(context, **cambios):
    """Conserva los filtros actuales de la URL cambiando solo algunos (p. ej. la página)."""
    parametros = context['request'].GET.copy()
    for clave, valor in cambios.items():
        parametros[clave] = valor
    return f'?{parametros.urlencode()}'
