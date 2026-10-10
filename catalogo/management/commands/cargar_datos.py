"""Carga datos de ejemplo pasando por la lógica de negocio (stock, promociones y multas).

Uso:
    python manage.py cargar_datos           # solo si la base no tiene datos
    python manage.py cargar_datos --borrar  # borra los datos del negocio y vuelve a cargar
"""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from catalogo.models import Categoria, Libro
from clientes.models import Cliente
from prestamos.models import Multa, Prestamo
from ventas.models import DetalleVenta, Promocion, Venta

CATEGORIAS = ['Novela', 'Infantil', 'Ciencia', 'Historia', 'Poesía']

# (isbn, título, autor, categoría, precio, stock venta, ejemplares préstamo)
LIBROS = [
    ('9780307474728', 'Cien años de soledad', 'Gabriel García Márquez', 'Novela', '389.00', 12, 3),
    ('9788437604572', 'Rayuela', 'Julio Cortázar', 'Novela', '345.00', 8, 2),
    ('9786071613158', 'Pedro Páramo', 'Juan Rulfo', 'Novela', '199.00', 15, 3),
    ('9788420471839', 'Don Quijote de la Mancha', 'Miguel de Cervantes', 'Novela', '499.00', 6, 2),
    ('9786073193566', 'La casa de los espíritus', 'Isabel Allende', 'Novela', '329.00', 9, 2),
    ('9786070731358', 'El principito', 'Antoine de Saint-Exupéry', 'Infantil', '159.00', 20, 4),
    ('9788498386356', 'Harry Potter y la piedra filosofal', 'J. K. Rowling', 'Infantil', '359.00', 14, 3),
    ('9786073140096', 'Matilda', 'Roald Dahl', 'Infantil', '229.00', 10, 2),
    ('9788420651804', 'Breve historia del tiempo', 'Stephen Hawking', 'Ciencia', '289.00', 7, 2),
    ('9786073180474', 'Cosmos', 'Carl Sagan', 'Ciencia', '399.00', 5, 1),
    ('9786073157889', 'Sapiens', 'Yuval Noah Harari', 'Historia', '419.00', 10, 2),
    ('9786071607324', 'Visión de los vencidos', 'Miguel León-Portilla', 'Historia', '179.00', 8, 2),
    ('9788437607955', 'Veinte poemas de amor', 'Pablo Neruda', 'Poesía', '149.00', 11, 2),
    ('9786071635563', 'Piedra de sol', 'Octavio Paz', 'Poesía', '139.00', 6, 1),
]

# (nombre, apellidos, email, teléfono, activo)
CLIENTES = [
    ('Ana', 'López García', 'ana.lopez@example.com', '5512345678', True),
    ('Luis', 'Pérez Hernández', 'luis.perez@example.com', '5523456789', True),
    ('María', 'Rodríguez Torres', 'maria.rodriguez@example.com', '5534567890', True),
    ('Jorge', 'Martínez Ruiz', 'jorge.martinez@example.com', '5545678901', True),
    ('Sofía', 'Hernández Díaz', 'sofia.hernandez@example.com', '5556789012', True),
    ('Carmen', 'Gómez Flores', 'carmen.gomez@example.com', '5567890123', True),
    ('Ricardo', 'Sánchez Morales', 'ricardo.sanchez@example.com', '5578901234', True),
    ('Elena', 'Ramírez Castro', 'elena.ramirez@example.com', '', False),
]


