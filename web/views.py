from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from catalogo.models import Libro
from clientes.models import Cliente
from prestamos.models import Multa, Prestamo
from ventas.models import Promocion, Venta
from ventas.servicios import PromocionesVigentes, registrar_venta

from . import forms


def requiere(permiso):
    """Pide iniciar sesión y luego el permiso; sin permiso responde 403 (página de error)."""
    def decorador(vista):
        return login_required(permission_required(permiso, raise_exception=True)(vista))
    return decorador


def volver(request, defecto):
    """Regresa a la página de origen solo si es de este mismo sitio (evita redirecciones abiertas)."""
    destino = request.POST.get('siguiente', '')
    if url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(destino)
    return redirect(defecto)


def paginar(request, consulta, por_pagina=20):
    # get_page tolera números inválidos (?pagina=abc) y devuelve la página más cercana.
    return Paginator(consulta, por_pagina).get_page(request.GET.get('pagina'))


# Nota: las consultas con Count() ignoran el orden por defecto del modelo, por eso se ordena explícitamente.

def con_prestados(libros):
    return libros.annotate(
        prestados=Count('prestamos', filter=Q(prestamos__fecha_devolucion__isnull=True))
    ).order_by('titulo')


# --- Público ---

def catalogo(request):
    filtro = forms.FiltroCatalogoForm(request.GET)
    datos = forms.datos_filtro(filtro)

    libros = con_prestados(Libro.objects.select_related('categoria'))
    if datos.get('q'):
        q = datos['q']
        libros = libros.filter(Q(titulo__icontains=q) | Q(autor__icontains=q) | Q(isbn__icontains=q))
    if datos.get('categoria'):
        libros = libros.filter(categoria=datos['categoria'])

    pagina = paginar(request, libros, 12)
    promociones = PromocionesVigentes()
    for libro in pagina:
        libro.promo = promociones.para(libro)
        libro.precio_final = promociones.precio_final(libro)
        libro.disponibles = libro.ejemplares_prestamo - libro.prestados

    return render(request, 'web/catalogo.html', {
        'pagina': pagina, 'filtro': filtro, 'promociones': promociones.promociones,
    })


# --- Panel ---

@login_required
def panel(request):
    hoy = timezone.localdate()
    usuario = request.user
    contexto = {'hoy': hoy}

    if usuario.has_perm('ventas.view_venta'):
        contexto['ventas_hoy'] = Venta.objects.filter(fecha__date=hoy).aggregate(
            cantidad=Count('id'), total=Sum('total')
        )
        contexto['ultimas_ventas'] = Venta.objects.select_related('cliente')[:5]
    if usuario.has_perm('prestamos.view_prestamo'):
        contexto['prestamos_activos'] = Prestamo.objects.activos().count()
        contexto['vencidos'] = Prestamo.objects.vencidos().select_related('cliente', 'libro').order_by('fecha_limite')
    if usuario.has_perm('prestamos.view_multa'):
        contexto['multas'] = Multa.objects.filter(pagada=False).aggregate(cantidad=Count('id'), total=Sum('monto'))
    if usuario.has_perm('catalogo.view_libro'):
        contexto['poco_stock'] = Libro.objects.filter(stock_venta__lt=3).order_by('stock_venta')
    contexto['promociones'] = Promocion.objects.vigentes()
    return render(request, 'web/panel.html', contexto)


# --- Ventas ---

@requiere('ventas.view_venta')
def ventas_lista(request):
    filtro = forms.FiltroVentasForm(request.GET)
    datos = forms.datos_filtro(filtro)
    ventas = Venta.objects.select_related('cliente').annotate(lineas=Count('detalles')).order_by('-fecha')
    if datos.get('q'):
        q = datos['q']
        ventas = ventas.filter(Q(cliente__nombre__icontains=q) | Q(cliente__apellidos__icontains=q))
    if datos.get('desde'):
        ventas = ventas.filter(fecha__date__gte=datos['desde'])
    if datos.get('hasta'):
        ventas = ventas.filter(fecha__date__lte=datos['hasta'])
    resumen = ventas.aggregate(total=Sum('total'))
    return render(request, 'web/ventas/lista.html', {
        'pagina': paginar(request, ventas), 'filtro': filtro, 'resumen': resumen,
    })


@requiere('ventas.view_venta')
def venta_detalle(request, pk):
    venta = get_object_or_404(Venta.objects.select_related('cliente'), pk=pk)
    detalles = venta.detalles.select_related('libro', 'promocion')
    return render(request, 'web/ventas/detalle.html', {'venta': venta, 'detalles': detalles})


