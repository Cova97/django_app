from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from catalogo.models import Categoria, Libro
from clientes.models import Cliente

from .models import Prestamo

LIBRERIA = {'DIAS_PRESTAMO': 14, 'MULTA_POR_DIA': Decimal('10.00'), 'MAX_PRESTAMOS_ACTIVOS': 2}


@override_settings(LIBRERIA=LIBRERIA)
class PrestamoTests(TestCase):
    def setUp(self):
        categoria = Categoria.objects.create(nombre='Novela')
        self.libro = Libro.objects.create(
            isbn='1', titulo='Rayuela', autor='Cortázar', categoria=categoria,
            precio_venta=Decimal('200'), ejemplares_prestamo=2,
        )
        self.cliente = Cliente.objects.create(nombre='Ana', apellidos='López', email='ana@x.com')

    def prestar(self, inicio=date(2026, 10, 1), cliente=None):
        prestamo = Prestamo(
            cliente=cliente or self.cliente, libro=self.libro,
            fecha_prestamo=inicio, fecha_limite=inicio + timedelta(days=14),
        )
        prestamo.full_clean()
        prestamo.save()
        return prestamo

    def test_devolucion_a_tiempo_no_genera_multa(self):
        prestamo = self.prestar()
        self.assertIsNone(prestamo.devolver(date(2026, 10, 15)))
        self.assertFalse(prestamo.activo)

    def test_devolucion_tardia_genera_multa(self):
        prestamo = self.prestar()  # límite: 15 de octubre
        multa = prestamo.devolver(date(2026, 10, 18))
        self.assertEqual(multa.dias_retraso, 3)
        self.assertEqual(multa.monto, Decimal('30.00'))
        self.assertTrue(self.cliente.tiene_multas_pendientes())

    def test_vencidos(self):
        prestamo = self.prestar()
        self.assertFalse(Prestamo.objects.vencidos(hoy=date(2026, 10, 15)).exists())
        self.assertIn(prestamo, Prestamo.objects.vencidos(hoy=date(2026, 10, 16)))

    def test_no_presta_sin_ejemplares(self):
        otro = Cliente.objects.create(nombre='Luis', apellidos='Pérez', email='luis@x.com')
        self.prestar(inicio=date.today())
        self.prestar(inicio=date.today(), cliente=otro)
        self.assertEqual(self.libro.ejemplares_disponibles, 0)
        with self.assertRaisesMessage(ValidationError, 'No hay ejemplares'):
            self.prestar(inicio=date.today(), cliente=otro)

    def test_no_presta_con_multa_pendiente(self):
        self.prestar().devolver(date(2026, 10, 20))
        with self.assertRaisesMessage(ValidationError, 'multas pendientes'):
            self.prestar(inicio=date.today())

        self.cliente.prestamos.get().multa.pagar()
        self.prestar(inicio=date.today())

    def test_no_presta_con_prestamo_vencido(self):
        self.libro.ejemplares_prestamo = 5
        self.libro.save()
        self.prestar(inicio=date.today() - timedelta(days=30))
        with self.assertRaisesMessage(ValidationError, 'vencidos'):
            self.prestar(inicio=date.today())

    def test_limite_de_prestamos_activos(self):
        self.libro.ejemplares_prestamo = 5
        self.libro.save()
        self.prestar(inicio=date.today())
        self.prestar(inicio=date.today())
        with self.assertRaisesMessage(ValidationError, '2 préstamos activos'):
            self.prestar(inicio=date.today())
