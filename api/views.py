"""Vistas de la API.

Protección contra inyección SQL: aquí NO hay SQL escrito a mano. Todas las
consultas usan el ORM de Django, que envía los valores como parámetros
separados del SQL (nunca concatenados), y los parámetros de la URL se
convierten a su tipo (entero, opción válida) antes de usarse. Si algún día
se necesita SQL crudo, usar siempre parámetros: cursor.execute(sql, [valor]).
"""
from django.contrib.auth import authenticate
from django.db.models import Count, Prefetch, Q
from rest_framework import filters, mixins, serializers, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from catalogo.models import Categoria, Libro
from clientes.models import Cliente
from prestamos.models import Multa, Prestamo
from ventas.models import DetalleVenta, Promocion, Venta
from ventas.servicios import PromocionesVigentes

from . import serializers as s
from .errores import Conflicto
from .permisos import LecturaPublicaEscrituraEmpleados
from .validadores import parametro

ID = r'\d+'  # las rutas /recurso/<id>/ solo aceptan números


# --- Autenticación ---

class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, trim_whitespace=False)


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'  # limita intentos para frenar ataques de fuerza bruta

    def get_authenticate_header(self, request):
        return 'Token'  # sin esto DRF respondería 403 en vez de 401 al fallar el login

    def post(self, request):
        datos = LoginSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        usuario = authenticate(request, **datos.validated_data)
        if usuario is None or not usuario.is_active:
            # Mismo mensaje si falla el usuario o la contraseña: no revela cuál existe.
            raise AuthenticationFailed('Usuario o contraseña incorrectos.')
        # Cada login emite un token nuevo e invalida el anterior.
        Token.objects.filter(user=usuario).delete()
        token = Token.objects.create(user=usuario)
        return Response({'token': token.key, 'usuario': UsuarioActualView.datos(usuario)})


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class UsuarioActualView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def datos(usuario):
        return {
            'id': usuario.pk,
            'username': usuario.username,
            'es_empleado': usuario.is_staff,
            'grupos': list(usuario.groups.values_list('name', flat=True)),
        }

    def get(self, request):
        return Response(self.datos(request.user))


# --- Base ---

class BaseViewSet(viewsets.GenericViewSet):
    lookup_value_regex = ID
    permiso_accion = None  # ver permisos.EmpleadoConPermisos
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    ordering_fields = []  # lista blanca: ?orden= solo acepta estos campos


# --- Catálogo ---

class CategoriaViewSet(BaseViewSet, viewsets.ModelViewSet):
    queryset = Categoria.objects.all()
    serializer_class = s.CategoriaSerializer
    permission_classes = [LecturaPublicaEscrituraEmpleados]
    search_fields = ['nombre']
    ordering_fields = ['nombre']


class LibroViewSet(BaseViewSet, viewsets.ModelViewSet):
    serializer_class = s.LibroSerializer
    permission_classes = [LecturaPublicaEscrituraEmpleados]
    search_fields = ['titulo', 'autor', 'isbn']
    ordering_fields = ['titulo', 'autor', 'precio_venta', 'stock_venta']
    queryset = Libro.objects.all()

    def get_queryset(self):
        libros = Libro.objects.select_related('categoria').annotate(
            prestados=Count('prestamos', filter=Q(prestamos__fecha_devolucion__isnull=True))
        ).order_by('titulo')  # Count() ignora el orden por defecto del modelo
        categoria = parametro(self.request, 'categoria', serializers.IntegerField(min_value=1))
        if categoria:
            libros = libros.filter(categoria_id=categoria)
        if parametro(self.request, 'disponibles', serializers.BooleanField()):
            libros = libros.filter(stock_venta__gt=0)
        return libros

    def get_serializer_context(self):
        # Las promociones vigentes se cargan una sola vez para toda la página.
        return {**super().get_serializer_context(), 'promociones_vigentes': PromocionesVigentes()}


class PromocionViewSet(BaseViewSet, viewsets.ModelViewSet):
    serializer_class = s.PromocionSerializer
    permission_classes = [LecturaPublicaEscrituraEmpleados]
    search_fields = ['nombre']
    ordering_fields = ['fecha_inicio', 'descuento_porcentaje']
    queryset = Promocion.objects.all()

    def get_queryset(self):
        promociones = Promocion.objects.prefetch_related('libros', 'categorias')
        # El público solo ve las promociones vigentes; el personal ve todas.
        if not self.request.user.is_staff:
            return promociones.vigentes()
        if parametro(self.request, 'vigentes', serializers.BooleanField()):
            return promociones.vigentes()
        return promociones


# --- Clientes ---

