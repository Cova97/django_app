from collections import Counter

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from .models import DetalleVenta, Promocion, Venta


@admin.register(Promocion)
class PromocionAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'descuento_porcentaje', 'fecha_inicio', 'fecha_fin', 'activa', 'vigente']
    list_filter = ['activa']
    search_fields = ['nombre']
    filter_horizontal = ['libros', 'categorias']

    @admin.display(boolean=True, description='vigente hoy')
    def vigente(self, obj):
        return obj.esta_vigente()


class DetalleVentaFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        # Valida el stock sumando todas las líneas del mismo libro.
        cantidades = Counter()
        libros = {}
        for form in self.forms:
            datos = getattr(form, 'cleaned_data', None)
            if not datos or datos.get('DELETE') or not datos.get('libro'):
                continue
            libro = datos['libro']
            cantidades[libro.pk] += datos.get('cantidad') or 0
            libros[libro.pk] = libro
        for pk, cantidad in cantidades.items():
            if cantidad > libros[pk].stock_venta:
                raise ValidationError(
                    f'"{libros[pk]}": pediste {cantidad} y solo hay {libros[pk].stock_venta} en stock.'
                )


class DetalleVentaInline(admin.TabularInline):
    model = DetalleVenta
    formset = DetalleVentaFormSet
    extra = 1
    autocomplete_fields = ['libro']
    readonly_fields = ['precio_unitario', 'descuento_porcentaje', 'promocion', 'subtotal']

    # Una venta registrada no se modifica: sus líneas quedan de solo lectura.
    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ['libro', 'cantidad', *self.readonly_fields]
        return self.readonly_fields

    def get_extra(self, request, obj=None, **kwargs):
        return 0 if obj else self.extra

    def has_add_permission(self, request, obj=None):
        return obj is None

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Venta)
class VentaAdmin(admin.ModelAdmin):
    list_display = ['id', 'cliente', 'fecha', 'total']
    list_filter = ['fecha']
    search_fields = ['cliente__nombre', 'cliente__apellidos']
    autocomplete_fields = ['cliente']
    readonly_fields = ['total']
    inlines = [DetalleVentaInline]
    date_hierarchy = 'fecha'

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ['cliente', 'fecha', 'total']
        return self.readonly_fields

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.recalcular_total()
