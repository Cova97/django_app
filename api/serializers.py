from decimal import Decimal

from rest_framework import serializers

from catalogo.models import Categoria, Libro
from clientes.models import Cliente
from prestamos.models import Multa, Prestamo
from ventas.models import DetalleVenta, Promocion, Venta
from ventas.servicios import PromocionesVigentes, errores_de_stock, registrar_venta

from .validadores import no_futura, nombre_persona, texto_seguro

MAX_LINEAS_VENTA = 50
MAX_CANTIDAD_LINEA = 100


# --- Catálogo ---

class CategoriaSerializer(serializers.ModelSerializer):
    nombre = serializers.CharField(max_length=100, validators=[texto_seguro])

    class Meta:
        model = Categoria
        fields = ['id', 'nombre']

    def validate_nombre(self, valor):
        repetidas = Categoria.objects.filter(nombre__iexact=valor)
        if self.instance:
            repetidas = repetidas.exclude(pk=self.instance.pk)
        if repetidas.exists():
            raise serializers.ValidationError('Ya existe una categoría con ese nombre.')
        return valor


class PromocionResumenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Promocion
        fields = ['id', 'nombre', 'descuento_porcentaje', 'fecha_fin']


class LibroSerializer(serializers.ModelSerializer):
    titulo = serializers.CharField(max_length=200, validators=[texto_seguro])
    autor = serializers.CharField(max_length=200, validators=[texto_seguro])
    categoria_nombre = serializers.CharField(source='categoria.nombre', read_only=True)
    ejemplares_disponibles = serializers.SerializerMethodField()
    promocion_vigente = serializers.SerializerMethodField()
    precio_con_descuento = serializers.SerializerMethodField()

    class Meta:
        model = Libro
        fields = [
            'id', 'isbn', 'titulo', 'autor', 'categoria', 'categoria_nombre',
            'precio_venta', 'precio_con_descuento', 'promocion_vigente',
            'stock_venta', 'ejemplares_prestamo', 'ejemplares_disponibles',
        ]
        extra_kwargs = {'precio_venta': {'max_value': Decimal('99999.99')}}

    def get_ejemplares_disponibles(self, libro):
        prestados = getattr(libro, 'prestados', None)  # anotado en la vista, evita N consultas
        if prestados is None:
            return libro.ejemplares_disponibles
        return libro.ejemplares_prestamo - prestados

    def _promociones(self):
        if 'promociones_vigentes' not in self.context:
            self.context['promociones_vigentes'] = PromocionesVigentes()
        return self.context['promociones_vigentes']

    def get_promocion_vigente(self, libro):
        promo = self._promociones().para(libro)
        return PromocionResumenSerializer(promo).data if promo else None

    def get_precio_con_descuento(self, libro):
        return str(self._promociones().precio_final(libro))

    def validate_ejemplares_prestamo(self, valor):
        if self.instance:
            prestados = self.instance.prestamos.activos().count()
            if valor < prestados:
                raise serializers.ValidationError(
                    f'Hay {prestados} ejemplares prestados; no puede ser menor a eso.'
                )
        return valor


class PromocionSerializer(serializers.ModelSerializer):
    nombre = serializers.CharField(max_length=100, validators=[texto_seguro])
    descripcion = serializers.CharField(
        max_length=1000, required=False, allow_blank=True, validators=[texto_seguro]
    )
    vigente = serializers.SerializerMethodField()

    class Meta:
        model = Promocion
        fields = [
            'id', 'nombre', 'descripcion', 'descuento_porcentaje', 'fecha_inicio', 'fecha_fin',
            'activa', 'vigente', 'libros', 'categorias',
        ]

    def get_vigente(self, promo):
        return promo.esta_vigente()

    def validate(self, datos):
        inicio = datos.get('fecha_inicio', getattr(self.instance, 'fecha_inicio', None))
        fin = datos.get('fecha_fin', getattr(self.instance, 'fecha_fin', None))
        if inicio and fin and fin < inicio:
            raise serializers.ValidationError({'fecha_fin': 'La temporada no puede terminar antes de empezar.'})
        return datos


# --- Clientes ---

class ClienteSerializer(serializers.ModelSerializer):
    nombre = serializers.CharField(max_length=100, validators=[nombre_persona])
    apellidos = serializers.CharField(max_length=150, validators=[nombre_persona])
    multas_pendientes = serializers.SerializerMethodField()
    prestamos_activos = serializers.SerializerMethodField()

    class Meta:
        model = Cliente
        fields = [
            'id', 'nombre', 'apellidos', 'email', 'telefono', 'activo', 'fecha_registro',
            'multas_pendientes', 'prestamos_activos',
        ]
        read_only_fields = ['fecha_registro']

    def get_multas_pendientes(self, cliente):
        valor = getattr(cliente, 'num_multas_pendientes', None)
        return cliente.tiene_multas_pendientes() if valor is None else valor > 0

    def get_prestamos_activos(self, cliente):
        valor = getattr(cliente, 'num_prestamos_activos', None)
        return cliente.prestamos.activos().count() if valor is None else valor

    def validate_email(self, valor):
        valor = valor.lower()
        repetidos = Cliente.objects.filter(email__iexact=valor)
        if self.instance:
            repetidos = repetidos.exclude(pk=self.instance.pk)
        if repetidos.exists():
            raise serializers.ValidationError('Ya existe un cliente con ese email.')
        return valor