class ClienteViewSet(BaseViewSet, viewsets.ModelViewSet):
    serializer_class = s.ClienteSerializer
    search_fields = ['nombre', 'apellidos', 'email']
    ordering_fields = ['apellidos', 'fecha_registro']
    queryset = Cliente.objects.all()

    def get_queryset(self):
        clientes = Cliente.objects.annotate(
            num_multas_pendientes=Count('prestamos__multa', filter=Q(prestamos__multa__pagada=False), distinct=True),
            num_prestamos_activos=Count('prestamos', filter=Q(prestamos__fecha_devolucion__isnull=True), distinct=True),
        ).order_by('apellidos', 'nombre')
        activo = parametro(self.request, 'activo', serializers.BooleanField())
        if activo is not None:
            clientes = clientes.filter(activo=activo)
        return clientes


# --- Ventas (una venta registrada no se modifica ni se borra) ---

class VentaViewSet(BaseViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin):
    serializer_class = s.VentaSerializer
    search_fields = ['cliente__nombre', 'cliente__apellidos']
    ordering_fields = ['fecha', 'total']
    queryset = Venta.objects.all()

    def get_queryset(self):
        ventas = Venta.objects.select_related('cliente').prefetch_related(
            Prefetch('detalles', DetalleVenta.objects.select_related('libro', 'promocion'))
        )
        cliente = parametro(self.request, 'cliente', serializers.IntegerField(min_value=1))
        if cliente:
            ventas = ventas.filter(cliente_id=cliente)
        desde = parametro(self.request, 'desde', serializers.DateField())
        if desde:
            ventas = ventas.filter(fecha__date__gte=desde)
        hasta = parametro(self.request, 'hasta', serializers.DateField())
        if hasta:
            ventas = ventas.filter(fecha__date__lte=hasta)
        return ventas

    def create(self, request, *args, **kwargs):
        datos = s.VentaCrearSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        venta = datos.save()
        return Response(s.VentaSerializer(self.get_queryset().get(pk=venta.pk)).data, status=201)


# --- Préstamos y multas ---

class PrestamoViewSet(BaseViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin):
    serializer_class = s.PrestamoSerializer
    search_fields = ['libro__titulo', 'cliente__nombre', 'cliente__apellidos']
    ordering_fields = ['fecha_prestamo', 'fecha_limite']
    queryset = Prestamo.objects.all()

    def get_queryset(self):
        prestamos = Prestamo.objects.select_related('cliente', 'libro', 'multa')
        estado = parametro(
            self.request, 'estado', serializers.ChoiceField(['activos', 'vencidos', 'devueltos'])
        )
        if estado == 'activos':
            prestamos = prestamos.activos()
        elif estado == 'vencidos':
            prestamos = prestamos.vencidos()
        elif estado == 'devueltos':
            prestamos = prestamos.filter(fecha_devolucion__isnull=False)
        cliente = parametro(self.request, 'cliente', serializers.IntegerField(min_value=1))
        if cliente:
            prestamos = prestamos.filter(cliente_id=cliente)
        return prestamos

    def create(self, request, *args, **kwargs):
        datos = s.PrestamoCrearSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        prestamo = datos.save()
        return Response(s.PrestamoSerializer(prestamo).data, status=201)

    @action(detail=True, methods=['post'], permiso_accion='change')
    def devolver(self, request, pk=None):
        prestamo = self.get_object()
        if not prestamo.activo:
            raise Conflicto('Este préstamo ya fue devuelto.')
        datos = s.FechaOpcionalSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        fecha = datos.validated_data.get('fecha')
        if fecha and fecha < prestamo.fecha_prestamo:
            raise serializers.ValidationError({'fecha': 'No puede ser anterior a la fecha del préstamo.'})
        prestamo.devolver(fecha)
        prestamo = self.get_queryset().get(pk=prestamo.pk)
        return Response(s.PrestamoSerializer(prestamo).data)


class MultaViewSet(BaseViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    serializer_class = s.MultaSerializer
    search_fields = ['prestamo__cliente__nombre', 'prestamo__cliente__apellidos']
    ordering_fields = ['fecha_generada', 'monto']
    queryset = Multa.objects.all()

    def get_queryset(self):
        multas = Multa.objects.select_related('prestamo__cliente')
        pagada = parametro(self.request, 'pagada', serializers.BooleanField())
        if pagada is not None:
            multas = multas.filter(pagada=pagada)
        cliente = parametro(self.request, 'cliente', serializers.IntegerField(min_value=1))
        if cliente:
            multas = multas.filter(prestamo__cliente_id=cliente)
        return multas

    @action(detail=True, methods=['post'], permiso_accion='change')
    def pagar(self, request, pk=None):
        multa = self.get_object()
        if multa.pagada:
            raise Conflicto('Esta multa ya fue pagada.')
        datos = s.FechaOpcionalSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        multa.pagar(datos.validated_data.get('fecha'))
        return Response(s.MultaSerializer(multa).data)
