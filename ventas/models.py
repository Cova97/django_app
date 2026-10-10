from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone

from catalogo.models import Categoria, Libro
from clientes.models import Cliente


class PromocionQuerySet(models.QuerySet):
    def vigentes(self, fecha=None):
        fecha = fecha or timezone.localdate()
        return self.filter(activa=True, fecha_inicio__lte=fecha, fecha_fin__gte=fecha)

    def aplicables_a(self, libro):
        # Sin libros ni categorías elegidos, la promoción aplica a todo el catálogo.
        general = Q(libros__isnull=True, categorias__isnull=True)
        return self.filter(
            general | Q(libros=libro) | Q(categorias=libro.categoria_id)
        ).distinct()

    def mejor_para(self, libro, fecha=None):
        """La promoción vigente con mayor descuento para el libro, o None."""
        return (
            self.vigentes(fecha).aplicables_a(libro).order_by('-descuento_porcentaje').first()
        )


class Promocion(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField('descripción', blank=True)
    descuento_porcentaje = models.DecimalField(
        'descuento (%)', max_digits=5, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01')), MaxValueValidator(100)],
    )
    fecha_inicio = models.DateField('inicio de temporada')
    fecha_fin = models.DateField('fin de temporada')
    activa = models.BooleanField(default=True)
    libros = models.ManyToManyField(
        Libro, blank=True, related_name='promociones',
        help_text='Déjalo vacío junto con categorías para aplicar a todo el catálogo.',
    )
    categorias = models.ManyToManyField(
        Categoria, blank=True, related_name='promociones', verbose_name='categorías'
    )

    objects = PromocionQuerySet.as_manager()

    class Meta:
        ordering = ['-fecha_inicio']
        verbose_name = 'promoción'
        verbose_name_plural = 'promociones'

    def __str__(self):
        return f'{self.nombre} (-{self.descuento_porcentaje}%)'

    def clean(self):
        if self.fecha_inicio and self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValidationError({'fecha_fin': 'La temporada no puede terminar antes de empezar.'})

    def esta_vigente(self, fecha=None):
        fecha = fecha or timezone.localdate()
        return self.activa and self.fecha_inicio <= fecha <= self.fecha_fin


class Venta(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='compras')
    fecha = models.DateTimeField(default=timezone.now)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)

    class Meta:
        ordering = ['-fecha']

    def __str__(self):
        return f'Venta #{self.pk} - {self.cliente}'

    def recalcular_total(self):
        self.total = sum((d.subtotal for d in self.detalles.all()), Decimal('0.00'))
        self.save(update_fields=['total'])


class DetalleVenta(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name='detalles')
    libro = models.ForeignKey(Libro, on_delete=models.PROTECT, related_name='ventas')
    cantidad = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    # Se congelan al vender para que el historial no cambie si después cambia el precio.
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    descuento_porcentaje = models.DecimalField(
        'descuento (%)', max_digits=5, decimal_places=2, default=0, editable=False
    )
    promocion = models.ForeignKey(
        Promocion, on_delete=models.SET_NULL, null=True, blank=True, editable=False,
        verbose_name='promoción',
    )

    class Meta:
        verbose_name = 'detalle de venta'
        verbose_name_plural = 'detalles de venta'

    def __str__(self):
        return f'{self.cantidad} x {self.libro}'

    @property
    def subtotal(self):
        if self.precio_unitario is None:  # línea aún sin guardar
            return None
        bruto = self.precio_unitario * self.cantidad
        neto = bruto * (Decimal('100') - self.descuento_porcentaje) / Decimal('100')
        return neto.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def clean(self):
        if self.pk is None and self.libro_id and self.cantidad:
            if self.cantidad > self.libro.stock_venta:
                raise ValidationError(
                    {'cantidad': f'Solo hay {self.libro.stock_venta} unidades en stock.'}
                )

    def save(self, *args, **kwargs):
        if self.pk is not None:
            return super().save(*args, **kwargs)

        promo = Promocion.objects.mejor_para(self.libro, timezone.localdate(self.venta.fecha))
        self.precio_unitario = self.libro.precio_venta
        self.promocion = promo
        self.descuento_porcentaje = promo.descuento_porcentaje if promo else Decimal('0')

        with transaction.atomic():
            # Descuento atómico: si otra venta se llevó el stock, no se actualiza nada.
            actualizados = Libro.objects.filter(
                pk=self.libro_id, stock_venta__gte=self.cantidad
            ).update(stock_venta=F('stock_venta') - self.cantidad)
            if not actualizados:
                raise ValidationError(f'Stock insuficiente para "{self.libro}".')
            super().save(*args, **kwargs)