@requiere('ventas.add_venta')
def venta_nueva(request):
    if request.method == 'POST':
        formulario = forms.VentaForm(request.POST)
        lineas = forms.LineasVentaFormSet(request.POST, prefix='lineas')
        if formulario.is_valid() and lineas.is_valid():
            datos = [(f.cleaned_data['libro'], f.cleaned_data['cantidad']) for f in lineas if f.cleaned_data]
            try:
                venta = registrar_venta(formulario.cleaned_data['cliente'], datos)
            except ValidationError as error:
                formulario.add_error(None, error)
            else:
                messages.success(request, f'Venta #{venta.pk} registrada por ${venta.total}.')
                return redirect('web:venta_detalle', pk=venta.pk)
    else:
        formulario = forms.VentaForm()
        lineas = forms.LineasVentaFormSet(prefix='lineas')

    # Precios para el total estimado en el navegador; el total real lo calcula el servidor.
    promociones = PromocionesVigentes()
    precios = {
        libro.pk: {
            'precio': str(libro.precio_venta),
            'final': str(promociones.precio_final(libro)),
            'promo': promo.nombre if (promo := promociones.para(libro)) else None,
        }
        for libro in Libro.objects.filter(stock_venta__gt=0)
    }
    return render(request, 'web/ventas/nueva.html', {
        'formulario': formulario, 'lineas': lineas, 'precios': precios,
    })


# --- Préstamos ---

ESTADOS_PRESTAMO = {
    'activos': ('Activos', lambda qs: qs.activos()),
    'vencidos': ('Vencidos', lambda qs: qs.vencidos()),
    'devueltos': ('Devueltos', lambda qs: qs.filter(fecha_devolucion__isnull=False)),
    'todos': ('Todos', lambda qs: qs),
}


@requiere('prestamos.view_prestamo')
def prestamos_lista(request):
    estado = request.GET.get('estado')
    if estado not in ESTADOS_PRESTAMO:
        estado = 'activos'
    filtro = forms.FiltroTextoForm(request.GET)
    datos = forms.datos_filtro(filtro)

    prestamos = ESTADOS_PRESTAMO[estado][1](Prestamo.objects.select_related('cliente', 'libro', 'multa'))
    if datos.get('q'):
        q = datos['q']
        prestamos = prestamos.filter(
            Q(libro__titulo__icontains=q) | Q(cliente__nombre__icontains=q) | Q(cliente__apellidos__icontains=q)
        )
    prestamos = prestamos.order_by('fecha_limite' if estado in ('activos', 'vencidos') else '-fecha_prestamo')
    return render(request, 'web/prestamos/lista.html', {
        'pagina': paginar(request, prestamos), 'filtro': filtro, 'estado': estado,
        'estados': {clave: nombre for clave, (nombre, _) in ESTADOS_PRESTAMO.items()},
    })


@requiere('prestamos.add_prestamo')
def prestamo_nuevo(request):
    formulario = forms.PrestamoForm(request.POST or None, initial={'cliente': request.GET.get('cliente')})
    if request.method == 'POST' and formulario.is_valid():
        # ModelForm ejecuta Prestamo.clean(): ejemplares, multas, vencidos y límite de préstamos.
        prestamo = formulario.save()
        messages.success(
            request, f'Préstamo registrado: "{prestamo.libro.titulo}" a {prestamo.cliente}. '
                     f'Debe devolverse el {prestamo.fecha_limite:%d/%m/%Y}.'
        )
        return redirect('web:prestamos_lista')
    return render(request, 'web/prestamos/nuevo.html', {'formulario': formulario})


@require_POST
@requiere('prestamos.change_prestamo')
def prestamo_devolver(request, pk):
    prestamo = get_object_or_404(Prestamo, pk=pk)
    if not prestamo.activo:
        messages.warning(request, 'Ese préstamo ya había sido devuelto.')
    else:
        multa = prestamo.devolver()
        if multa:
            messages.warning(
                request, f'Libro devuelto con {multa.dias_retraso} día(s) de retraso. '
                         f'Se generó una multa de ${multa.monto} a {prestamo.cliente}.'
            )
        else:
            messages.success(request, f'"{prestamo.libro.titulo}" devuelto a tiempo.')
    return volver(request, 'web:prestamos_lista')


# --- Multas ---

