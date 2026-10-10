from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase

from clientes.models import Cliente
from prestamos.models import Multa, Prestamo
from ventas.models import DetalleVenta, Venta


class CargarDatosTests(TestCase):
    def cargar(self, *args):
        call_command('cargar_datos', *args, stdout=StringIO())

    def test_carga_escenarios_de_ejemplo(self):
        self.cargar()

        self.assertEqual(Venta.objects.count(), 11)
        self.assertEqual(Prestamo.objects.vencidos().count(), 2)
        self.assertEqual(Multa.objects.filter(pagada=False).count(), 1)
        self.assertTrue(Cliente.objects.get(nombre='Jorge').tiene_multas_pendientes())
        # La promoción desactivada nunca se aplica; la mayor vigente sí.
        self.assertFalse(DetalleVenta.objects.filter(promocion__activa=False).exists())
        quijote = DetalleVenta.objects.get(libro__titulo='Don Quijote de la Mancha')
        self.assertEqual(quijote.promocion.nombre, 'Semana de los clásicos')

    def test_no_duplica_sin_borrar(self):
        self.cargar()
        with self.assertRaises(CommandError):
            self.cargar()
        self.cargar('--borrar')
        self.assertEqual(Venta.objects.count(), 11)
