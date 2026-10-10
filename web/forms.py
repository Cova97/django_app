from django import forms

from catalogo.models import Categoria, Libro
from clientes.models import Cliente
from prestamos.models import Prestamo


class EstiloBootstrap:
    """Agrega las clases CSS de Bootstrap a todos los campos del formulario."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            widget = campo.widget
            if isinstance(widget, forms.CheckboxInput):
                clase = 'form-check-input'
            elif isinstance(widget, forms.Select):
                clase = 'form-select'
            else:
                clase = 'form-control'
            widget.attrs['class'] = f"{widget.attrs.get('class', '')} {clase}".strip()


class CampoFecha(forms.DateInput):
    input_type = 'date'

    def __init__(self, **kwargs):
        super().__init__(format='%Y-%m-%d', **kwargs)


# --- Filtros (GET). Si un filtro no es válido se ignora en lugar de fallar. ---

class FiltroCatalogoForm(EstiloBootstrap, forms.Form):
    q = forms.CharField(
        required=False, max_length=100, label='Buscar',
        widget=forms.TextInput(attrs={'placeholder': 'Título, autor o ISBN', 'type': 'search'}),
    )
    categoria = forms.ModelChoiceField(
        Categoria.objects.all(), required=False, empty_label='Todas las categorías', label='Categoría'
    )


class FiltroTextoForm(EstiloBootstrap, forms.Form):
    q = forms.CharField(
        required=False, max_length=100, label='Buscar',
        widget=forms.TextInput(attrs={'placeholder': 'Buscar…', 'type': 'search'}),
    )


class FiltroVentasForm(EstiloBootstrap, forms.Form):
    q = forms.CharField(
        required=False, max_length=100, label='Cliente',
        widget=forms.TextInput(attrs={'placeholder': 'Nombre del cliente', 'type': 'search'}),
    )
    desde = forms.DateField(required=False, widget=CampoFecha())
    hasta = forms.DateField(required=False, widget=CampoFecha())


def datos_filtro(formulario):
    return formulario.cleaned_data if formulario.is_valid() else {}


# --- Ventas ---

class OpcionLibro(forms.ModelChoiceField):
    def label_from_instance(self, libro):
        return f'{libro.titulo} — ${libro.precio_venta} (stock: {libro.stock_venta})'


class VentaForm(EstiloBootstrap, forms.Form):
    cliente = forms.ModelChoiceField(Cliente.objects.filter(activo=True), empty_label='Selecciona un cliente')


class LineaVentaForm(EstiloBootstrap, forms.Form):
    libro = OpcionLibro(
        Libro.objects.filter(stock_venta__gt=0).order_by('titulo'), empty_label='Selecciona un libro'
    )
    cantidad = forms.IntegerField(min_value=1, max_value=100, initial=1)


LineasVentaFormSet = forms.formset_factory(
    LineaVentaForm, extra=0, min_num=1, validate_min=True, max_num=50, validate_max=True,
)


# --- Préstamos ---

class PrestamoForm(EstiloBootstrap, forms.ModelForm):
    class Meta:
        model = Prestamo
        fields = ['cliente', 'libro', 'fecha_limite']
        widgets = {'fecha_limite': CampoFecha()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cliente'].queryset = Cliente.objects.filter(activo=True)
        self.fields['libro'].queryset = Libro.objects.filter(ejemplares_prestamo__gt=0).order_by('titulo')
        self.fields['fecha_limite'].help_text = 'Por defecto, 14 días a partir de hoy.'


# --- Clientes ---

class ClienteForm(EstiloBootstrap, forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ['nombre', 'apellidos', 'email', 'telefono', 'activo']
        help_texts = {'telefono': '10 dígitos, sin espacios ni guiones.'}

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        repetidos = Cliente.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if repetidos.exists():
            raise forms.ValidationError('Ya existe un cliente con ese email.')
        return email
