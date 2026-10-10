from django.contrib import admin

from .models import Cliente


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'apellidos', 'email', 'telefono', 'activo', 'multas_pendientes']
    list_filter = ['activo']
    search_fields = ['nombre', 'apellidos', 'email']

    @admin.display(description='multas pendientes', boolean=True)
    def multas_pendientes(self, obj):
        return obj.tiene_multas_pendientes()
