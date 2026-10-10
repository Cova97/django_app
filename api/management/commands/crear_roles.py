"""Crea (o actualiza) los grupos de empleados con sus permisos.

Uso: python manage.py crear_roles
Después, en el admin: Usuarios -> marcar "Es staff" y asignar el grupo.
"""
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

ROLES = {
    'Cajero': {
        'catalogo': {'categoria': ['view'], 'libro': ['view']},
        'clientes': {'cliente': ['view', 'add', 'change']},
        'ventas': {'promocion': ['view'], 'venta': ['view', 'add'], 'detalleventa': ['view', 'add']},
    },
    'Bibliotecario': {
        'catalogo': {'categoria': ['view'], 'libro': ['view']},
        'clientes': {'cliente': ['view', 'add', 'change']},
        'prestamos': {'prestamo': ['view', 'add', 'change'], 'multa': ['view', 'change']},
    },
    'Gerente': {
        'catalogo': {'categoria': ['view', 'add', 'change', 'delete'], 'libro': ['view', 'add', 'change', 'delete']},
        'clientes': {'cliente': ['view', 'add', 'change', 'delete']},
        'ventas': {
            'promocion': ['view', 'add', 'change', 'delete'],
            'venta': ['view', 'add'], 'detalleventa': ['view', 'add'],
        },
        'prestamos': {'prestamo': ['view', 'add', 'change'], 'multa': ['view', 'change']},
    },
}


class Command(BaseCommand):
    help = 'Crea los grupos Cajero, Bibliotecario y Gerente con sus permisos.'

    def handle(self, *args, **options):
        for nombre, apps in ROLES.items():
            permisos = []
            for app, modelos in apps.items():
                for modelo, acciones in modelos.items():
                    for accion in acciones:
                        permisos.append(Permission.objects.get(
                            content_type__app_label=app, codename=f'{accion}_{modelo}'
                        ))
            grupo, creado = Group.objects.get_or_create(name=nombre)
            grupo.permissions.set(permisos)
            estado = 'creado' if creado else 'actualizado'
            self.stdout.write(self.style.SUCCESS(f'{nombre}: {estado} con {len(permisos)} permisos'))
