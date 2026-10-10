"""Operaciones de venta compartidas por el admin, la API y el sitio web."""
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import DetalleVenta, Promocion, Venta


def errores_de_stock(lineas):
    """Revisa [(libro, cantidad), ...] sumando las líneas del mismo libro."""
    cantidades = Counter()
    libros = {}
    for libro, cantidad in lineas:
        cantidades[libro.pk] += cantidad
        libros[libro.pk] = libro
    return [
        f'"{libros[pk].titulo}": pediste {cantidad} y solo hay {libros[pk].stock_venta} en stock.'
        for pk, cantidad in cantidades.items() if cantidad > libros[pk].stock_venta
    ]


@transaction.atomic
def registrar_venta(cliente, lineas, fecha=None):
    """Crea la venta con sus líneas; cada línea aplica su promoción y descuenta stock."""
    errores = errores_de_stock(lineas)
    if errores:
        raise ValidationError(errores)
    venta = Venta.objects.create(cliente=cliente, **({'fecha': fecha} if fecha else {}))
    for libro, cantidad in lineas:
        DetalleVenta.objects.create(venta=venta, libro=libro, cantidad=cantidad)
    venta.recalcular_total()
    return venta


class PromocionesVigentes:
    """Carga las promociones vigentes en 3 consultas y resuelve la mejor para cada libro en memoria.

    Útil para listados: evita hacer una consulta por cada libro.
    """

    def __init__(self, fecha=None):
        self.promociones = list(
            Promocion.objects.vigentes(fecha).prefetch_related('libros', 'categorias')
        )
        for promo in self.promociones:
            promo.libros_ids = {libro.pk for libro in promo.libros.all()}
            promo.categorias_ids = {categoria.pk for categoria in promo.categorias.all()}

    def para(self, libro):
        aplicables = [
            p for p in self.promociones
            if (not p.libros_ids and not p.categorias_ids)
            or libro.pk in p.libros_ids or libro.categoria_id in p.categorias_ids
        ]
        return max(aplicables, key=lambda p: p.descuento_porcentaje, default=None)

    def precio_final(self, libro):
        promo = self.para(libro)
        if not promo:
            return libro.precio_venta
        precio = libro.precio_venta * (Decimal('100') - promo.descuento_porcentaje) / Decimal('100')
        return precio.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
