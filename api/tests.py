from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from catalogo.models import Categoria, Libro
from clientes.models import Cliente
from prestamos.models import Multa, Prestamo
from ventas.models import Promocion, Venta


class BaseApiTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('crear_roles', stdout=StringIO())
        cls.hoy = timezone.localdate()
        cls.novela = Categoria.objects.create(nombre='Novela')
        cls.cliente = Cliente.objects.create(nombre='Ana', apellidos='López', email='ana@x.com')

    def setUp(self):
        cache.clear()  # reinicia los contadores de límite de solicitudes
        self.api = APIClient()
        self.libro = Libro.objects.create(
            isbn='9780307474728', titulo='Cien años de soledad', autor='García Márquez',
            categoria=self.novela, precio_venta=Decimal('200.00'), stock_venta=10, ejemplares_prestamo=2,
        )

    def empleado(self, rol='Gerente', username=None):
        usuario = User.objects.create_user(username or (rol or 'sin_rol').lower(), password='clave-segura-123', is_staff=True)
        if rol:
            usuario.groups.add(Group.objects.get(name=rol))
        return usuario

    def como(self, rol='Gerente'):
        usuario = self.empleado(rol)
        token = Token.objects.create(user=usuario)
        self.api.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        return usuario

    def assertError(self, respuesta, estado, codigo):
        self.assertEqual(respuesta.status_code, estado, respuesta.content)
        self.assertEqual(respuesta['Content-Type'], 'application/json')
        error = respuesta.json()['error']
        self.assertEqual((error['estado'], error['codigo']), (estado, codigo))
        return error


class ErroresGlobalesTests(BaseApiTest):
    def test_ruta_inexistente_responde_json(self):
        self.assertError(self.api.get('/api/no-existe/'), 404, 'no_encontrado')

    def test_recurso_inexistente(self):
        self.como()
        self.assertError(self.api.get('/api/clientes/99999/'), 404, 'no_encontrado')

    def test_metodo_no_permitido(self):
        self.como()
        self.assertError(self.api.put('/api/clientes/', {}, format='json'), 405, 'metodo_no_permitido')

    def test_venta_no_se_puede_borrar(self):
        self.como()
        venta = Venta.objects.create(cliente=self.cliente)
        self.assertIn(self.api.delete(f'/api/ventas/{venta.pk}/').status_code, (403, 405))
        self.assertTrue(Venta.objects.filter(pk=venta.pk).exists())

    def test_json_mal_formado(self):
        self.como()
        respuesta = self.api.post('/api/clientes/', '{"nombre": ', content_type='application/json')
        self.assertError(respuesta, 400, 'datos_invalidos')

    def test_tipo_de_contenido_no_soportado(self):
        self.como()
        respuesta = self.api.post('/api/clientes/', 'nombre=Ana', content_type='application/x-www-form-urlencoded')
        self.assertError(respuesta, 415, 'tipo_no_soportado')

    def test_error_de_validacion_incluye_detalles_por_campo(self):
        self.como()
        error = self.assertError(self.api.post('/api/clientes/', {}, format='json'), 400, 'datos_invalidos')
        self.assertIn('nombre', error['detalles'])
        self.assertIn('email', error['detalles'])

    def test_borrar_con_registros_relacionados_es_conflicto(self):
        self.como()
        error = self.assertError(self.api.delete(f'/api/categorias/{self.novela.pk}/'), 409, 'conflicto')
        self.assertIn('registros relacionados', error['mensaje'])

    def test_error_inesperado_no_filtra_detalles_internos(self):
        self.como()
        with mock.patch('api.views.ClienteViewSet.get_queryset', side_effect=RuntimeError('SELECT secreto')):
            with self.assertLogs('api', level='ERROR') as registro, self.assertLogs('django.request', 'ERROR'):
                respuesta = self.api.get('/api/clientes/')
        error = self.assertError(respuesta, 500, 'error_interno')
        self.assertNotIn('secreto', respuesta.content.decode())
        self.assertIsNone(error['detalles'])
        self.assertIn('SELECT secreto', '\n'.join(registro.output))  # sí queda en el log

    def test_regla_de_negocio_del_modelo_se_convierte_en_400(self):
        self.como()
        Multa.objects.create(
            prestamo=Prestamo.objects.create(cliente=self.cliente, libro=self.libro, fecha_devolucion=self.hoy),
            dias_retraso=2, monto=Decimal('20'),
        )
        respuesta = self.api.post('/api/prestamos/', {'cliente': self.cliente.pk, 'libro': self.libro.pk}, format='json')
        error = self.assertError(respuesta, 400, 'datos_invalidos')
        self.assertIn('multas pendientes', error['detalles']['cliente'][0])


