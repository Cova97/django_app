"""Flujos completos de venta tal como se operan desde el admin."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from catalogo.models import Categoria, Libro
from clientes.models import Cliente

from .models import Promocion, Venta


class FlujoVentaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('cajero', 'cajero@x.com', 'x')
        cls.novela = Categoria.objects.create(nombre='Novela')
        cls.infantil = Categoria.objects.create(nombre='Infantil')
        cls.cliente = Cliente.objects.create(nombre='Ana', apellidos='López', email='ana@x.com')
        cls.hoy = timezone.localdate()

    def setUp(self):
        self.client.force_login(self.admin)
        self.rayuela = Libro.objects.create(
            isbn='1', titulo='Rayuela', autor='Cortázar', categoria=self.novela,
            precio_venta=Decimal('200.00'), stock_venta=10,
        )
        self.principito = Libro.objects.create(
            isbn='2', titulo='El principito', autor='Saint-Exupéry', categoria=self.infantil,
            precio_venta=Decimal('150.00'), stock_venta=10,
        )

    def registrar_venta(self, lineas, fecha=None):
        """Envía el formulario 'Añadir venta' del admin con [(libro, cantidad), ...]."""
        fecha = fecha or self.hoy
        datos = {
            'cliente': self.cliente.pk,
            'fecha_0': fecha.isoformat(),
            'fecha_1': '12:00:00',
            'detalles-TOTAL_FORMS': len(lineas),
            'detalles-INITIAL_FORMS': 0,
            'detalles-MIN_NUM_FORMS': 0,
            'detalles-MAX_NUM_FORMS': 1000,
            '_save': 'Guardar',
        }
        for i, (libro, cantidad) in enumerate(lineas):
            datos[f'detalles-{i}-libro'] = libro.pk
            datos[f'detalles-{i}-cantidad'] = cantidad
        return self.client.post(reverse('admin:ventas_venta_add'), datos)

    def crear_promo(self, nombre, porcentaje, inicio, fin, libros=(), categorias=(), activa=True):
        promo = Promocion.objects.create(
            nombre=nombre, descuento_porcentaje=Decimal(porcentaje),
            fecha_inicio=inicio, fecha_fin=fin, activa=activa,
        )
        promo.libros.set(libros)
        promo.categorias.set(categorias)
        return promo

    # --- Ventas sin promoción ---

    def test_venta_normal_cobra_precio_completo_y_descuenta_stock(self):
        respuesta = self.registrar_venta([(self.rayuela, 2), (self.principito, 1)])
        self.assertRedirects(respuesta, reverse('admin:ventas_venta_changelist'))

        venta = Venta.objects.get()
        self.assertEqual(venta.total, Decimal('550.00'))  # 2x200 + 1x150
        self.assertEqual(venta.detalles.count(), 2)
        self.rayuela.refresh_from_db()
        self.principito.refresh_from_db()
        self.assertEqual(self.rayuela.stock_venta, 8)
        self.assertEqual(self.principito.stock_venta, 9)

    def test_venta_sin_stock_suficiente_se_rechaza_sin_tocar_nada(self):
        respuesta = self.registrar_venta([(self.rayuela, 11)])
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Solo hay 10 unidades en stock')
        self.assertFalse(Venta.objects.exists())
        self.rayuela.refresh_from_db()
        self.assertEqual(self.rayuela.stock_venta, 10)

    def test_mismo_libro_en_varias_lineas_suma_para_validar_stock(self):
        respuesta = self.registrar_venta([(self.rayuela, 6), (self.rayuela, 5)])
        self.assertContains(respuesta, 'pediste 11 y solo hay 10')
        self.assertFalse(Venta.objects.exists())

    def test_vender_todo_el_stock_y_luego_ya_no_se_puede(self):
        self.registrar_venta([(self.rayuela, 10)])
        self.rayuela.refresh_from_db()
        self.assertEqual(self.rayuela.stock_venta, 0)

        respuesta = self.registrar_venta([(self.rayuela, 1)])
        self.assertContains(respuesta, 'Solo hay 0 unidades en stock')
        self.assertEqual(Venta.objects.count(), 1)

    def test_cambiar_precio_despues_no_altera_ventas_anteriores(self):
        self.registrar_venta([(self.rayuela, 1)])
        self.rayuela.precio_venta = Decimal('999.00')
        self.rayuela.save()

        venta = Venta.objects.get()
        venta.recalcular_total()
        self.assertEqual(venta.total, Decimal('200.00'))

    def test_venta_registrada_queda_de_solo_lectura(self):
        self.registrar_venta([(self.rayuela, 1)])
        venta = Venta.objects.get()
        html = self.client.get(reverse('admin:ventas_venta_change', args=[venta.pk])).content.decode()
        self.assertNotIn('name="detalles-0-cantidad"', html)
        self.assertNotIn('name="cliente"', html)

    # --- Promociones por temporada ---

    def test_promocion_de_temporada_por_categoria(self):
        promo = self.crear_promo(
            'Día del niño', '30', self.hoy - timedelta(days=3), self.hoy + timedelta(days=3),
            categorias=[self.infantil],
        )
        self.registrar_venta([(self.principito, 2), (self.rayuela, 1)])

        venta = Venta.objects.get()
        infantil = venta.detalles.get(libro=self.principito)
        novela = venta.detalles.get(libro=self.rayuela)
        self.assertEqual(infantil.promocion, promo)
        self.assertEqual(infantil.subtotal, Decimal('210.00'))  # 300 - 30%
        self.assertIsNone(novela.promocion)
        self.assertEqual(venta.total, Decimal('410.00'))

    def test_promocion_general_aplica_a_todo_el_catalogo(self):
        self.crear_promo('Buen Fin', '10', self.hoy, self.hoy)
        self.registrar_venta([(self.rayuela, 1), (self.principito, 1)])
        self.assertEqual(Venta.objects.get().total, Decimal('315.00'))  # 350 - 10%

    def test_se_aplica_la_promocion_con_mayor_descuento(self):
        inicio, fin = self.hoy - timedelta(days=1), self.hoy + timedelta(days=1)
        self.crear_promo('General', '10', inicio, fin)
        self.crear_promo('Novelas', '20', inicio, fin, categorias=[self.novela])
        rayuela = self.crear_promo('Rayuela', '50', inicio, fin, libros=[self.rayuela])

        self.registrar_venta([(self.rayuela, 1), (self.principito, 1)])
        venta = Venta.objects.get()
        self.assertEqual(venta.detalles.get(libro=self.rayuela).promocion, rayuela)
        self.assertEqual(venta.detalles.get(libro=self.principito).promocion.nombre, 'General')
        self.assertEqual(venta.total, Decimal('235.00'))  # 100 + 135

    def test_la_promocion_se_decide_por_la_fecha_de_la_venta(self):
        inicio, fin = self.hoy + timedelta(days=10), self.hoy + timedelta(days=20)
        self.crear_promo('Próxima temporada', '25', inicio, fin)

        self.registrar_venta([(self.rayuela, 1)], fecha=inicio - timedelta(days=1))
        self.registrar_venta([(self.rayuela, 1)], fecha=inicio)
        self.registrar_venta([(self.rayuela, 1)], fecha=fin)
        self.registrar_venta([(self.rayuela, 1)], fecha=fin + timedelta(days=1))

        totales = list(Venta.objects.order_by('fecha').values_list('total', flat=True))
        self.assertEqual(totales, [Decimal('200.00'), Decimal('150.00'), Decimal('150.00'), Decimal('200.00')])

    def test_promocion_desactivada_no_aplica(self):
        self.crear_promo('Pausada', '40', self.hoy, self.hoy, activa=False)
        self.registrar_venta([(self.rayuela, 1)])
        self.assertEqual(Venta.objects.get().total, Decimal('200.00'))

    def test_terminar_una_promocion_no_cambia_ventas_ya_hechas(self):
        promo = self.crear_promo('Navidad', '50', self.hoy, self.hoy)
        self.registrar_venta([(self.rayuela, 1)])
        promo.activa = False
        promo.save()

        venta = Venta.objects.get()
        venta.recalcular_total()
        self.assertEqual(venta.total, Decimal('100.00'))

    def test_no_se_puede_crear_promocion_con_fechas_invertidas(self):
        respuesta = self.client.post(reverse('admin:ventas_promocion_add'), {
            'nombre': 'Mal capturada', 'descuento_porcentaje': '10',
            'fecha_inicio': self.hoy.isoformat(),
            'fecha_fin': (self.hoy - timedelta(days=1)).isoformat(),
            'activa': 'on',
        })
        self.assertContains(respuesta, 'no puede terminar antes de empezar')
        self.assertFalse(Promocion.objects.exists())
