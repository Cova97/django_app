from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('categorias', views.CategoriaViewSet, basename='categoria')
router.register('libros', views.LibroViewSet, basename='libro')
router.register('promociones', views.PromocionViewSet, basename='promocion')
router.register('clientes', views.ClienteViewSet, basename='cliente')
router.register('ventas', views.VentaViewSet, basename='venta')
router.register('prestamos', views.PrestamoViewSet, basename='prestamo')
router.register('multas', views.MultaViewSet, basename='multa')

urlpatterns = [
    path('auth/login/', views.LoginView.as_view(), name='login'),
    path('auth/logout/', views.LogoutView.as_view(), name='logout'),
    path('auth/yo/', views.UsuarioActualView.as_view(), name='usuario-actual'),
    *router.urls,
]