class AutenticacionTests(BaseApiTest):
    def login(self, username, password):
        return self.api.post('/api/auth/login/', {'username': username, 'password': password}, format='json')

    def test_login_entrega_token_y_permite_usar_la_api(self):
        self.empleado('Cajero')
        respuesta = self.login('cajero', 'clave-segura-123')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()['usuario']['grupos'], ['Cajero'])

        self.api.credentials(HTTP_AUTHORIZATION=f'Token {respuesta.json()["token"]}')
        self.assertEqual(self.api.get('/api/clientes/').status_code, 200)

    def test_credenciales_incorrectas_no_revelan_si_existe_el_usuario(self):
        self.empleado('Cajero')
        mal_password = self.assertError(self.login('cajero', 'otra'), 401, 'no_autenticado')
        no_existe = self.assertError(self.login('fantasma', 'otra'), 401, 'no_autenticado')
        self.assertEqual(mal_password['mensaje'], no_existe['mensaje'])

    def test_limite_de_intentos_de_login(self):
        for _ in range(5):
            self.login('nadie', 'x')
        self.assertError(self.login('nadie', 'x'), 429, 'demasiadas_solicitudes')

    def test_token_expirado(self):
        self.como()
        Token.objects.update(created=timezone.now() - timedelta(hours=9))
        error = self.assertError(self.api.get('/api/clientes/'), 401, 'no_autenticado')
        self.assertIn('expiró', error['mensaje'])
        self.assertFalse(Token.objects.exists())

    def test_logout_invalida_el_token(self):
        self.como()
        self.assertEqual(self.api.post('/api/auth/logout/').status_code, 204)
        self.assertError(self.api.get('/api/clientes/'), 401, 'no_autenticado')

    def test_token_falso(self):
        self.api.credentials(HTTP_AUTHORIZATION='Token inventado123')
        self.assertError(self.api.get('/api/clientes/'), 401, 'no_autenticado')


class PermisosTests(BaseApiTest):
    def test_catalogo_es_publico_para_lectura(self):
        self.assertEqual(self.api.get('/api/libros/').status_code, 200)
        self.assertEqual(self.api.get('/api/categorias/').status_code, 200)

    def test_anonimo_no_modifica_catalogo_ni_ve_datos_privados(self):
        self.assertError(self.api.post('/api/libros/', {}, format='json'), 401, 'no_autenticado')
        for ruta in ['/api/clientes/', '/api/ventas/', '/api/prestamos/', '/api/multas/']:
            self.assertError(self.api.get(ruta), 401, 'no_autenticado')

    def test_publico_solo_ve_promociones_vigentes(self):
        Promocion.objects.create(nombre='Vigente', descuento_porcentaje=10, fecha_inicio=self.hoy, fecha_fin=self.hoy)
        Promocion.objects.create(nombre='Inactiva', descuento_porcentaje=10, fecha_inicio=self.hoy,
                                 fecha_fin=self.hoy, activa=False)
        nombres = [p['nombre'] for p in self.api.get('/api/promociones/').json()['results']]
        self.assertEqual(nombres, ['Vigente'])

    def test_usuario_no_empleado_no_tiene_acceso(self):
        usuario = User.objects.create_user('cliente_web', password='x')
        self.api.force_authenticate(usuario)
        self.assertError(self.api.get('/api/clientes/'), 403, 'sin_permiso')

    def test_empleado_sin_rol_no_tiene_acceso(self):
        self.como(rol=None)
        self.assertError(self.api.get('/api/clientes/'), 403, 'sin_permiso')

    def test_cajero_vende_pero_no_presta_ni_cambia_catalogo(self):
        self.como('Cajero')
        venta = {'cliente': self.cliente.pk, 'detalles': [{'libro': self.libro.pk, 'cantidad': 1}]}
        self.assertEqual(self.api.post('/api/ventas/', venta, format='json').status_code, 201)
        prestamo = {'cliente': self.cliente.pk, 'libro': self.libro.pk}
        self.assertError(self.api.post('/api/prestamos/', prestamo, format='json'), 403, 'sin_permiso')
        self.assertError(self.api.patch(f'/api/libros/{self.libro.pk}/', {'precio_venta': '1'}, format='json'),
                         403, 'sin_permiso')

    def test_bibliotecario_presta_y_devuelve_pero_no_vende(self):
        self.como('Bibliotecario')
        respuesta = self.api.post('/api/prestamos/', {'cliente': self.cliente.pk, 'libro': self.libro.pk}, format='json')
        self.assertEqual(respuesta.status_code, 201)
        devolver = self.api.post(f'/api/prestamos/{respuesta.json()["id"]}/devolver/', {}, format='json')
        self.assertEqual(devolver.json()['estado'], 'devuelto')
        venta = {'cliente': self.cliente.pk, 'detalles': [{'libro': self.libro.pk, 'cantidad': 1}]}
        self.assertError(self.api.post('/api/ventas/', venta, format='json'), 403, 'sin_permiso')

    def test_solo_gerente_borra(self):
        otra = Categoria.objects.create(nombre='Vacía')
        self.como('Bibliotecario')
        self.assertError(self.api.delete(f'/api/categorias/{otra.pk}/'), 403, 'sin_permiso')
        self.api.credentials()
        self.como('Gerente')
        self.assertEqual(self.api.delete(f'/api/categorias/{otra.pk}/').status_code, 204)


class ValidacionTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.como()

    def detalles(self, respuesta):
        return self.assertError(respuesta, 400, 'datos_invalidos')['detalles']

    def test_libro_con_datos_invalidos(self):
        detalles = self.detalles(self.api.post('/api/libros/', {
            'isbn': '978-84-376', 'titulo': '<script>alert(1)</script>', 'autor': '',
            'categoria': 999, 'precio_venta': '-5', 'stock_venta': -1,
        }, format='json'))
        self.assertEqual(
            set(detalles), {'isbn', 'titulo', 'autor', 'categoria', 'precio_venta', 'stock_venta'}
        )

    def test_isbn_duplicado(self):
        detalles = self.detalles(self.api.post('/api/libros/', {
            'isbn': self.libro.isbn, 'titulo': 'Otro', 'autor': 'X', 'categoria': self.novela.pk,
            'precio_venta': '10',
        }, format='json'))
        self.assertIn('isbn', detalles)

    def test_no_bajar_ejemplares_por_debajo_de_los_prestados(self):
        Prestamo.objects.create(cliente=self.cliente, libro=self.libro)
        Prestamo.objects.create(cliente=self.cliente, libro=self.libro)
        detalles = self.detalles(self.api.patch(f'/api/libros/{self.libro.pk}/', {'ejemplares_prestamo': 1}, format='json'))
        self.assertIn('2 ejemplares prestados', detalles['ejemplares_prestamo'][0])

    def test_cliente_con_datos_invalidos(self):
        detalles = self.detalles(self.api.post('/api/clientes/', {
            'nombre': 'Ana123', 'apellidos': '<b>López</b>', 'email': 'no-es-email', 'telefono': '55-12',
        }, format='json'))
        self.assertEqual(set(detalles), {'nombre', 'apellidos', 'email', 'telefono'})

    def test_email_duplicado_sin_importar_mayusculas(self):
        detalles = self.detalles(self.api.post('/api/clientes/', {
            'nombre': 'Ana', 'apellidos': 'Otra', 'email': 'ANA@X.COM',
        }, format='json'))
        self.assertIn('email', detalles)

    def test_venta_sin_lineas_cantidad_invalida_y_stock(self):
        self.assertIn('detalles', self.detalles(self.api.post(
            '/api/ventas/', {'cliente': self.cliente.pk, 'detalles': []}, format='json')))
        self.assertIn('detalles', self.detalles(self.api.post(
            '/api/ventas/', {'cliente': self.cliente.pk, 'detalles': [{'libro': self.libro.pk, 'cantidad': 0}]},
            format='json')))
        detalles = self.detalles(self.api.post('/api/ventas/', {'cliente': self.cliente.pk, 'detalles': [
            {'libro': self.libro.pk, 'cantidad': 6}, {'libro': self.libro.pk, 'cantidad': 5},
        ]}, format='json'))
        self.assertIn('pediste 11 y solo hay 10', detalles['detalles'][0])
        self.assertFalse(Venta.objects.exists())

    def test_venta_con_fecha_futura(self):
        manana = (timezone.now() + timedelta(days=1)).isoformat()
        detalles = self.detalles(self.api.post('/api/ventas/', {
            'cliente': self.cliente.pk, 'fecha': manana, 'detalles': [{'libro': self.libro.pk, 'cantidad': 1}],
        }, format='json'))
        self.assertIn('fecha', detalles)

    def test_venta_valida_aplica_promocion_y_descuenta_stock(self):
        Promocion.objects.create(nombre='Hoy', descuento_porcentaje=25, fecha_inicio=self.hoy, fecha_fin=self.hoy)
        respuesta = self.api.post('/api/ventas/', {
            'cliente': self.cliente.pk, 'detalles': [{'libro': self.libro.pk, 'cantidad': 2}],
        }, format='json')
        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(respuesta.json()['total'], '300.00')
        self.assertEqual(respuesta.json()['detalles'][0]['promocion_nombre'], 'Hoy')
        self.libro.refresh_from_db()
        self.assertEqual(self.libro.stock_venta, 8)

    def test_promocion_con_fechas_invertidas_y_descuento_fuera_de_rango(self):
        detalles = self.detalles(self.api.post('/api/promociones/', {
            'nombre': 'Mala', 'descuento_porcentaje': '150',
            'fecha_inicio': str(self.hoy), 'fecha_fin': str(self.hoy - timedelta(days=1)),
        }, format='json'))
        self.assertIn('descuento_porcentaje', detalles)

    def test_devolver_y_pagar_dos_veces_es_conflicto(self):
        prestamo = Prestamo.objects.create(
            cliente=self.cliente, libro=self.libro,
            fecha_prestamo=self.hoy - timedelta(days=20), fecha_limite=self.hoy - timedelta(days=6),
        )
        respuesta = self.api.post(f'/api/prestamos/{prestamo.pk}/devolver/', {}, format='json')
        self.assertEqual(respuesta.json()['multa']['monto'], '60.00')
        self.assertError(self.api.post(f'/api/prestamos/{prestamo.pk}/devolver/', {}, format='json'), 409, 'conflicto')

        multa = Multa.objects.get()
        self.assertTrue(self.api.post(f'/api/multas/{multa.pk}/pagar/', {}, format='json').json()['pagada'])
        self.assertError(self.api.post(f'/api/multas/{multa.pk}/pagar/', {}, format='json'), 409, 'conflicto')

    def test_parametros_de_filtro_invalidos(self):
        self.assertIn('estado', self.detalles(self.api.get('/api/prestamos/?estado=todos')))
        self.assertIn('cliente', self.detalles(self.api.get('/api/prestamos/?cliente=abc')))
        self.assertIn('desde', self.detalles(self.api.get('/api/ventas/?desde=ayer')))


