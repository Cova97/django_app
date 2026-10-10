from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from catalogo.models import Categoria, Libro
from clientes.models import Cliente
from prestamos.models import Multa, Prestamo
from ventas.models import Promocion, Venta


class BaseWebTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('crear_roles', stdout=StringIO())
        cls.hoy = timezone.localdate()
        cls.novela = Categoria.objects.create(nombre='Novela')
        cls.ana = Cliente.objects.create(nombre='Ana', apellidos='López', email='ana@x.com')

    def setUp(self):
        self.libro = Libro.objects.create(
            isbn='9780307474728', titulo='Cien años de soledad', autor='García Márquez',
            categoria=self.novela, precio_venta=Decimal('200.00'), stock_venta=10, ejemplares_prestamo=2,
        )

    def entrar(self, rol):
        usuario = User.objects.create_user(rol.lower(), password='x', is_staff=True)
        usuario.groups.add(Group.objects.get(name=rol))
        self.client.force_login(usuario)
        return usuario

    def prestamo_vencido(self, dias=6, cliente=None):
        limite = self.hoy - timedelta(days=dias)
        return Prestamo.objects.create(
            cliente=cliente or self.ana, libro=self.libro,
            fecha_prestamo=limite - timedelta(days=14), fecha_limite=limite,
        )

    def mensajes(self, respuesta):
        return [str(m) for m in respuesta.context['messages']]