@requiere('prestamos.view_multa')
def multas_lista(request):
    estado = request.GET.get('estado')
    if estado not in ('pendientes', 'pagadas', 'todas'):
        estado = 'pendientes'
    multas = Multa.objects.select_related('prestamo__cliente', 'prestamo__libro')
    if estado != 'todas':
        multas = multas.filter(pagada=(estado == 'pagadas'))
    pendiente = Multa.objects.filter(pagada=False).aggregate(total=Sum('monto'))['total']
    return render(request, 'web/multas/lista.html', {
        'pagina': paginar(request, multas), 'estado': estado, 'total_pendiente': pendiente,
    })


@require_POST
@requiere('prestamos.change_multa')
def multa_pagar(request, pk):
    multa = get_object_or_404(Multa.objects.select_related('prestamo__cliente'), pk=pk)
    if multa.pagada:
        messages.warning(request, 'Esa multa ya estaba pagada.')
    else:
        multa.pagar()
        messages.success(request, f'Multa de ${multa.monto} de {multa.prestamo.cliente} marcada como pagada.')
    return volver(request, 'web:multas_lista')


# --- Clientes ---

@requiere('clientes.view_cliente')
def clientes_lista(request):
    filtro = forms.FiltroTextoForm(request.GET)
    datos = forms.datos_filtro(filtro)
    clientes = Cliente.objects.annotate(
        activos=Count('prestamos', filter=Q(prestamos__fecha_devolucion__isnull=True), distinct=True),
        pendientes=Count('prestamos__multa', filter=Q(prestamos__multa__pagada=False), distinct=True),
    ).order_by('apellidos', 'nombre')
    if datos.get('q'):
        q = datos['q']
        clientes = clientes.filter(Q(nombre__icontains=q) | Q(apellidos__icontains=q) | Q(email__icontains=q))
    return render(request, 'web/clientes/lista.html', {'pagina': paginar(request, clientes), 'filtro': filtro})


@requiere('clientes.view_cliente')
def cliente_detalle(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    contexto = {'cliente': cliente}
    if request.user.has_perm('ventas.view_venta'):
        contexto['ventas'] = cliente.compras.all()[:10]
    if request.user.has_perm('prestamos.view_prestamo'):
        contexto['prestamos'] = cliente.prestamos.select_related('libro', 'multa')[:20]
    return render(request, 'web/clientes/detalle.html', contexto)


@requiere('clientes.add_cliente')
def cliente_nuevo(request):
    return _guardar_cliente(request, Cliente())


@requiere('clientes.change_cliente')
def cliente_editar(request, pk):
    return _guardar_cliente(request, get_object_or_404(Cliente, pk=pk))


def _guardar_cliente(request, cliente):
    formulario = forms.ClienteForm(request.POST or None, instance=cliente)
    if request.method == 'POST' and formulario.is_valid():
        cliente = formulario.save()
        messages.success(request, f'Cliente "{cliente}" guardado.')
        return redirect('web:cliente_detalle', pk=cliente.pk)
    return render(request, 'web/clientes/form.html', {'formulario': formulario, 'cliente': cliente})


# --- Inventario y promociones ---

@requiere('catalogo.view_libro')
def inventario(request):
    filtro = forms.FiltroCatalogoForm(request.GET)
    datos = forms.datos_filtro(filtro)
    libros = con_prestados(Libro.objects.select_related('categoria'))
    if datos.get('q'):
        q = datos['q']
        libros = libros.filter(Q(titulo__icontains=q) | Q(autor__icontains=q) | Q(isbn__icontains=q))
    if datos.get('categoria'):
        libros = libros.filter(categoria=datos['categoria'])
    pagina = paginar(request, libros, 25)
    for libro in pagina:
        libro.disponibles = libro.ejemplares_prestamo - libro.prestados
    return render(request, 'web/inventario.html', {'pagina': pagina, 'filtro': filtro})


@requiere('ventas.view_promocion')
def promociones(request):
    hoy = timezone.localdate()
    lista = Promocion.objects.prefetch_related('libros', 'categorias')
    for promo in lista:
        if not promo.activa:
            promo.estado = ('Desactivada', 'secondary')
        elif promo.fecha_fin < hoy:
            promo.estado = ('Terminada', 'secondary')
        elif promo.fecha_inicio > hoy:
            promo.estado = ('Próxima', 'info')
        else:
            promo.estado = ('Vigente', 'success')
    return render(request, 'web/promociones.html', {'promociones': lista})
