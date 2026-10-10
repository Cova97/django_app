from django.contrib import admin

from .models import Categoria, Libro


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    search_fields = ['nombre']


@admin.register(Libro)
class LibroAdmin(admin.ModelAdmin):
    list_display = [
        'titulo', 'autor', 'categoria', 'precio_venta',
        'stock_venta', 'ejemplares_prestamo', 'disponibles_prestamo',
    ]
    list_filter = ['categoria']
    search_fields = ['titulo', 'autor', 'isbn']

    @admin.display(description='disponibles para préstamo')
    def disponibles_prestamo(self, obj):
        return obj.ejemplares_disponibles
