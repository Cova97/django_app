"""Flujos completos de préstamo, retraso y multa tal como se operan desde el admin."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from catalogo.models import Categoria, Libro
from clientes.models import Cliente

from .models import Multa, Prestamo

LIBRERIA = {'DIAS_PRESTAMO': 14, 'MULTA_POR_DIA': Decimal('10.00'), 'MAX_PRESTAMOS_ACTIVOS': 3}


@override_settings(LIBRERIA=LIBRERIA)
class FlujoPrestamoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('bibliotecario', 'b@x.com', 'x')
        cls.categoria = Categoria.objects.create(nombre='Novela')
        cls.hoy = timezone.localdate()

    def setUp(self):
        self.client.force_login(self.admin)
        self.libro = Libro.objects.create(
            isbn='1', titulo='Rayuela', autor='Cortázar', categoria=self.categoria,
            precio_venta=Decimal('200'), ejemplares_prestamo=2,
        )
        self.ana = Cliente.objects.create(nombre='Ana', apellidos='López', email='ana@x.com')
        self.luis = Cliente.objects.create(nombre='Luis', apellidos='Pérez', email='luis@x.com')

    # --- helpers que simulan lo que hace el bibliotecario en el admin ---

    def prestar(self, cliente, libro=None, inicio=None, dias=14):
        inicio = inicio or self.hoy
        return self.client.post(reverse('admin:prestamos_prestamo_add'), {
            'cliente': cliente.pk,
            'libro': (libro or self.libro).pk,
            'fecha_prestamo': inicio.isoformat(),
            'fecha_limite': (inicio + timedelta(days=dias)).isoformat(),
            '_save': 'Guardar',
        })

    def prestamo_atrasado(self, cliente, dias_retraso):
        """Préstamo hecho en el pasado cuya fecha límite ya pasó hace `dias_retraso` días."""
        limite = self.hoy - timedelta(days=dias_retraso)
        return Prestamo.objects.create(
            cliente=cliente, libro=self.libro,
            fecha_prestamo=limite - timedelta(days=14), fecha_limite=limite,
        )

    def devolver(self, *prestamos):
        return self.client.post(reverse('admin:prestamos_prestamo_changelist'), {
            'action': 'registrar_devolucion',
            '_selected_action': [p.pk for p in prestamos],
        }, follow=True)

    def pagar(self, *multas):
        return self.client.post(reverse('admin:prestamos_multa_changelist'), {
            'action': 'marcar_pagadas',
            '_selected_action': [m.pk for m in multas],
        }, follow=True)

    def listado(self, estado=''):
        url = reverse('admin:prestamos_prestamo_changelist')
        return self.client.get(f'{url}?estado={estado}' if estado else url)

    # --- Préstamo y devolución a tiempo ---

    def test_prestamo_y_devolucion_a_tiempo(self):
        respuesta = self.prestar(self.ana)
        self.assertRedirects(respuesta, reverse('admin:prestamos_prestamo_changelist'))
        prestamo = Prestamo.objects.get()
        self.assertEqual(prestamo.fecha_limite, self.hoy + timedelta(days=14))
        self.assertEqual(self.libro.ejemplares_disponibles, 1)

        respuesta = self.devolver(prestamo)
        self.assertContains(respuesta, '1 préstamo(s) devuelto(s), 0 multa(s) generada(s).')
        prestamo.refresh_from_db()
        self.assertEqual(prestamo.fecha_devolucion, self.hoy)
        self.assertEqual(self.libro.ejemplares_disponibles, 2)
        self.assertFalse(Multa.objects.exists())

    def test_devolver_justo_el_dia_limite_no_genera_multa(self):
        prestamo = self.prestamo_atrasado(self.ana, dias_retraso=0)
        self.devolver(prestamo)
        self.assertFalse(Multa.objects.exists())

    # --- Retrasos ---

    def test_prestamo_atrasado_aparece_como_vencido_con_multa_estimada(self):
        self.prestamo_atrasado(self.ana, dias_retraso=6)
        self.prestar(self.luis)

        vencidos = self.listado('vencidos')
        self.assertEqual(vencidos.context['cl'].result_count, 1)
        self.assertContains(vencidos, 'VENCIDO')
        self.assertContains(vencidos, '$60.00 (estimada)')
        self.assertEqual(self.listado('activos').context['cl'].result_count, 2)

    def test_un_dia_de_retraso_genera_multa_de_un_dia(self):
        prestamo = self.prestamo_atrasado(self.ana, dias_retraso=1)
        self.devolver(prestamo)
        multa = Multa.objects.get()
        self.assertEqual((multa.dias_retraso, multa.monto), (1, Decimal('10.00')))

    def test_flujo_completo_retraso_multa_bloqueo_pago_y_nuevo_prestamo(self):
        prestamo = self.prestamo_atrasado(self.ana, dias_retraso=6)

        # 1. Mientras no devuelva el libro vencido, no puede pedir otro.
        respuesta = self.prestar(self.ana)
        self.assertContains(respuesta, 'préstamos vencidos sin devolver')

        # 2. Devuelve con 6 días de retraso: se genera multa de $60.
        respuesta = self.devolver(prestamo)
        self.assertContains(respuesta, '1 multa(s) generada(s)')
        multa = Multa.objects.get()
        self.assertEqual(multa.dias_retraso, 6)
        self.assertEqual(multa.monto, Decimal('60.00'))
        self.assertFalse(multa.pagada)
        self.assertContains(self.listado('devueltos'), '$60.00 (pendiente)')

        # 3. Con la multa pendiente sigue bloqueado.
        respuesta = self.prestar(self.ana)
        self.assertContains(respuesta, 'multas pendientes de pago')
        self.assertEqual(Prestamo.objects.count(), 1)

        # 4. Paga la multa.
        self.assertContains(self.pagar(multa), '1 multa(s) marcadas como pagadas.')
        multa.refresh_from_db()
        self.assertTrue(multa.pagada)
        self.assertEqual(multa.fecha_pago, self.hoy)

        # 5. Ya puede volver a pedir prestado.
        self.assertRedirects(self.prestar(self.ana), reverse('admin:prestamos_prestamo_changelist'))
        self.assertEqual(self.ana.prestamos.activos().count(), 1)

    def test_devolver_dos_veces_no_duplica_la_multa(self):
        prestamo = self.prestamo_atrasado(self.ana, dias_retraso=3)
        self.devolver(prestamo)
        respuesta = self.devolver(prestamo)
        self.assertContains(respuesta, '0 préstamo(s) devuelto(s)')
        self.assertEqual(Multa.objects.count(), 1)

    def test_devolucion_masiva_mezcla_a_tiempo_y_atrasados(self):
        self.libro.ejemplares_prestamo = 5
        self.libro.save()
        a_tiempo = Prestamo.objects.create(cliente=self.ana, libro=self.libro)
        atrasado_1 = self.prestamo_atrasado(self.ana, dias_retraso=2)
        atrasado_2 = self.prestamo_atrasado(self.luis, dias_retraso=5)

        respuesta = self.devolver(a_tiempo, atrasado_1, atrasado_2)
        self.assertContains(respuesta, '3 préstamo(s) devuelto(s), 2 multa(s) generada(s).')
        self.assertEqual(
            sorted(Multa.objects.values_list('monto', flat=True)),
            [Decimal('20.00'), Decimal('50.00')],
        )

    def test_pagar_una_multa_ya_pagada_no_cambia_su_fecha(self):
        self.devolver(self.prestamo_atrasado(self.ana, dias_retraso=2))
        multa = Multa.objects.get()
        multa.pagar(self.hoy - timedelta(days=5))
        self.assertContains(self.pagar(multa), '0 multa(s) marcadas')
        multa.refresh_from_db()
        self.assertEqual(multa.fecha_pago, self.hoy - timedelta(days=5))

    def test_las_multas_no_se_capturan_a_mano(self):
        respuesta = self.client.get(reverse('admin:prestamos_multa_add'))
        self.assertEqual(respuesta.status_code, 403)

    # --- Disponibilidad y límites ---

    def test_sin_ejemplares_disponibles_hasta_que_alguien_devuelva(self):
        otra = Cliente.objects.create(nombre='Eva', apellidos='Ruiz', email='eva@x.com')
        self.prestar(self.ana)
        self.prestar(self.luis)
        self.assertEqual(self.libro.ejemplares_disponibles, 0)

        respuesta = self.prestar(otra)
        self.assertContains(respuesta, 'No hay ejemplares disponibles')

        self.devolver(self.ana.prestamos.get())
        self.assertRedirects(self.prestar(otra), reverse('admin:prestamos_prestamo_changelist'))

    def test_limite_de_prestamos_activos_por_cliente(self):
        self.libro.ejemplares_prestamo = 10
        self.libro.save()
        for _ in range(3):
            self.prestar(self.ana)

        respuesta = self.prestar(self.ana)
        self.assertContains(respuesta, 'ya tiene 3 préstamos activos')

        self.devolver(self.ana.prestamos.first())
        self.assertRedirects(self.prestar(self.ana), reverse('admin:prestamos_prestamo_changelist'))

    def test_cliente_inactivo_no_puede_pedir_prestado(self):
        self.ana.activo = False
        self.ana.save()
        self.assertContains(self.prestar(self.ana), 'El cliente está inactivo')

    def test_fecha_limite_anterior_al_prestamo_se_rechaza(self):
        respuesta = self.prestar(self.ana, dias=-1)
        self.assertContains(respuesta, 'Debe ser posterior a la fecha de préstamo')
        self.assertFalse(Prestamo.objects.exists())

    @override_settings(LIBRERIA={**LIBRERIA, 'MULTA_POR_DIA': Decimal('25.50')})
    def test_monto_de_multa_configurable(self):
        self.devolver(self.prestamo_atrasado(self.ana, dias_retraso=4))
        self.assertEqual(Multa.objects.get().monto, Decimal('102.00'))
