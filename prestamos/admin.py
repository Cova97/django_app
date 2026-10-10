from django.contrib import admin, messages
from django.utils import timezone

from .models import Multa, Prestamo


class EstadoPrestamoFilter(admin.SimpleListFilter):
    title = 'estado'
    parameter_name = 'estado'

    def lookups(self, request, model_admin):
        return [('activos', 'Activos'), ('vencidos', 'Vencidos'), ('devueltos', 'Devueltos')]

    def queryset(self, request, queryset):
        if self.value() == 'activos':
            return queryset.activos()
        if self.value() == 'vencidos':
            return queryset.vencidos()
        if self.value() == 'devueltos':
            return queryset.filter(fecha_devolucion__isnull=False)
        return queryset


@admin.register(Prestamo)
class PrestamoAdmin(admin.ModelAdmin):
    list_display = [
        'libro', 'cliente', 'fecha_prestamo', 'fecha_limite', 'fecha_devolucion',
        'estado', 'retraso', 'multa_info',
    ]
    list_filter = [EstadoPrestamoFilter, 'fecha_prestamo']
    search_fields = ['libro__titulo', 'cliente__nombre', 'cliente__apellidos']
    autocomplete_fields = ['cliente', 'libro']
    readonly_fields = ['fecha_devolucion']
    actions = ['registrar_devolucion']

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ['cliente', 'libro', 'fecha_prestamo', 'fecha_devolucion']
        return self.readonly_fields

    @admin.display(description='estado')
    def estado(self, obj):
        if not obj.activo:
            return 'Devuelto'
        return 'VENCIDO' if obj.vencido else 'Activo'

    @admin.display(description='días de retraso')
    def retraso(self, obj):
        return obj.dias_retraso()

    # No se llama "multa" porque el admin usaría la relación Prestamo.multa en su lugar.
    @admin.display(description='multa')
    def multa_info(self, obj):
        if hasattr(obj, 'multa'):
            return f'${obj.multa.monto} ({"pagada" if obj.multa.pagada else "pendiente"})'
        if obj.vencido:
            return f'${obj.multa_estimada()} (estimada)'
        return '-'

    @admin.action(description='Registrar devolución (hoy)')
    def registrar_devolucion(self, request, queryset):
        devueltos, multas = 0, 0
        for prestamo in queryset.activos():
            if prestamo.devolver(timezone.localdate()):
                multas += 1
            devueltos += 1
        self.message_user(
            request,
            f'{devueltos} préstamo(s) devuelto(s), {multas} multa(s) generada(s).',
            messages.WARNING if multas else messages.SUCCESS,
        )


@admin.register(Multa)
class MultaAdmin(admin.ModelAdmin):
    list_display = ['prestamo', 'cliente', 'dias_retraso', 'monto', 'pagada', 'fecha_pago']
    list_filter = ['pagada']
    search_fields = ['prestamo__cliente__nombre', 'prestamo__cliente__apellidos']
    readonly_fields = ['prestamo', 'dias_retraso', 'monto', 'fecha_generada']
    actions = ['marcar_pagadas']

    def has_add_permission(self, request):
        # Las multas solo se generan al devolver un préstamo con retraso.
        return False

    @admin.display(description='cliente')
    def cliente(self, obj):
        return obj.prestamo.cliente

    @admin.action(description='Marcar como pagadas (hoy)')
    def marcar_pagadas(self, request, queryset):
        pendientes = queryset.filter(pagada=False)
        for multa in pendientes:
            multa.pagar()
        self.message_user(request, f'{len(pendientes)} multa(s) marcadas como pagadas.')
