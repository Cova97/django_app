from datetime import date, datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from catalogo.models import Categoria, Libro
from clientes.models import Cliente

from .models import DetalleVenta, Promocion, Venta


class VentaPromocionTests(TestCase):
    def setUp(self):
        self.novela = Categoria.objects.create(nombre='Novela')
        self.ciencia = Categoria.objects.create(nombre='Ciencia')
        self.libro = Libro.objects.create(
            isbn='1', titulo='Rayuela', autor='Cortázar', categoria=self.novela,
            precio_venta=Decimal('200.00'), stock_venta=5,
        )
        self.otro = Libro.objects.create(
            isbn='2', titulo='Cosmos', autor='Sagan', categoria=self.ciencia,
            precio_venta=Decimal('300.00'), stock_venta=5,
        )
        self.cliente = Cliente.objects.create(nombre='Ana', apellidos='López', email='ana@x.com')

    def vender(self, libro, cantidad, fecha=date(2026, 12, 15)):
        fecha = timezone.make_aware(datetime.combine(fecha, datetime.min.time().replace(hour=12)))
        venta = Venta.objects.create(cliente=self.cliente, fecha=fecha)
        detalle = DetalleVenta.objects.create(venta=venta, libro=libro, cantidad=cantidad)
        venta.recalcular_total()
        return venta, detalle

    def test_sin_promocion_cobra_precio_completo_y_descuenta_stock(self):
        venta, detalle = self.vender(self.libro, 2)
        self.assertIsNone(detalle.promocion)
        self.assertEqual(venta.total, Decimal('400.00'))
        self.libro.refresh_from_db()
        self.assertEqual(self.libro.stock_venta, 3)

    def test_promocion_de_temporada_por_categoria(self):
        promo = Promocion.objects.create(
            nombre='Navidad', descuento_porcentaje=Decimal('25'),
            fecha_inicio=date(2026, 12, 1), fecha_fin=date(2026, 12, 31),
        )
        promo.categorias.add(self.novela)

        venta, detalle = self.vender(self.libro, 2)
        self.assertEqual(detalle.promocion, promo)
        self.assertEqual(venta.total, Decimal('300.00'))

        _, detalle_otro = self.vender(self.otro, 1)
        self.assertIsNone(detalle_otro.promocion)

    def test_promocion_fuera_de_temporada_no_aplica(self):
        Promocion.objects.create(
            nombre='Navidad', descuento_porcentaje=Decimal('25'),
            fecha_inicio=date(2026, 12, 1), fecha_fin=date(2026, 12, 31),
        )
        _, detalle = self.vender(self.libro, 1, fecha=date(2027, 1, 5))
        self.assertIsNone(detalle.promocion)

    def test_se_aplica_la_mejor_promocion(self):
        Promocion.objects.create(
            nombre='General', descuento_porcentaje=Decimal('10'),
            fecha_inicio=date(2026, 12, 1), fecha_fin=date(2026, 12, 31),
        )
        especial = Promocion.objects.create(
            nombre='Rayuela', descuento_porcentaje=Decimal('40'),
            fecha_inicio=date(2026, 12, 1), fecha_fin=date(2026, 12, 31),
        )
        especial.libros.add(self.libro)

        _, detalle = self.vender(self.libro, 1)
        self.assertEqual(detalle.promocion, especial)
        _, detalle_otro = self.vender(self.otro, 1)
        self.assertEqual(detalle_otro.promocion.nombre, 'General')

    def test_stock_insuficiente(self):
        with self.assertRaises(ValidationError):
            self.vender(self.libro, 6)
        self.libro.refresh_from_db()
        self.assertEqual(self.libro.stock_venta, 5)
