# 📚 Librería: sistema de ventas y préstamos de libros

Sistema web de código abierto para administrar una librería que **vende** libros y también los **presta** a sus clientes. Maneja promociones por temporada, controla los préstamos vencidos y genera multas por retraso de forma automática.

Está hecho por completo con **Django**: base de datos, reglas de negocio, panel para empleados, catálogo público y API REST viven en un solo proyecto.

---

## Contenido

- [Qué hace](#qué-hace)
- [Tecnologías](#tecnologías)
- [Instalación paso a paso](#instalación-paso-a-paso)
- [Primeros pasos: recorrido de prueba](#primeros-pasos-recorrido-de-prueba)
- [Roles y permisos](#roles-y-permisos)
- [API REST](#api-rest)
- [Configuración](#configuración)
- [Pruebas automáticas](#pruebas-automáticas)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Usar otra base de datos (PostgreSQL / MySQL)](#usar-otra-base-de-datos-postgresql--mysql)
- [Puesta en producción](#puesta-en-producción)
- [Problemas comunes](#problemas-comunes)
- [Cómo contribuir](#cómo-contribuir)
- [Licencia](#licencia)

---

## Qué hace

### Ventas y promociones
- Venta de varios libros en una sola operación, con validación de stock. No permite vender más de lo que hay, aunque el mismo libro aparezca en varias líneas.
- **Promociones por temporada** con fecha de inicio y fin y un porcentaje de descuento. Pueden aplicar a todo el catálogo, a categorías o a libros específicos.
- Al vender se aplica sola **la mejor promoción vigente en la fecha de la venta**. Las promociones desactivadas o fuera de temporada no se aplican.
- Cada venta guarda el precio y el descuento de ese momento: si después cambian los precios o termina la promoción, el historial no se altera. Una venta registrada no se puede editar ni borrar.

### Préstamos, retrasos y multas
- Préstamos con fecha límite, 14 días por defecto (configurable).
- Control de ejemplares: no se presta si todos los ejemplares están fuera.
- **Detección de préstamos vencidos**, con los días de retraso y la multa estimada.
- Al devolver con retraso se **genera automáticamente una multa**, por defecto $10 por día (configurable).
- Un cliente **no puede pedir prestado** si:
  - tiene multas sin pagar,
  - tiene préstamos vencidos sin devolver,
  - ya llegó al máximo de préstamos activos (3 por defecto), o
  - está inactivo.

### Interfaces
| Interfaz | Para quién | Dirección |
|---|---|---|
| **Catálogo público** | Cualquier visitante | `/` |
| **Panel de empleados** | Cajeros, bibliotecarios y gerentes | `/panel/` |
| **Administración de Django** | Gerentes y administradores | `/admin/` |
| **API REST (JSON)** | Otras aplicaciones (web, móvil) | `/api/` |

### Seguridad
- Inicio de sesión y **permisos por rol** (Cajero, Bibliotecario, Gerente), los mismos en el panel, el admin y la API.
- API con tokens que **caducan** a las 8 horas y límite de intentos de login contra ataques de fuerza bruta.
- Protección contra **inyección SQL**: todas las consultas usan el ORM de Django, con parámetros, y los filtros de la URL se validan antes de usarse.
- Validación de datos en todas las entradas: ISBN, teléfono, nombres, email único, rangos de precios y cantidades, fechas.
- **Manejo global de errores**: la API siempre responde JSON con el mismo formato y el sitio muestra páginas de error propias (404, 403, 500). Los errores inesperados se registran en `errores.log` sin exponer detalles internos.
- Protección CSRF en formularios y validación de redirecciones.

---

## Tecnologías

- [Python](https://www.python.org/) 3.12 o superior (probado con 3.14)
- [Django](https://www.djangoproject.com/) 6.1
- [Django REST Framework](https://www.django-rest-framework.org/) 3.18
- [Bootstrap](https://getbootstrap.com/) 5.3, incluido en el proyecto, así que funciona sin internet
- SQLite por defecto, sin instalar nada extra; compatible con PostgreSQL y MySQL

---

## Instalación paso a paso

> Los comandos están para **Windows (PowerShell)** y **Linux / macOS (terminal)**. Donde son distintos, se indican ambos.

### 1. Instala lo necesario

- **Python 3.12 o superior**: descárgalo de [python.org/downloads](https://www.python.org/downloads/).
  En Windows, durante la instalación marca la casilla **"Add python.exe to PATH"**.
- **Git** (opcional, para clonar): [git-scm.com](https://git-scm.com/).

Comprueba que quedó instalado:

```bash
python --version
```

> En Linux/macOS puede que el comando sea `python3` en lugar de `python`.

### 2. Descarga el proyecto

Con Git:

```bash
git clone <URL-DEL-REPOSITORIO> libreria
cd libreria
```

O descarga el ZIP desde la página del repositorio, descomprímelo y abre una terminal dentro de la carpeta.

### 3. Crea y activa un entorno virtual

El entorno virtual mantiene las dependencias del proyecto separadas del resto de tu sistema.

**Windows (PowerShell):**
```powershell
python -m venv venv
venv\Scripts\activate
```

> Si PowerShell muestra un error de "ejecución de scripts deshabilitada", ejecuta una vez
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y vuelve a intentar.

**Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

Sabrás que está activo porque la línea de la terminal empieza con `(venv)`.

### 4. Instala las dependencias

```bash
pip install -r requirements.txt
```

### 5. Crea la base de datos

```bash
python manage.py migrate
```

Esto crea el archivo `db.sqlite3` con todas las tablas.

### 6. Crea los roles de empleados

```bash
python manage.py crear_roles
```

Crea los grupos **Cajero**, **Bibliotecario** y **Gerente** con sus permisos.

### 7. Crea tu usuario administrador

```bash
python manage.py createsuperuser
```

Te pedirá un nombre de usuario, un email (opcional) y una contraseña.

### 8. (Opcional) Carga datos de ejemplo

```bash
python manage.py cargar_datos
```

Agrega 14 libros, 8 clientes, 6 promociones, ventas, préstamos (algunos vencidos) y multas. Las fechas se calculan a partir del día de hoy, así que siempre habrá promociones vigentes y préstamos vencidos para probar.

> Para volver a empezar con datos limpios: `python manage.py cargar_datos --borrar`
> (borra libros, clientes, ventas, préstamos, etc.; **no** borra usuarios).

### 9. Inicia el servidor

```bash
python manage.py runserver
```

Abre en tu navegador:

- Catálogo público: **http://127.0.0.1:8000/**
- Panel de empleados: **http://127.0.0.1:8000/panel/** (entra con el usuario del paso 7)
- Administración: **http://127.0.0.1:8000/admin/**
- API: **http://127.0.0.1:8000/api/**

Para detener el servidor, presiona `Ctrl + C`.

> Cada vez que vuelvas a trabajar en el proyecto, solo tienes que **activar el entorno virtual** (paso 3) y **ejecutar el servidor** (paso 9).

---

## Primeros pasos: recorrido de prueba

Con los datos de ejemplo cargados, prueba esto:

1. **Catálogo público**: abre `/` sin iniciar sesión. Verás las promociones vigentes y los precios con descuento (el precio anterior aparece tachado).
2. **Panel**: inicia sesión en "Acceso empleados". El resumen muestra las ventas del día, los préstamos vencidos y las multas por cobrar.
3. **Venta con promoción**: en *Ventas → Nueva venta*, agrega *Don Quijote de la Mancha*. Se le aplica la promoción "Semana de los clásicos" (25%) y no la general (10%), porque gana la mayor.
4. **Préstamo vencido**: en *Préstamos → Vencidos*, Luis tiene un libro con 6 días de retraso. Presiona **Devolver**: se genera una multa de $60.
5. **Bloqueo por multa**: intenta registrar un préstamo nuevo para Luis. El sistema lo impide porque tiene una multa pendiente.
6. **Cobro**: en *Multas*, presiona **Cobrar**. Ahora Luis ya puede pedir prestado.
7. **Roles**: en `/admin/` crea un usuario, márcalo como *Es staff* y asígnale el grupo **Cajero**. Al entrar con él verás que no tiene acceso a préstamos ni multas.

---

## Roles y permisos

| Acción | Cajero | Bibliotecario | Gerente |
|---|:---:|:---:|:---:|
| Ver catálogo e inventario | ✅ | ✅ | ✅ |
| Registrar y editar clientes | ✅ | ✅ | ✅ |
| Registrar ventas | ✅ | ❌ | ✅ |
| Registrar préstamos y devoluciones | ❌ | ✅ | ✅ |
| Cobrar multas | ❌ | ✅ | ✅ |
| Crear y editar libros y promociones | ❌ | ❌ | ✅ |
| Borrar registros | ❌ | ❌ | ✅ |

Para dar acceso a un empleado: en `/admin/` → *Usuarios*, marca **"Es staff"** y asígnale un grupo.
El superusuario tiene todos los permisos.

---

## API REST

Todas las rutas están bajo `/api/`. En modo desarrollo puedes explorarlas desde el navegador en `http://127.0.0.1:8000/api/` (inicia sesión antes en `/admin/`).

### Autenticación

```bash
# 1. Obtener un token (caduca en 8 horas)
curl -X POST http://127.0.0.1:8000/api/auth/login/ \
     -H "Content-Type: application/json" \
     -d '{"username": "admin", "password": "tu-contraseña"}'

# 2. Usarlo en cada petición
curl http://127.0.0.1:8000/api/clientes/ -H "Authorization: Token <tu-token>"
```

### Rutas

| Ruta | Métodos | Acceso |
|---|---|---|
| `/api/auth/login/`, `/api/auth/logout/`, `/api/auth/yo/` | POST / POST / GET | — |
| `/api/libros/`, `/api/categorias/` | GET (público), POST / PATCH / DELETE | Gerente para modificar |
| `/api/promociones/` | GET (público: solo vigentes), POST / PATCH / DELETE | Gerente para modificar |
| `/api/clientes/` | GET, POST, PATCH, DELETE | Empleados |
| `/api/ventas/` | GET, POST | Cajero, Gerente |
| `/api/prestamos/` | GET, POST | Bibliotecario, Gerente |
| `/api/prestamos/{id}/devolver/` | POST | Bibliotecario, Gerente |
| `/api/multas/` | GET | Bibliotecario, Gerente |
| `/api/multas/{id}/pagar/` | POST | Bibliotecario, Gerente |

**Filtros:** `?q=` (búsqueda), `?orden=` (ordenamiento), `?pagina=`, `?categoria=`, `?estado=activos|vencidos|devueltos`, `?pagada=true|false`, `?desde=AAAA-MM-DD`, `?hasta=AAAA-MM-DD`.

**Ejemplo, registrar una venta:**

```json
POST /api/ventas/
{
  "cliente": 1,
  "detalles": [
    {"libro": 3, "cantidad": 2},
    {"libro": 7, "cantidad": 1}
  ]
}
```

### Formato de errores

Todos los errores responden con la misma estructura:

```json
{
  "error": {
    "estado": 400,
    "codigo": "datos_invalidos",
    "mensaje": "Los datos enviados no son válidos.",
    "detalles": {"cliente": ["El cliente tiene multas pendientes de pago."]}
  }
}
```

Códigos posibles: `datos_invalidos` (400), `no_autenticado` (401), `sin_permiso` (403), `no_encontrado` (404), `metodo_no_permitido` (405), `conflicto` (409), `tipo_no_soportado` (415), `demasiadas_solicitudes` (429), `error_interno` (500).

---

## Configuración

### Reglas del negocio

Se ajustan en `app/settings.py`:

```python
LIBRERIA = {
    'DIAS_PRESTAMO': 14,                # días que dura un préstamo
    'MULTA_POR_DIA': Decimal('10.00'),  # monto por cada día de retraso
    'MAX_PRESTAMOS_ACTIVOS': 3,         # préstamos simultáneos por cliente
}

API_TOKEN_HORAS = 8   # duración de la sesión de la API
TIME_ZONE = 'America/Mexico_City'  # cámbiala a tu zona horaria; afecta el cálculo de retrasos
```

### Variables de entorno

| Variable | Para qué | Valor por defecto |
|---|---|---|
| `DJANGO_DEBUG` | `1` desarrollo, `0` producción | `1` |
| `DJANGO_SECRET_KEY` | Clave secreta (**obligatoria en producción**) | clave de desarrollo |
| `DJANGO_ALLOWED_HOSTS` | Dominios permitidos, separados por coma | vacío |

---

## Pruebas automáticas

El proyecto incluye más de 100 pruebas que cubren las reglas del negocio, los flujos completos (ventas, promociones, préstamos, retrasos, multas), la seguridad de la API, los permisos por rol, la validación de datos y los intentos de inyección SQL.

```bash
python manage.py test              # todas
python manage.py test ventas       # ventas y promociones
python manage.py test prestamos    # préstamos, retrasos y multas
python manage.py test api          # API: errores, seguridad, validación, inyección SQL
python manage.py test web          # sitio web
```

---

## Estructura del proyecto

```
├── app/              Configuración del proyecto (settings, rutas principales)
├── catalogo/         Libros y categorías  + comando `cargar_datos`
├── clientes/         Clientes
├── ventas/           Ventas, promociones y servicios de venta compartidos
├── prestamos/        Préstamos y multas
├── api/              API REST: rutas, permisos, validaciones, manejo de errores + comando `crear_roles`
├── web/              Catálogo público y panel de empleados (vistas, formularios, plantillas)
├── templates/        Plantilla base, login y páginas de error
├── static/           CSS, JavaScript y Bootstrap
├── manage.py
└── requirements.txt
```

Las reglas de negocio viven en los **modelos** (`models.py`) y en `ventas/servicios.py`; el admin, la API y el sitio web las reutilizan, así que se comportan igual en las tres interfaces.

---

## Usar otra base de datos (PostgreSQL / MySQL)

SQLite es ideal para probar. Para uso real con varios usuarios a la vez se recomienda **PostgreSQL**:

1. Instala PostgreSQL y crea una base de datos y un usuario.
2. Instala el conector: `pip install "psycopg[binary]"`
3. Cambia `DATABASES` en `app/settings.py`:
   ```python
   DATABASES = {
       'default': {
           'ENGINE': 'django.db.backends.postgresql',
           'NAME': os.environ.get('DB_NAME', 'libreria'),
           'USER': os.environ.get('DB_USER', 'libreria_user'),
           'PASSWORD': os.environ.get('DB_PASSWORD', ''),
           'HOST': os.environ.get('DB_HOST', 'localhost'),
           'PORT': os.environ.get('DB_PORT', '5432'),
       }
   }
   ```
4. Ejecuta de nuevo los pasos 5 a 8 de la instalación.

Para MySQL/MariaDB: `pip install mysqlclient` y `'ENGINE': 'django.db.backends.mysql'`.

---

## Puesta en producción

Lista mínima antes de publicar el sistema en internet:

- [ ] Define `DJANGO_DEBUG=0`, una `DJANGO_SECRET_KEY` larga y aleatoria, y `DJANGO_ALLOWED_HOSTS` con tu dominio.
- [ ] Usa PostgreSQL o MySQL en lugar de SQLite.
- [ ] Ejecuta `python manage.py collectstatic` y sirve la carpeta `staticfiles/` con tu servidor web (o con [WhiteNoise](https://whitenoise.readthedocs.io/)).
- [ ] Usa un servidor de aplicaciones como [Gunicorn](https://gunicorn.org/) o [Waitress](https://docs.pylonsproject.org/projects/waitress/) (Windows) detrás de HTTPS.
- [ ] Ejecuta `python manage.py check --deploy` y atiende sus avisos.

Con `DJANGO_DEBUG=0` se activan automáticamente: redirección a HTTPS, cookies seguras y HSTS.

Para generar una clave secreta:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

---

## Problemas comunes

| Problema | Solución |
|---|---|
| `python` no se reconoce como comando | Reinstala Python marcando "Add python.exe to PATH", o usa `py` (Windows) / `python3` (Linux/macOS). |
| PowerShell no deja activar el entorno virtual | Ejecuta `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. |
| `ModuleNotFoundError: No module named 'django'` | El entorno virtual no está activo. Actívalo (paso 3). |
| `no such table` | Falta crear la base de datos: `python manage.py migrate`. |
| `La base ya tiene datos` al cargar ejemplos | Usa `python manage.py cargar_datos --borrar`. |
| Un empleado entra pero no ve nada en el panel | Debe estar marcado como "Es staff" y tener un grupo asignado. |
| El puerto 8000 está ocupado | Usa otro: `python manage.py runserver 8080`. |
| Los retrasos se calculan con un día de diferencia | Ajusta `TIME_ZONE` en `app/settings.py` a tu zona horaria. |

---

## Cómo contribuir

¡Las contribuciones son bienvenidas!

1. Haz un *fork* del repositorio y crea una rama: `git checkout -b mi-mejora`
2. Haz tus cambios y agrega pruebas para lo nuevo.
3. Verifica que todo pase: `python manage.py test`
4. Si cambiaste modelos, genera la migración: `python manage.py makemigrations`
5. Abre un *pull request* explicando qué cambia y por qué.

Ideas para contribuir: pantallas para editar libros y promociones desde el panel, reportes de ventas por temporada, recordatorios por email de préstamos por vencer, apartado de libros, traducciones.

Si encuentras un error, abre un *issue* con los pasos para reproducirlo.

---

## Licencia

Este proyecto se distribuye bajo la **Licencia MIT**: puedes usarlo, copiarlo, modificarlo y distribuirlo libremente, incluso con fines comerciales, siempre que conserves el aviso de copyright. Consulta el archivo [LICENSE](LICENSE).
