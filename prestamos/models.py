from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from catalogo.models import Libro
from clientes.models import Cliente


def fecha_limite_por_defecto():
    return timezone.localdate() + timedelta(days=settings.LIBRERIA['DIAS_PRESTAMO'])


class PrestamoQuerySet(models.QuerySet):
    def activos(self):
        return self.filter(fecha_devolucion__isnull=True)

    def vencidos(self, hoy=None):
        hoy = hoy or timezone.localdate()
        return self.activos().filter(fecha_limite__lt=hoy)


class Prestamo(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='prestamos')
    libro = models.ForeignKey(Libro, on_delete=models.PROTECT, related_name='prestamos')
    fecha_prestamo = models.DateField('fecha de préstamo', default=timezone.localdate)
    fecha_limite = models.DateField('fecha límite', default=fecha_limite_por_defecto)
    fecha_devolucion = models.DateField('fecha de devolución', null=True, blank=True, editable=False)

    objects = PrestamoQuerySet.as_manager()

    class Meta:
        ordering = ['-fecha_prestamo']
        verbose_name = 'préstamo'
        verbose_name_plural = 'préstamos'

    def __str__(self):
        return f'{self.libro.titulo} -> {self.cliente}'

    @property
    def activo(self):
        return self.fecha_devolucion is None

    def dias_retraso(self, hasta=None):
        hasta = self.fecha_devolucion or hasta or timezone.localdate()
        return max((hasta - self.fecha_limite).days, 0)

    @property
    def vencido(self):
        return self.activo and self.dias_retraso() > 0

    def multa_estimada(self):
        return self.dias_retraso() * settings.LIBRERIA['MULTA_POR_DIA']

    def clean(self):
        if self.fecha_prestamo and self.fecha_limite and self.fecha_limite < self.fecha_prestamo:
            raise ValidationError({'fecha_limite': 'Debe ser posterior a la fecha de préstamo.'})

        if self.pk is not None:
            return

        if self.libro_id and self.libro.ejemplares_disponibles <= 0:
            raise ValidationError({'libro': 'No hay ejemplares disponibles para préstamo.'})

        if self.cliente_id:
            cliente = self.cliente
            maximo = settings.LIBRERIA['MAX_PRESTAMOS_ACTIVOS']
            if not cliente.activo:
                raise ValidationError({'cliente': 'El cliente está inactivo.'})
            if cliente.tiene_multas_pendientes():
                raise ValidationError({'cliente': 'El cliente tiene multas pendientes de pago.'})
            if cliente.prestamos.vencidos().exists():
                raise ValidationError({'cliente': 'El cliente tiene préstamos vencidos sin devolver.'})
            if cliente.prestamos.activos().count() >= maximo:
                raise ValidationError({'cliente': f'El cliente ya tiene {maximo} préstamos activos.'})

    @transaction.atomic
    def devolver(self, fecha=None):
        """Registra la devolución y genera la multa si hubo retraso. Regresa la multa o None."""
        if not self.activo:
            raise ValidationError('Este préstamo ya fue devuelto.')
        self.fecha_devolucion = fecha or timezone.localdate()
        self.save(update_fields=['fecha_devolucion'])

        dias = self.dias_retraso()
        if not dias:
            return None
        return Multa.objects.create(
            prestamo=self,
            dias_retraso=dias,
            monto=dias * settings.LIBRERIA['MULTA_POR_DIA'],
        )


class Multa(models.Model):
    prestamo = models.OneToOneField(
        Prestamo, on_delete=models.CASCADE, related_name='multa', verbose_name='préstamo'
    )
    dias_retraso = models.PositiveIntegerField('días de retraso')
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_generada = models.DateField(auto_now_add=True)
    pagada = models.BooleanField(default=False)
    fecha_pago = models.DateField('fecha de pago', null=True, blank=True)

    class Meta:
        ordering = ['pagada', '-fecha_generada']

    def __str__(self):
        return f'Multa ${self.monto} - {self.prestamo.cliente}'

    def pagar(self, fecha=None):
        self.pagada = True
        self.fecha_pago = fecha or timezone.localdate()
        self.save(update_fields=['pagada', 'fecha_pago'])
