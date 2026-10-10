from django.urls import path

from . import views

app_name = 'web'

urlpatterns = [
    path('', views.catalogo, name='catalogo'),
    path('panel/', views.panel, name='panel'),
    path('panel/ventas/', views.ventas_lista, name='ventas_lista'),
    path('panel/ventas/nueva/', views.venta_nueva, name='venta_nueva'),
    path('panel/ventas/<int:pk>/', views.venta_detalle, name='venta_detalle'),
    path('panel/prestamos/', views.prestamos_lista, name='prestamos_lista'),
    path('panel/prestamos/nuevo/', views.prestamo_nuevo, name='prestamo_nuevo'),
    path('panel/prestamos/<int:pk>/devolver/', views.prestamo_devolver, name='prestamo_devolver'),
    path('panel/multas/', views.multas_lista, name='multas_lista'),
    path('panel/multas/<int:pk>/pagar/', views.multa_pagar, name='multa_pagar'),
    path('panel/clientes/', views.clientes_lista, name='clientes_lista'),
    path('panel/clientes/nuevo/', views.cliente_nuevo, name='cliente_nuevo'),
    path('panel/clientes/<int:pk>/', views.cliente_detalle, name='cliente_detalle'),
    path('panel/clientes/<int:pk>/editar/', views.cliente_editar, name='cliente_editar'),
    path('panel/inventario/', views.inventario, name='inventario'),
    path('panel/promociones/', views.promociones, name='promociones'),
]
