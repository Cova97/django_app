from django.core.validators import RegexValidator
from django.db import models

validar_telefono = RegexValidator(r'^\d{10}$', 'El teléfono debe tener 10 dígitos.')
validar_nombre = RegexValidator(
    r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ' .-]+$",
    'Solo se permiten letras, espacios, puntos, guiones y apóstrofos.',
)


class Cliente(models.Model):
    nombre = models.CharField(max_length=100, validators=[validar_nombre])
    apellidos = models.CharField(max_length=150, validators=[validar_nombre])
    email = models.EmailField(unique=True)
    telefono = models.CharField('teléfono', max_length=10, blank=True, validators=[validar_telefono])
    fecha_registro = models.DateField('fecha de registro', auto_now_add=True)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['apellidos', 'nombre']

    def __str__(self):
        return f'{self.nombre} {self.apellidos}'

    def tiene_multas_pendientes(self):
        return self.prestamos.filter(multa__pagada=False).exists()