class Command(BaseCommand):
    help = 'Carga libros, clientes, promociones, ventas, préstamos y multas de ejemplo.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--borrar', action='store_true',
            help='Borra los datos del negocio (no los usuarios) antes de cargar.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        modelos = [Multa, Prestamo, DetalleVenta, Venta, Promocion, Cliente, Libro, Categoria]
        if options['borrar']:
            for modelo in modelos:
                modelo.objects.all().delete()
        elif any(modelo.objects.exists() for modelo in modelos):
            raise CommandError('La base ya tiene datos. Usa --borrar para reemplazarlos.')

        self.hoy = timezone.localdate()
        self.cargar_catalogo()
        self.cargar_clientes()
        self.cargar_promociones()
        self.cargar_ventas()
        self.cargar_prestamos()

        self.stdout.write(self.style.SUCCESS('Datos de ejemplo cargados:'))
        for modelo in reversed(modelos):
            self.stdout.write(f'  {modelo._meta.verbose_name_plural}: {modelo.objects.count()}')

    def dia(self, dias):
        return self.hoy + timedelta(days=dias)

    def cargar_catalogo(self):
        categorias = {nombre: Categoria.objects.create(nombre=nombre) for nombre in CATEGORIAS}
        self.libros = {}
        for isbn, titulo, autor, categoria, precio, stock, ejemplares in LIBROS:
            self.libros[titulo] = Libro.objects.create(
                isbn=isbn, titulo=titulo, autor=autor, categoria=categorias[categoria],
                precio_venta=Decimal(precio), stock_venta=stock, ejemplares_prestamo=ejemplares,
            )
        self.categorias = categorias

    def cargar_clientes(self):
        self.clientes = {}
        for nombre, apellidos, email, telefono, activo in CLIENTES:
            self.clientes[nombre] = Cliente.objects.create(
                nombre=nombre, apellidos=apellidos, email=email, telefono=telefono, activo=activo,
            )

    def cargar_promociones(self):
        regreso = Promocion.objects.create(
            nombre='Regreso a clases', descuento_porcentaje=Decimal('15'),
            descripcion='15% en libros infantiles.',
            fecha_inicio=self.dia(-70), fecha_fin=self.dia(-40),
        )
        regreso.categorias.add(self.categorias['Infantil'])

        Promocion.objects.create(
            nombre='Mes de la lectura', descuento_porcentaje=Decimal('10'),
            descripcion='10% en todo el catálogo.',
            fecha_inicio=self.dia(-9), fecha_fin=self.dia(20),
        )

        clasicos = Promocion.objects.create(
            nombre='Semana de los clásicos', descuento_porcentaje=Decimal('25'),
            descripcion='25% en clásicos seleccionados.',
            fecha_inicio=self.dia(-5), fecha_fin=self.dia(5),
        )
        clasicos.libros.add(self.libros['Don Quijote de la Mancha'], self.libros['Pedro Páramo'])

        Promocion.objects.create(
            nombre='Buen Fin', descuento_porcentaje=Decimal('20'),
            descripcion='20% en todo el catálogo.',
            fecha_inicio=self.dia(35), fecha_fin=self.dia(38),
        )

        navidad = Promocion.objects.create(
            nombre='Navidad', descuento_porcentaje=Decimal('30'),
            descripcion='30% en libros infantiles y poesía.',
            fecha_inicio=self.dia(55), fecha_fin=self.dia(75),
        )
        navidad.categorias.add(self.categorias['Infantil'], self.categorias['Poesía'])

        Promocion.objects.create(
            nombre='Liquidación (cancelada)', descuento_porcentaje=Decimal('50'),
            descripcion='Promoción desactivada: no debe aplicarse.',
            fecha_inicio=self.dia(-3), fecha_fin=self.dia(3), activa=False,
        )

    def vender(self, cliente, dias, hora, lineas):
        fecha = timezone.make_aware(datetime.combine(self.dia(dias), time(hora)))
        venta = Venta.objects.create(cliente=self.clientes[cliente], fecha=fecha)
        for titulo, cantidad in lineas:
            DetalleVenta.objects.create(venta=venta, libro=self.libros[titulo], cantidad=cantidad)
        venta.recalcular_total()

    def cargar_ventas(self):
        # Antes de cualquier promoción: precio completo.
        self.vender('María', -85, 11, [('Cien años de soledad', 1), ('Sapiens', 1)])
        self.vender('Ricardo', -80, 17, [('Cosmos', 1)])
        # Durante "Regreso a clases": 15% solo en infantiles.
        self.vender('Sofía', -65, 10, [('El principito', 2), ('Matilda', 1), ('Rayuela', 1)])
        self.vender('Carmen', -50, 13, [('Harry Potter y la piedra filosofal', 3)])
        self.vender('Jorge', -45, 16, [('El principito', 1), ('Breve historia del tiempo', 1)])
        # Entre temporadas: precio completo.
        self.vender('Ana', -25, 12, [('Veinte poemas de amor', 2), ('Piedra de sol', 1)])
        self.vender('Luis', -15, 18, [('La casa de los espíritus', 1)])
        # "Mes de la lectura" (10%) + "Semana de los clásicos" (25%) a la vez: gana la mayor.
        self.vender('Ana', -4, 11, [('Don Quijote de la Mancha', 1), ('Pedro Páramo', 2)])
        self.vender('María', -2, 15, [('Visión de los vencidos', 1), ('Pedro Páramo', 1)])
        self.vender('Ricardo', -1, 10, [('Sapiens', 2), ('Cien años de soledad', 1)])
        self.vender('Carmen', 0, 9, [('Matilda', 1), ('El principito', 1)])

    def prestar(self, cliente, titulo, dias_desde_prestamo):
        inicio = self.dia(-dias_desde_prestamo)
        return Prestamo.objects.create(
            cliente=self.clientes[cliente], libro=self.libros[titulo], fecha_prestamo=inicio,
            fecha_limite=inicio + timedelta(days=settings.LIBRERIA['DIAS_PRESTAMO']),
        )

    def cargar_prestamos(self):
        # Devuelto a tiempo.
        self.prestar('María', 'Rayuela', 40).devolver(self.dia(-30))
        self.prestar('Ana', 'Breve historia del tiempo', 25).devolver(self.dia(-11))
        # Devuelto tarde, multa ya pagada.
        multa = self.prestar('Sofía', 'Harry Potter y la piedra filosofal', 50).devolver(self.dia(-34))
        multa.pagar(self.dia(-30))
        # Devuelto tarde, multa pendiente (Jorge queda bloqueado para nuevos préstamos).
        self.prestar('Jorge', 'Pedro Páramo', 35).devolver(self.dia(-16))
        # Activos a tiempo.
        self.prestar('Ana', 'Cien años de soledad', 3)
        self.prestar('Carmen', 'Sapiens', 10)
        self.prestar('Ricardo', 'Cosmos', 1)
        # Activos vencidos (Luis y María deben devolver y pagarán multa).
        self.prestar('Luis', 'El principito', 20)
        self.prestar('María', 'Matilda', 18)