class CatalogoPublicoTests(BaseWebTest):
    def test_se_ve_sin_iniciar_sesion_con_precio_de_promocion(self):
        Promocion.objects.create(nombre='Otoño', descuento_porcentaje=25, fecha_inicio=self.hoy, fecha_fin=self.hoy)
        respuesta = self.client.get(reverse('web:catalogo'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Cien años de soledad')
        self.assertContains(respuesta, '$150.00')  # 200 - 25%
        self.assertContains(respuesta, 'Otoño')
        self.assertContains(respuesta, 'Acceso empleados')

    def test_busqueda_y_filtros_invalidos_no_fallan(self):
        self.assertContains(self.client.get('/?q=soledad'), 'Cien años')
        self.assertNotContains(self.client.get('/?q=inexistente'), 'Cien años')
        self.assertEqual(self.client.get('/?categoria=abc&pagina=xyz').status_code, 200)
        self.assertEqual(self.client.get("/?q=' OR '1'='1").status_code, 200)


class AccesoTests(BaseWebTest):
    def test_panel_pide_login(self):
        respuesta = self.client.get(reverse('web:panel'))
        self.assertRedirects(respuesta, f"{reverse('login')}?next={reverse('web:panel')}")

    def test_login_y_logout(self):
        User.objects.create_user('cajero', password='clave-123', is_staff=True)
        respuesta = self.client.post(reverse('login'), {'username': 'cajero', 'password': 'clave-123'})
        self.assertRedirects(respuesta, reverse('web:panel'))
        respuesta = self.client.post(reverse('logout'))
        self.assertRedirects(respuesta, reverse('web:catalogo'))

    def test_login_incorrecto(self):
        respuesta = self.client.post(reverse('login'), {'username': 'nadie', 'password': 'x'})
        self.assertContains(respuesta, 'Usuario o contraseña incorrectos')

    def test_menu_segun_rol(self):
        self.entrar('Cajero')
        respuesta = self.client.get(reverse('web:panel'))
        self.assertContains(respuesta, reverse('web:ventas_lista'))
        self.assertNotContains(respuesta, reverse('web:prestamos_lista'))

    def test_sin_permiso_muestra_pagina_403(self):
        self.entrar('Cajero')
        respuesta = self.client.get(reverse('web:prestamos_lista'))
        self.assertEqual(respuesta.status_code, 403)
        self.assertTemplateUsed(respuesta, '403.html')

    def test_pagina_404_propia(self):
        respuesta = self.client.get('/no-existe/')
        self.assertEqual(respuesta.status_code, 404)
        self.assertContains(respuesta, 'Página no encontrada', status_code=404)

    def test_acciones_solo_por_post_y_con_csrf(self):
        self.entrar('Bibliotecario')
        prestamo = self.prestamo_vencido()
        url = reverse('web:prestamo_devolver', args=[prestamo.pk])
        self.assertEqual(self.client.get(url).status_code, 405)

        con_csrf = Client(enforce_csrf_checks=True)
        con_csrf.force_login(User.objects.get(username='bibliotecario'))
        respuesta = con_csrf.post(url)
        self.assertEqual(respuesta.status_code, 403)
        self.assertContains(respuesta, 'expiró', status_code=403)
        prestamo.refresh_from_db()
        self.assertTrue(prestamo.activo)

    def test_no_redirige_a_sitios_externos(self):
        self.entrar('Bibliotecario')
        prestamo = self.prestamo_vencido()
        respuesta = self.client.post(
            reverse('web:prestamo_devolver', args=[prestamo.pk]), {'siguiente': 'https://sitio-malicioso.com/'}
        )
        self.assertRedirects(respuesta, reverse('web:prestamos_lista'))


class FlujoVentaWebTests(BaseWebTest):
    def datos_venta(self, *lineas, cliente=None):
        datos = {
            'cliente': (cliente or self.ana).pk,
            'lineas-TOTAL_FORMS': len(lineas), 'lineas-INITIAL_FORMS': 0,
            'lineas-MIN_NUM_FORMS': 1, 'lineas-MAX_NUM_FORMS': 50,
        }
        for i, (libro, cantidad) in enumerate(lineas):
            datos[f'lineas-{i}-libro'] = libro.pk
            datos[f'lineas-{i}-cantidad'] = cantidad
        return datos

    def test_cajero_registra_venta_con_promocion(self):
        self.entrar('Cajero')
        Promocion.objects.create(nombre='Otoño', descuento_porcentaje=10, fecha_inicio=self.hoy, fecha_fin=self.hoy)
        self.assertContains(self.client.get(reverse('web:venta_nueva')), 'Total estimado')

        respuesta = self.client.post(reverse('web:venta_nueva'), self.datos_venta((self.libro, 2)), follow=True)
        venta = Venta.objects.get()
        self.assertRedirects(respuesta, reverse('web:venta_detalle', args=[venta.pk]))
        self.assertEqual(venta.total, Decimal('360.00'))
        self.assertIn(f'Venta #{venta.pk} registrada por $360.00.', self.mensajes(respuesta))
        self.assertContains(respuesta, 'Otoño')
        self.libro.refresh_from_db()
        self.assertEqual(self.libro.stock_venta, 8)

    def test_stock_insuficiente_muestra_error_y_no_registra(self):
        self.entrar('Cajero')
        respuesta = self.client.post(
            reverse('web:venta_nueva'), self.datos_venta((self.libro, 6), (self.libro, 5))
        )
        self.assertContains(respuesta, 'pediste 11 y solo hay 10')
        self.assertFalse(Venta.objects.exists())

    def test_venta_sin_lineas_o_sin_cliente(self):
        self.entrar('Cajero')
        respuesta = self.client.post(reverse('web:venta_nueva'), {
            'cliente': '', 'lineas-TOTAL_FORMS': 0, 'lineas-INITIAL_FORMS': 0,
            'lineas-MIN_NUM_FORMS': 1, 'lineas-MAX_NUM_FORMS': 50,
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('cliente', respuesta.context['formulario'].errors)
        self.assertTrue(respuesta.context['lineas'].non_form_errors())  # al menos una línea
        self.assertFalse(Venta.objects.exists())

    def test_listado_y_filtro_por_fecha(self):
        self.entrar('Cajero')
        self.client.post(reverse('web:venta_nueva'), self.datos_venta((self.libro, 1)))
        hoy = self.hoy.isoformat()
        self.assertContains(self.client.get(f'{reverse("web:ventas_lista")}?desde={hoy}&hasta={hoy}'), 'Ana López')
        ayer = (self.hoy - timedelta(days=1)).isoformat()
        self.assertNotContains(self.client.get(f'{reverse("web:ventas_lista")}?hasta={ayer}'), 'Ana López')


class FlujoPrestamoWebTests(BaseWebTest):
    def test_prestamo_retraso_multa_cobro_y_nuevo_prestamo(self):
        self.entrar('Bibliotecario')
        prestamo = self.prestamo_vencido(dias=6)

        # El panel y la pestaña de vencidos lo muestran con su multa estimada.
        self.assertContains(self.client.get(reverse('web:panel')), '$60.00')
        vencidos = self.client.get(f"{reverse('web:prestamos_lista')}?estado=vencidos")
        self.assertContains(vencidos, 'Vencido · 6 días')

        # No puede llevarse otro libro mientras tenga uno vencido.
        respuesta = self.client.post(reverse('web:prestamo_nuevo'), {
            'cliente': self.ana.pk, 'libro': self.libro.pk, 'fecha_limite': self.hoy + timedelta(days=14),
        })
        self.assertContains(respuesta, 'préstamos vencidos sin devolver')

        # Devuelve: se genera la multa.
        respuesta = self.client.post(reverse('web:prestamo_devolver', args=[prestamo.pk]), follow=True)
        self.assertIn('Se generó una multa de $60.00', ' '.join(self.mensajes(respuesta)))
        multa = Multa.objects.get()

        # Cobra la multa desde la pantalla de multas.
        self.assertContains(self.client.get(reverse('web:multas_lista')), 'Cobrar')
        respuesta = self.client.post(reverse('web:multa_pagar', args=[multa.pk]), follow=True)
        self.assertIn('marcada como pagada', ' '.join(self.mensajes(respuesta)))

        # Ya puede pedir prestado otra vez.
        respuesta = self.client.post(reverse('web:prestamo_nuevo'), {
            'cliente': self.ana.pk, 'libro': self.libro.pk, 'fecha_limite': self.hoy + timedelta(days=14),
        }, follow=True)
        self.assertRedirects(respuesta, reverse('web:prestamos_lista'))
        self.assertEqual(self.ana.prestamos.activos().count(), 1)

    def test_devolucion_a_tiempo(self):
        self.entrar('Bibliotecario')
        prestamo = Prestamo.objects.create(cliente=self.ana, libro=self.libro)
        respuesta = self.client.post(reverse('web:prestamo_devolver', args=[prestamo.pk]), follow=True)
        self.assertIn('devuelto a tiempo', ' '.join(self.mensajes(respuesta)))
        self.assertFalse(Multa.objects.exists())

    def test_devolver_dos_veces_avisa(self):
        self.entrar('Bibliotecario')
        prestamo = self.prestamo_vencido()
        self.client.post(reverse('web:prestamo_devolver', args=[prestamo.pk]))
        respuesta = self.client.post(reverse('web:prestamo_devolver', args=[prestamo.pk]), follow=True)
        self.assertIn('ya había sido devuelto', ' '.join(self.mensajes(respuesta)))
        self.assertEqual(Multa.objects.count(), 1)


class ClientesWebTests(BaseWebTest):
    def test_alta_con_validaciones(self):
        self.entrar('Cajero')
        respuesta = self.client.post(reverse('web:cliente_nuevo'), {
            'nombre': 'Luis99', 'apellidos': 'Pérez', 'email': 'ANA@X.COM', 'telefono': '55-12', 'activo': 'on',
        })
        self.assertContains(respuesta, 'Solo se permiten letras')
        self.assertContains(respuesta, 'Ya existe un cliente con ese email')
        self.assertContains(respuesta, '10 dígitos')

        respuesta = self.client.post(reverse('web:cliente_nuevo'), {
            'nombre': 'Luis', 'apellidos': 'Pérez', 'email': 'Luis@X.com', 'telefono': '5512345678', 'activo': 'on',
        })
        luis = Cliente.objects.get(nombre='Luis')
        self.assertRedirects(respuesta, reverse('web:cliente_detalle', args=[luis.pk]))
        self.assertEqual(luis.email, 'luis@x.com')

    def test_detalle_muestra_historial(self):
        self.entrar('Gerente')
        prestamo = self.prestamo_vencido(dias=2)
        prestamo.devolver()
        respuesta = self.client.get(reverse('web:cliente_detalle', args=[self.ana.pk]))
        self.assertContains(respuesta, 'Cien años de soledad')
        self.assertContains(respuesta, 'pendiente')

    def test_todas_las_paginas_del_gerente_cargan(self):
        self.entrar('Gerente')
        Venta.objects.create(cliente=self.ana)
        for nombre in ['panel', 'ventas_lista', 'venta_nueva', 'prestamos_lista', 'prestamo_nuevo',
                       'multas_lista', 'clientes_lista', 'cliente_nuevo', 'inventario', 'promociones']:
            with self.subTest(pagina=nombre):
                self.assertEqual(self.client.get(reverse(f'web:{nombre}')).status_code, 200)
        for nombre, pk in [('venta_detalle', Venta.objects.get().pk), ('cliente_detalle', self.ana.pk),
                           ('cliente_editar', self.ana.pk)]:
            with self.subTest(pagina=nombre):
                self.assertEqual(self.client.get(reverse(f'web:{nombre}', args=[pk])).status_code, 200)
