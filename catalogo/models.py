from django.core.validators import MinValueValidator, RegexValidator
from django.db import models

validar_isbn = RegexValidator(r'^\d{10}(\d{3})?$', 'El ISBN debe tener 10 o 13 dígitos, sin guiones.')


class Categoria(models.Model):
    nombre = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'categoría'
        verbose_name_plural = 'categorías'

    def __str__(self):
        return self.nombre


class Libro(models.Model):
    isbn = models.CharField('ISBN', max_length=13, unique=True, validators=[validar_isbn])
    titulo = models.CharField('título', max_length=200)
    autor = models.CharField(max_length=200)
    categoria = models.ForeignKey(
        Categoria, on_delete=models.PROTECT, related_name='libros', verbose_name='categoría'
    )
    precio_venta = models.DecimalField(
        'precio de venta', max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )
    stock_venta = models.PositiveIntegerField(
        'stock para venta', default=0, help_text='Unidades disponibles para vender.'
    )
    ejemplares_prestamo = models.PositiveIntegerField(
        'ejemplares para préstamo', default=0,
        help_text='Total de ejemplares destinados a préstamo (se presten o no).',
    )

    class Meta:
        ordering = ['titulo']

    def __str__(self):
        return f'{self.titulo} ({self.autor})'

    @property
    def ejemplares_disponibles(self):
        """Ejemplares de préstamo que están en la librería ahora mismo."""
        prestados = self.prestamos.filter(fecha_devolucion__isnull=True).count()
        return self.ejemplares_prestamo - prestados