class InyeccionSqlTests(BaseApiTest):
    """Los intentos de inyección se tratan como texto o se rechazan; nunca se ejecutan."""

    CARGAS = [
        "' OR '1'='1",
        "'; DROP TABLE catalogo_libro; --",
        '1 OR 1=1',
        '" OR ""="',
        "1; DELETE FROM clientes_cliente",
        "%' UNION SELECT username, password FROM auth_user --",
    ]

    def setUp(self):
        super().setUp()
        self.como()

    def assertTablasIntactas(self):
        self.assertTrue(Libro.objects.filter(pk=self.libro.pk).exists())
        self.assertTrue(Cliente.objects.filter(pk=self.cliente.pk).exists())

    def test_busqueda(self):
        for carga in self.CARGAS:
            with self.subTest(carga=carga):
                respuesta = self.api.get('/api/libros/', {'q': carga})
                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(respuesta.json()['count'], 0)  # nada coincide con ese texto literal
        self.assertTablasIntactas()

    def test_filtros_numericos(self):
        for carga in self.CARGAS:
            with self.subTest(carga=carga):
                self.assertError(self.api.get('/api/libros/', {'categoria': carga}), 400, 'datos_invalidos')
                self.assertError(self.api.get('/api/prestamos/', {'cliente': carga}), 400, 'datos_invalidos')
        self.assertTablasIntactas()

    def test_ordenamiento_solo_acepta_campos_permitidos(self):
        for carga in [*self.CARGAS, 'password', 'categoria__nombre']:
            with self.subTest(carga=carga):
                respuesta = self.api.get('/api/libros/', {'orden': carga})
                self.assertEqual(respuesta.status_code, 200)  # se ignora el campo no permitido
                self.assertEqual(respuesta.json()['count'], 1)
        self.assertTablasIntactas()

    def test_id_en_la_ruta(self):
        for carga in ['1 OR 1=1', "1' --", '1;DROP TABLE x']:
            with self.subTest(carga=carga):
                self.assertError(self.api.get(f'/api/libros/{carga}/'), 404, 'no_encontrado')

    def test_texto_se_guarda_literal_sin_ejecutarse(self):
        carga = "Robert'); DROP TABLE catalogo_libro; --"
        respuesta = self.api.post('/api/libros/', {
            'isbn': '9780000000001', 'titulo': carga, 'autor': 'X', 'categoria': self.novela.pk,
            'precio_venta': '10',
        }, format='json')
        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(Libro.objects.get(isbn='9780000000001').titulo, carga)
        self.assertTablasIntactas()

    def test_nombre_de_cliente_rechaza_caracteres_de_sql(self):
        respuesta = self.api.post('/api/clientes/', {
            'nombre': "x'; DROP TABLE clientes_cliente; --", 'apellidos': 'Y', 'email': 'y@x.com',
        }, format='json')
        self.assertError(respuesta, 400, 'datos_invalidos')
        self.assertTablasIntactas()

    def test_login(self):
        self.empleado('Cajero')
        for carga in self.CARGAS[:4]:
            cache.clear()
            with self.subTest(carga=carga):
                respuesta = self.api.post('/api/auth/login/', {'username': carga, 'password': carga}, format='json')
                self.assertError(respuesta, 401, 'no_autenticado')