# --- Ventas ---

class DetalleVentaSerializer(serializers.ModelSerializer):
    libro_titulo = serializers.CharField(source='libro.titulo', read_only=True)
    promocion_nombre = serializers.CharField(source='promocion.nombre', read_only=True, default=None)
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = DetalleVenta
        fields = [
            'libro', 'libro_titulo', 'cantidad', 'precio_unitario', 'descuento_porcentaje',
            'promocion', 'promocion_nombre', 'subtotal',
        ]


class VentaSerializer(serializers.ModelSerializer):
    cliente_nombre = serializers.CharField(source='cliente.__str__', read_only=True)
    detalles = DetalleVentaSerializer(many=True, read_only=True)

    class Meta:
        model = Venta
        fields = ['id', 'cliente', 'cliente_nombre', 'fecha', 'total', 'detalles']


class LineaVentaSerializer(serializers.Serializer):
    libro = serializers.PrimaryKeyRelatedField(queryset=Libro.objects.all())
    cantidad = serializers.IntegerField(min_value=1, max_value=MAX_CANTIDAD_LINEA)


class VentaCrearSerializer(serializers.Serializer):
    cliente = serializers.PrimaryKeyRelatedField(queryset=Cliente.objects.all())
    fecha = serializers.DateTimeField(required=False, validators=[no_futura])
    detalles = LineaVentaSerializer(many=True, allow_empty=False, max_length=MAX_LINEAS_VENTA)

    def validate_detalles(self, lineas):
        errores = errores_de_stock([(linea['libro'], linea['cantidad']) for linea in lineas])
        if errores:
            raise serializers.ValidationError(errores)
        return lineas

    def create(self, datos):
        lineas = [(linea['libro'], linea['cantidad']) for linea in datos['detalles']]
        return registrar_venta(datos['cliente'], lineas, datos.get('fecha'))


# --- Préstamos y multas ---

class MultaSerializer(serializers.ModelSerializer):
    cliente = serializers.IntegerField(source='prestamo.cliente_id', read_only=True)
    cliente_nombre = serializers.CharField(source='prestamo.cliente.__str__', read_only=True)

    class Meta:
        model = Multa
        fields = [
            'id', 'prestamo', 'cliente', 'cliente_nombre', 'dias_retraso', 'monto',
            'fecha_generada', 'pagada', 'fecha_pago',
        ]
        read_only_fields = fields


class PrestamoSerializer(serializers.ModelSerializer):
    cliente_nombre = serializers.CharField(source='cliente.__str__', read_only=True)
    libro_titulo = serializers.CharField(source='libro.titulo', read_only=True)
    estado = serializers.SerializerMethodField()
    dias_retraso = serializers.SerializerMethodField()
    multa_estimada = serializers.SerializerMethodField()
    multa = serializers.SerializerMethodField()

    class Meta:
        model = Prestamo
        fields = [
            'id', 'cliente', 'cliente_nombre', 'libro', 'libro_titulo', 'fecha_prestamo',
            'fecha_limite', 'fecha_devolucion', 'estado', 'dias_retraso', 'multa_estimada', 'multa',
        ]
        read_only_fields = ['fecha_devolucion']

    def get_estado(self, prestamo):
        if not prestamo.activo:
            return 'devuelto'
        return 'vencido' if prestamo.vencido else 'activo'

    def get_dias_retraso(self, prestamo):
        return prestamo.dias_retraso()

    def get_multa_estimada(self, prestamo):
        return str(prestamo.multa_estimada()) if prestamo.vencido else None

    def get_multa(self, prestamo):
        multa = getattr(prestamo, 'multa', None)
        return {'id': multa.pk, 'monto': str(multa.monto), 'pagada': multa.pagada} if multa else None


class PrestamoCrearSerializer(serializers.ModelSerializer):
    fecha_prestamo = serializers.DateField(required=False, validators=[no_futura])
    fecha_limite = serializers.DateField(required=False)

    class Meta:
        model = Prestamo
        fields = ['cliente', 'libro', 'fecha_prestamo', 'fecha_limite']

    def create(self, datos):
        prestamo = Prestamo(**datos)
        prestamo.full_clean()  # reglas del modelo: ejemplares, multas, vencidos, límite
        prestamo.save()
        return prestamo


class FechaOpcionalSerializer(serializers.Serializer):
    fecha = serializers.DateField(required=False, validators=[no_futura])
