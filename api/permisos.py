from rest_framework.permissions import SAFE_METHODS, DjangoModelPermissions


class EmpleadoConPermisos(DjangoModelPermissions):
    """Solo personal (is_staff) con el permiso del modelo correspondiente.

    Los permisos son los mismos del admin de Django (ver/añadir/modificar/borrar),
    así que se administran asignando grupos a los usuarios (ver `crear_roles`).
    Una acción puede pedir otro permiso con `permiso_accion`, por ejemplo
    "devolver" un préstamo requiere `change_prestamo` aunque sea un POST.
    """

    perms_map = {
        **DjangoModelPermissions.perms_map,
        'GET': ['%(app_label)s.view_%(model_name)s'],
        'HEAD': ['%(app_label)s.view_%(model_name)s'],
    }

    def has_permission(self, request, view):
        usuario = request.user
        if not (usuario and usuario.is_authenticated and usuario.is_staff):
            return False
        accion = getattr(view, 'permiso_accion', None)
        if accion:
            modelo = self._queryset(view).model._meta
            return usuario.has_perm(f'{modelo.app_label}.{accion}_{modelo.model_name}')
        return super().has_permission(request, view)


class LecturaPublicaEscrituraEmpleados(EmpleadoConPermisos):
    """El catálogo se puede consultar sin sesión; modificarlo requiere permisos."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return super().has_permission(request, view)
