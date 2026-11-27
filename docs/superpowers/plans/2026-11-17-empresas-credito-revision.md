# Empresas, crédito por empresa y "Revisión" — Plan de implementación

> **Para quien implemente:** usar superpowers:subagent-driven-development (recomendado) o superpowers:executing-plans. Los pasos usan casillas `- [ ]`.

**Objetivo:** que cada proveedor exista una sola vez con un crédito por empresa, que cada creador trabaje para su empresa, que quien revisa vea el crédito de todas las empresas, y que "Aprobación" pase a llamarse "Revisión" en pantalla.

**Arquitectura:** tabla `empresas`; `Usuario.empresa_id`; tabla `proveedor_creditos` (una fila por proveedor + empresa). Las pantallas de proveedores muestran una columna por empresa visible para el usuario. El renombre toca solo textos visibles.

**Tecnología:** Python, FastAPI, SQLAlchemy sobre SQLite, plantillas Jinja2 + HTMX, pytest (ya en el proyecto).

**Spec:** `docs/superpowers/specs/2026-11-17-empresas-credito-revision-design.md`

## Restricciones globales

- Toda la interfaz en español. Datos de prueba siempre inventados.
- **Renombre solo visible:** no cambian rutas (`/aprobaciones`), clases CSS (`insignia-aprobado`), nombres de funciones, constantes (`APROBADO`, `PENDIENTE`), columnas ni valores guardados (`"aprobado"`, tipo de historial `"aprobacion"`).
- Textos nuevos: menú y pantalla **«Revisiones»**; rol **«Revisor»**; estados **«Pendiente / Revisado / Rechazado»**; botón **«Marcar como revisado»**; mensajes «Revisado: X», «Proveedores revisados: n».
- **Facturación fuera de alcance:** no se cambia su lógica. `crear_factura`, `fila_pago` y `Proveedor.credito_texto` siguen leyendo `Proveedor.credito_tipo/credito_valor` (columnas antiguas, ya no las escribe ninguna pantalla). Solo se renombra el texto visible de facturas.
- El crédito **no es dato sensible**: guardar un crédito no reabre la revisión ni cambia `modificado_por_id`/`modificado_en`.
- Un creador solo ve y edita el crédito de su empresa (en servidor, nunca confiar en el `empresa_id` que llegue del navegador). Revisor y administrador ven todas las empresas activas; solo el administrador edita créditos de cualquier empresa.
- Números de ID y de cuenta siempre texto.
- **No hay migración:** la base existente no tiene `usuarios.empresa_id`; no arrancar la app contra ella hasta la migración (diferida). Las pruebas usan bases temporales.
- No hacer commit salvo que el usuario lo pida. Los «puntos de control» solo corren las pruebas.
- Comando de pruebas, desde `D:\BACSS\PRODUCTOS\manejoProvedores`: `python -m pytest -q`.

## Review Focus

Entradas que el spec no menciona y que más probablemente fallen; cada una tiene su prueba en la tarea indicada.

1. Mismo número de ID escrito con espacios o con otro tipo de espacio → debe reconocerse como proveedor existente (Tarea 4).
2. Proveedor existente pero desactivado, al que otra empresa le añade crédito → se añade el crédito, no se reactiva, y se avisa (Tarea 4).
3. Un creador manipula el `empresa_id` del formulario para escribir el crédito de otra empresa → se rechaza o se ignora (Tarea 4).
4. Empresa desactivada → su columna desaparece del listado del revisor, sus créditos se conservan y reaparecen al reactivarla (Tarea 5).
5. Aún no hay empresas creadas → listado, ficha, formulario y exportación no se rompen y explican qué falta (Tarea 5).

## Estructura de archivos

| Archivo | Cambio |
|---|---|
| `app/modelos.py` | Nuevas `Empresa`, `ProveedorCredito`; `Usuario.empresa_id`; helpers en `Proveedor`; etiquetas «Revisor», «Revisado» |
| `app/servicios.py` | Empresas, usuarios con empresa, créditos por empresa, visibilidad y permisos; textos de revisión |
| `app/rutas/proveedores.py` | Crédito fuera del formulario principal, alta que reconoce proveedor existente, `POST /proveedores/{pid}/credito`, columnas por empresa |
| `app/rutas/administracion.py` | Pantalla `/empresas`; empresa en `/usuarios` |
| `app/rutas/aprobaciones.py`, `app/web.py`, `app/cli.py`, `app/importacion.py`, `app/exportacion.py`, `app/validaciones.py` | Textos y créditos por empresa |
| `app/templates/*.html` | Ver cada tarea |
| `tests/ayudas.py`, `tests/test_web.py` | Ayudas y fixture `equipo` con empresas |
| `tests/test_revision_textos.py`, `test_empresas.py`, `test_credito_empresas.py`, `test_proveedor_empresas.py`, `test_vistas_revisor.py` | Pruebas nuevas |

---

### Tarea 1: «Aprobación» pasa a «Revisión» (solo lo visible)

**Archivos:**
- Modificar: `app/modelos.py` (`ROLES`, `ESTADOS_APROBACION`), `app/servicios.py` (mensajes y etiquetas de historial), `app/rutas/aprobaciones.py`, `app/rutas/proveedores.py`, `app/rutas/administracion.py`, `app/importacion.py`, `app/cli.py`, `app/exportacion.py`, `app/validaciones.py` y todas las plantillas que tengan «aprob» en texto visible (`base`, `aprobaciones`, `proveedores`, `proveedor_ficha`, `proveedor_form`, `validaciones`, `historial`, `usuarios`, `facturas`, `panel`).
- Crear: `tests/test_revision_textos.py`
- Actualizar aserciones existentes: `tests/test_aprobacion.py:34`, `test_exportacion.py:132,148,197`, `test_importacion.py:200`, `test_sin_facturacion.py:57`, `test_web.py:247,390`.

**Interfaces:**
- Produce: `modelos.ROLES[APROBADOR] == "Revisor"`; `modelos.ESTADOS_APROBACION[APROBADO] == "Revisado"`; el historial guarda `valor_nuevo == "Revisado"` y `campo == "Estado de revisión"` en registros nuevos.

- [ ] **Paso 1: escribir la prueba que vigila los textos** en `tests/test_revision_textos.py`:

```python
import re

from test_web import _crear_proveedor, equipo  # noqa: F401
from ayudas import publicar

PROHIBIDO = re.compile(r"aprobaci|aprobad|aprobar|aprobador", re.I)


def _visible(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)  # quita etiquetas: href, class y action no cuentan


def test_ninguna_pantalla_habla_de_aprobacion(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo)
    paginas = [
        ("creador", "/"), ("creador", "/proveedores"), ("creador", f"/proveedores/{pid}"),
        ("creador", "/proveedores/nuevo"), ("aprobador", f"/proveedores/{pid}"),
        ("aprobador", "/aprobaciones"), ("admin", "/aprobaciones"), ("admin", "/validaciones"),
        ("admin", "/historial"), ("admin", "/usuarios"), ("admin", "/facturas"),
    ]
    for quien, ruta in paginas:
        texto = _visible(equipo[quien].get(ruta).text)
        assert not PROHIBIDO.search(texto), (ruta, PROHIBIDO.search(texto).group())
    assert publicar(equipo["aprobador"], f"/aprobaciones/{pid}/aprobar").status_code == 303
    ficha = _visible(equipo["creador"].get(f"/proveedores/{pid}").text)
    assert "Revisado" in ficha and not PROHIBIDO.search(ficha)
```

- [ ] **Paso 2: correr** `python -m pytest tests/test_revision_textos.py -q`. Esperado: FALLA nombrando «Aprobaciones».
- [ ] **Paso 3: cambiar los textos** según las restricciones globales, en este orden: etiquetas de `modelos.py`; mensajes de `servicios.py` (`motivo_no_puede_aprobar` → «Su perfil no permite revisar proveedores.», «El proveedor no está pendiente de revisión.», «No puede revisar un proveedor que usted mismo creó.», «No puede revisar un proveedor cuya última modificación hizo usted.»; campo de historial «Estado de revisión»; valor «Revisado»); mensajes de rutas; plantillas; salida de CLI e importador («ya revisados»); encabezado de exportación `ESTADO REVISION`; frases de facturas («proveedores revisados», «no está revisado»).
- [ ] **Paso 4: actualizar las aserciones listadas arriba** a los textos nuevos. Una aserción que busque `usted mismo cre` no cambia.
- [ ] **Paso 5: revisar lo que queda.** Ejecutar `grep -rniE "aprob" app --include=*.py --include=*.html`. Cada resultado restante debe ser identificador, ruta, clase CSS, valor guardado o comentario; cualquier otro es texto visible y se cambia.
- [ ] **Paso 6: punto de control.** `python -m pytest -q` debe pasar completo.

---

### Tarea 2: Empresas y usuarios con empresa

**Archivos:**
- Modificar: `app/modelos.py`, `app/servicios.py`, `app/rutas/administracion.py`, `app/templates/usuarios.html`, `app/templates/base.html`
- Crear: `app/templates/empresas.html`, `tests/test_empresas.py`
- Modificar: `tests/ayudas.py`, `tests/test_web.py` (fixture `equipo`)

**Interfaces:**
- Produce en `modelos`: `Empresa(id, nombre: str, nombre_norm: str único, activo: bool)`; `Usuario.empresa_id: Optional[int]` (FK `empresas.id`) y `Usuario.empresa`.
- Produce en `servicios`:
  - `crear_empresa(db, nombre: str) -> Empresa` (error: «Escriba el nombre de la empresa.» / «Ya existe una empresa con ese nombre.»; duplicado por `normalizar`).
  - `actualizar_empresa(db, e: Empresa, nombre: str, activo: bool) -> None`
  - `empresas_activas(db) -> List[Empresa]` ordenadas por `nombre_norm`
  - `empresa_de(u: Usuario) -> Optional[Empresa]`: la empresa del usuario solo si está activa.
  - `crear_usuario(db, usuario, nombre, clave, rol, empresa_id: Optional[int] = None)` y `actualizar_usuario(db, u, nombre, rol, activo, clave="", empresa_id=None)`: solo el rol creador guarda empresa. Un creador **activo** sin empresa activa válida da «Elija la empresa de la persona (créela antes en Empresas).».
- Produce en `ayudas`: `empresa(sesion, nombre="EMPRESA A") -> Empresa` (la busca por nombre normalizado o la crea); `crear_usuario(sesion, usuario, rol, empresa=None)` (un creador sin empresa recibe `empresa(sesion)`).
- Produce en `equipo` (test_web): el administrador crea «EMPRESA A» y «EMPRESA B» con `POST /empresas/nueva`; `carla` (creador) en A; nuevo `diana` (creador) en B, expuesta como `equipo["creador2"]`.

- [ ] **Paso 1: escribir pruebas** en `tests/test_empresas.py`:

```python
import pytest
from sqlalchemy import select

from app import servicios
from app.modelos import CREADOR, APROBADOR, Empresa
from app.servicios import ErrorNegocio
import ayudas


def test_crear_empresa_no_admite_vacia_ni_repetida(sesion):
    e = servicios.crear_empresa(sesion, "  Cía   Norte ")
    assert e.nombre == "Cía Norte"
    with pytest.raises(ErrorNegocio, match="Escriba el nombre"):
        servicios.crear_empresa(sesion, "   ")
    with pytest.raises(ErrorNegocio, match="Ya existe"):
        servicios.crear_empresa(sesion, "CIA NORTE")  # mayúsculas y acentos no distinguen


def test_un_creador_nuevo_exige_empresa_activa(sesion):
    inactiva = ayudas.empresa(sesion, "VIEJA")
    servicios.actualizar_empresa(sesion, inactiva, "VIEJA", False)
    for empresa_id in (None, inactiva.id):
        with pytest.raises(ErrorNegocio, match="empresa"):
            servicios.crear_usuario(sesion, "nuevo", "Nuevo", "clave-nuevo-123", CREADOR, empresa_id)
    u = servicios.crear_usuario(sesion, "revisor", "Revisor", "clave-revisor-123", APROBADOR, inactiva.id)
    assert u.empresa_id is None  # solo el creador guarda empresa


def test_empresa_de_solo_si_esta_activa(sesion):
    e = ayudas.empresa(sesion)
    u = ayudas.crear_usuario(sesion, "ana", CREADOR, e)
    assert servicios.empresa_de(u).id == e.id
    servicios.actualizar_empresa(sesion, e, e.nombre, False)
    assert servicios.empresa_de(u) is None


def test_pantalla_empresas_solo_para_el_administrador(equipo):
    from test_web import equipo  # noqa: F401
    assert equipo["admin"].get("/empresas").status_code == 200
    assert equipo["creador"].get("/empresas").status_code == 403
    assert equipo["aprobador"].get("/empresas").status_code == 403


def test_administrador_crea_renombra_y_desactiva_empresas(equipo):
    from ayudas import publicar
    assert publicar(equipo["admin"], "/empresas/nueva", {"nombre": "EMPRESA C"}).status_code == 303
    assert "EMPRESA C" in equipo["admin"].get("/empresas").text
    from app import db
    with db.SessionLocal() as s:
        c = s.scalars(select(Empresa).where(Empresa.nombre == "EMPRESA C")).one()
    publicar(equipo["admin"], f"/empresas/{c.id}", {"nombre": "EMPRESA CE", "activo": "1"})
    publicar(equipo["admin"], f"/empresas/{c.id}", {"nombre": "EMPRESA CE"})  # sin «activo»: se desactiva
    with db.SessionLocal() as s:
        c = s.get(Empresa, c.id)
        assert (c.nombre, c.activo) == ("EMPRESA CE", False)


def test_usuarios_muestra_y_cambia_la_empresa(equipo):
    from ayudas import publicar
    from app import db
    with db.SessionLocal() as s:
        b = s.scalars(select(Empresa).where(Empresa.nombre == "EMPRESA B")).one()
        from app.modelos import Usuario
        carla = s.scalars(select(Usuario).where(Usuario.usuario == "carla")).one()
    assert "EMPRESA A" in equipo["admin"].get("/usuarios").text
    publicar(equipo["admin"], f"/usuarios/{carla.id}",
             {"nombre": "Carla", "rol": "creador", "activo": "1", "empresa_id": str(b.id)})
    with db.SessionLocal() as s:
        assert s.get(Usuario, carla.id).empresa_id == b.id
```

- [ ] **Paso 2: correr** `python -m pytest tests/test_empresas.py -q`. Esperado: FALLA («Empresa» no existe).
- [ ] **Paso 3: modelos.** Añadir `Empresa` y `Usuario.empresa_id/empresa` con las firmas de arriba.
- [ ] **Paso 4: servicios.** Implementar las funciones de empresa y las nuevas reglas de `crear_usuario`/`actualizar_usuario`. `nombre` se guarda con `limpiar`; `nombre_norm` con `normalizar`.
- [ ] **Paso 5: rutas y plantillas.** En `administracion.py`: `GET /empresas` (lista + formulario de alta), `POST /empresas/nueva` (campo `nombre`), `POST /empresas/{eid}` (campos `nombre`, `activo`), todas con `solo_admin`; los errores de `ErrorNegocio` se muestran con `aviso(..., "error")`. `usuario_nuevo` y `usuario_editar` leen `empresa_id` con `entero(...)`. En `usuarios.html` añadir una columna «Empresa» con un `<select name="empresa_id">` (opción vacía + empresas activas) en la tabla y en el formulario de alta; actualizar el texto de perfiles. `base.html`: enlace «Empresas» en el menú Administración y `'/empresas'` en su lista de rutas activas. `empresas.html` sigue el estilo de `catalogos.html`.
- [ ] **Paso 6: ayudas y fixture `equipo`** como se describe en Interfaces; añadir `empresa` a `personas` (el creador ya recibe una por defecto).
- [ ] **Paso 7: punto de control.** `python -m pytest -q` pasa completo.

---

### Tarea 3: Crédito por empresa (servicios y modelo)

**Archivos:**
- Modificar: `app/modelos.py`, `app/servicios.py`
- Crear: `tests/test_credito_empresas.py`
- Modificar: `tests/ayudas.py`

**Interfaces:**
- Consume (Tarea 2): `Empresa`, `servicios.empresa_de`, `ayudas.empresa`, `ayudas.crear_usuario`.
- Produce en `modelos`: `ProveedorCredito(id, proveedor_id, empresa_id, credito_tipo: str, credito_valor: Optional[int])` con unicidad `(proveedor_id, empresa_id)`; `Proveedor.creditos: List[ProveedorCredito]` (cascada `all, delete-orphan`); `Proveedor.credito_de(empresa_id: int) -> Optional[ProveedorCredito]`; `Proveedor.credito_texto_de(empresa_id: int) -> str` (usa `credito.texto`; «—» si no hay fila).
- Produce en `servicios`:
  - `empresas_visibles(db, usuario) -> List[Empresa]`: administrador y revisor, todas las activas; creador, solo la suya si está activa.
  - `puede_editar_credito(usuario, empresa_id: int) -> bool`: administrador siempre; creador solo su `empresa_id`; revisor nunca.
  - `aplicar_credito(db, p, empresa, tipo: Optional[str], valor: Optional[int], usuario) -> bool`: sin chequeo de permiso (lo usa el importador). Valida con `credito.validar`; empresa inactiva → `ErrorNegocio`; `tipo=None` borra la fila; crea/actualiza/borra y escribe un registro de historial (`tipo="cambio"`, `campo=f"Crédito · {empresa.nombre}"`, anterior «(vacío)» o `credito.texto(...)`, `sensible=False`). Devuelve si cambió algo. No toca estado de revisión ni `modificado_*`.
  - `guardar_credito(db, p, empresa, tipo, valor, usuario) -> bool`: si `not puede_editar_credito` → `ErrorNegocio("Solo puede cambiar el crédito de su empresa.")`; si no, `aplicar_credito`.
  - `proveedor_por_id(db, tipo_id_id: Optional[int], numero_id: Optional[str]) -> Optional[Proveedor]` (None si falta alguno).
- Produce en `ayudas`: `con_credito(sesion, p, empresa, usuario, tipo="dias", valor=30) -> None` (usa `aplicar_credito` y confirma).

- [ ] **Paso 1: escribir pruebas** en `tests/test_credito_empresas.py`:

```python
import pytest
from sqlalchemy import select

from app import servicios
from app.modelos import Historial
from app.servicios import ErrorNegocio
import ayudas


def _proveedor(sesion, personas):
    return ayudas.proveedor_aprobado(sesion, personas["creador"], personas["aprobador"])


def test_guardar_crear_actualizar_y_borrar(sesion, personas):
    p, a = _proveedor(sesion, personas), personas["creador"].empresa
    servicios.guardar_credito(sesion, p, a, "dias", 15, personas["creador"])
    assert p.credito_texto_de(a.id) == "15 días"
    servicios.guardar_credito(sesion, p, a, "dias", 0, personas["creador"])
    assert p.credito_texto_de(a.id) == "Contado"
    servicios.guardar_credito(sesion, p, a, None, None, personas["creador"])
    assert p.credito_de(a.id) is None and p.credito_texto_de(a.id) == "—"


def test_dos_empresas_un_proveedor(sesion, personas):
    p = _proveedor(sesion, personas)
    a, b = personas["creador"].empresa, ayudas.empresa(sesion, "EMPRESA B")
    ayudas.con_credito(sesion, p, a, personas["admin"], "dias", 0)
    ayudas.con_credito(sesion, p, b, personas["admin"], "dias", 15)
    assert (p.credito_texto_de(a.id), p.credito_texto_de(b.id)) == ("Contado", "15 días")
    assert p.credito_texto_de(ayudas.empresa(sesion, "EMPRESA C").id) == "—"


def test_guardar_credito_no_reabre_la_revision_y_queda_en_el_historial(sesion, personas):
    p, c = _proveedor(sesion, personas), personas["creador"]
    modificado = (p.modificado_por_id, p.modificado_en)
    servicios.guardar_credito(sesion, p, c.empresa, "dias", 30, c)
    sesion.commit()
    assert p.estado_aprobacion == "aprobado" and (p.modificado_por_id, p.modificado_en) == modificado
    h = sesion.scalars(select(Historial).order_by(Historial.id.desc())).first()
    assert (h.campo, h.valor_anterior, h.valor_nuevo, h.sensible) == (
        f"Crédito · {c.empresa.nombre}", "(vacío)", "30 días", False)


def test_permisos_por_empresa(sesion, personas):
    p, b = _proveedor(sesion, personas), ayudas.empresa(sesion, "EMPRESA B")
    with pytest.raises(ErrorNegocio, match="su empresa"):
        servicios.guardar_credito(sesion, p, b, "dias", 5, personas["creador"])
    with pytest.raises(ErrorNegocio):
        servicios.guardar_credito(sesion, p, personas["creador"].empresa, "dias", 5, personas["aprobador"])
    assert servicios.guardar_credito(sesion, p, b, "dias", 5, personas["admin"]) is True


def test_credito_invalido_y_empresa_inactiva(sesion, personas):
    p, c = _proveedor(sesion, personas), personas["creador"]
    with pytest.raises(ErrorNegocio, match="días de crédito"):
        servicios.guardar_credito(sesion, p, c.empresa, "dias", None, c)
    servicios.actualizar_empresa(sesion, c.empresa, c.empresa.nombre, False)
    with pytest.raises(ErrorNegocio):
        servicios.aplicar_credito(sesion, p, c.empresa, "dias", 5, personas["admin"])


def test_empresas_visibles(sesion, personas):
    b = ayudas.empresa(sesion, "EMPRESA B")
    nombres = lambda u: [e.nombre for e in servicios.empresas_visibles(sesion, u)]
    assert nombres(personas["admin"]) == nombres(personas["aprobador"]) == ["EMPRESA A", "EMPRESA B"]
    assert nombres(personas["creador"]) == ["EMPRESA A"]
    servicios.actualizar_empresa(sesion, b, b.nombre, False)
    assert nombres(personas["admin"]) == ["EMPRESA A"]


def test_proveedor_por_id(sesion, personas):
    p = _proveedor(sesion, personas)
    assert servicios.proveedor_por_id(sesion, p.tipo_id_id, p.numero_id).id == p.id
    assert servicios.proveedor_por_id(sesion, None, p.numero_id) is None
    assert servicios.proveedor_por_id(sesion, p.tipo_id_id, None) is None
```

- [ ] **Paso 2: correr** `python -m pytest tests/test_credito_empresas.py -q`. Esperado: FALLA (`guardar_credito` no existe).
- [ ] **Paso 3: implementar** modelo y servicios con las firmas de Interfaces. `empresas_visibles` y `puede_editar_credito` usan las constantes de rol de `modelos`.
- [ ] **Paso 4: punto de control.** `python -m pytest -q` pasa completo.

---

### Tarea 4: Alta que reconoce proveedor existente y crédito en la ficha

**Archivos:**
- Modificar: `app/rutas/proveedores.py`, `app/templates/proveedor_form.html`, `app/templates/proveedor_ficha.html`, `app/templates/_verificacion.html` (solo si hace falta)
- Crear: `app/templates/_credito_campos.html`, `tests/test_proveedor_empresas.py`
- Modificar: `tests/test_experiencia.py` (aserciones que leían `Proveedor.credito_tipo` tras el formulario: líneas 88–94 y las que dependan del texto de «Ya existe…»)

**Interfaces:**
- Consume: `servicios.empresa_de`, `empresas_visibles`, `puede_editar_credito`, `guardar_credito`, `proveedor_por_id`, `Proveedor.credito_de`.
- Produce en `rutas/proveedores.py`:
  - `_credito_de_formulario(formulario) -> Tuple[Optional[str], Optional[int]]`: la misma interpretación de los campos `credito`, `credito_dias`, `credito_dia` que hoy está dentro de `_datos_formulario`.
  - `_opcion_credito(tipo, valor) -> str`: devuelve `"contado"`, `"dias"`, `"dia_fijo"`, `"fin_mes"` o `""` (reemplaza la versión que recibe un diccionario).
  - `POST /proveedores/{pid}/credito` (`puede_editar`): campos `empresa_id` y los de crédito. Si `puede_editar_credito` es falso → 403; si no, `guardar_credito`, aviso «Crédito guardado.» y vuelve a la ficha.
- `_datos_formulario` y `_datos_de` **dejan de incluir** `credito_tipo`/`credito_valor`: editar un proveedor ya no toca el crédito.
- Macro `campos(sufijo, opcion, valor)` en `_credito_campos.html`: el `<select name="credito" id="credito{sufijo}">`, `credito_dias` y `credito_dia` con ids `credito_dias{sufijo}`/`credito_dia{sufijo}` y `data-mostrar-si="credito{sufijo}=dias"` / `=dia_fijo` (el JS busca el control por `id`, por eso cada fila de la ficha lleva su sufijo).

**Comportamiento:**
- `GET`/`POST /proveedores/nuevo` como **creador sin empresa activa** (`empresa_de(u)` es None): aviso de error «Su usuario no tiene empresa asignada. Pídale al administrador que se la asigne.» y redirección a `/proveedores`. El administrador no tiene esa restricción.
- Formulario de alta: para un creador incluye una tarjeta «Crédito con <empresa>» con la macro; para el administrador no hay campos de crédito (aviso: «El crédito se registra desde la ficha del proveedor»). El formulario de edición no lleva crédito.
- `POST /proveedores/nuevo`: antes de validar, `proveedor_por_id(...)` con el tipo y el número ya normalizados con `sin_espacios`. Si existe: **no se cambia ningún dato compartido**; si quien envía es creador y eligió una condición de crédito, se guarda con `guardar_credito` para su propia empresa (se ignora cualquier `empresa_id` del formulario); aviso «Ese proveedor ya estaba registrado: se añadió el crédito de su empresa. Los demás datos no se cambiaron; use Editar si hay que corregirlos.» (variantes sin crédito, y «…está desactivado» si `not activo`); redirige a su ficha. Si no existe, se crea como hoy y, si hay crédito, se guarda para la empresa del creador.
- `GET /proveedores/verificar`: cuando `pid` está vacío y hay un proveedor repetido, el aviso pasa a nivel `"alerta"` con el texto «Ese <tipo> ya está registrado. Al guardar solo se añadirá el crédito de su empresa; ábralo para ver o corregir los demás datos».
- Ficha: tarjeta «Crédito por empresa» con una fila por `empresas_visibles(u)`: nombre, texto del crédito y, si `puede_editar_credito`, un `<form method="post" action="/proveedores/{id}/credito">` por fila con `empresa_id` oculto y la macro con `sufijo="-{empresa.id}"`. Si no hay empresas visibles, el texto «Aún no hay empresas; el administrador debe crearlas en Administración → Empresas.» (o «Su usuario no tiene empresa asignada.» para un creador).

- [ ] **Paso 1: escribir pruebas** en `tests/test_proveedor_empresas.py` (usa `equipo`, `ids_catalogo`, `_crear_proveedor` de `test_web`):

```python
from sqlalchemy import select

from app import db
from app.modelos import Empresa, Proveedor, ProveedorCredito
from ayudas import formulario_proveedor, publicar
from test_web import _crear_proveedor, equipo  # noqa: F401


def _empresa_id(nombre):
    with db.SessionLocal() as s:
        return s.scalars(select(Empresa).where(Empresa.nombre == nombre)).one().id


def _creditos(pid):
    with db.SessionLocal() as s:
        filas = s.scalars(select(ProveedorCredito).where(ProveedorCredito.proveedor_id == pid)).all()
        return {f.empresa_id: (f.credito_tipo, f.credito_valor) for f in filas}


def test_el_creador_registra_con_el_credito_de_su_empresa(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo, credito="dias", credito_dias="15")
    assert _creditos(pid) == {_empresa_id("EMPRESA A"): ("dias", 15)}
    with db.SessionLocal() as s:
        assert s.get(Proveedor, pid).credito_tipo is None  # columna antigua intacta


def test_registrar_uno_existente_solo_agrega_el_credito(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo, credito="dias", credito_dias="15")
    r = publicar(equipo["creador2"], "/proveedores/nuevo", formulario_proveedor(
        ids_catalogo, nombre="OTRO NOMBRE", numero_cuenta="0000000001", credito="contado"))
    assert r.status_code == 303 and r.headers["location"] == f"/proveedores/{pid}"
    with db.SessionLocal() as s:
        assert s.scalars(select(Proveedor)).all().__len__() == 1
        assert s.get(Proveedor, pid).nombre == "DISTRIBUIDORA FICTICIA CIA. LTDA."
        assert s.get(Proveedor, pid).numero_cuenta == "0009876543"
    assert _creditos(pid) == {_empresa_id("EMPRESA A"): ("dias", 15), _empresa_id("EMPRESA B"): ("dias", 0)}
    assert "ya estaba registrado" in equipo["creador2"].get(f"/proveedores/{pid}").text


def test_el_id_con_espacios_tambien_se_reconoce(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo)
    r = publicar(equipo["creador2"], "/proveedores/nuevo",
                 formulario_proveedor(ids_catalogo, numero_id=" 0190 000000001 "))
    assert r.headers["location"] == f"/proveedores/{pid}"


def test_proveedor_desactivado_recibe_credito_sin_reactivarse(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo)
    publicar(equipo["creador"], f"/proveedores/{pid}/activo", {"activo": "0"})
    r = publicar(equipo["creador2"], "/proveedores/nuevo", formulario_proveedor(ids_catalogo, credito="contado"))
    assert r.headers["location"] == f"/proveedores/{pid}"
    with db.SessionLocal() as s:
        assert s.get(Proveedor, pid).activo is False
    assert _empresa_id("EMPRESA B") in _creditos(pid)
    assert "desactivado" in equipo["creador2"].get(f"/proveedores/{pid}").text


def test_el_creador_no_puede_escribir_el_credito_de_otra_empresa(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo)
    b = _empresa_id("EMPRESA B")
    r = publicar(equipo["creador"], f"/proveedores/{pid}/credito",
                 {"empresa_id": str(b), "credito": "contado"})
    assert r.status_code == 403 and b not in _creditos(pid)
    # En el alta, un empresa_id escondido se ignora: se usa siempre la empresa del usuario.
    r = publicar(equipo["creador"], "/proveedores/nuevo", formulario_proveedor(
        ids_catalogo, numero_id="0990000000001", empresa_id=str(b), credito="contado"))
    assert b not in _creditos(int(r.headers["location"].rsplit("/", 1)[1]))


def test_permisos_del_credito_en_la_ficha(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo)
    a, b = _empresa_id("EMPRESA A"), _empresa_id("EMPRESA B")
    datos = {"empresa_id": str(a), "credito": "dias", "credito_dias": "45"}
    assert publicar(equipo["aprobador"], f"/proveedores/{pid}/credito", datos).status_code == 403
    assert publicar(equipo["creador"], f"/proveedores/{pid}/credito", datos).status_code == 303
    assert publicar(equipo["admin"], f"/proveedores/{pid}/credito",
                    {"empresa_id": str(b), "credito": "fin_mes"}).status_code == 303
    assert _creditos(pid) == {a: ("dias", 45), b: ("fin_mes", None)}


def test_el_creador_solo_ve_su_empresa_en_la_ficha(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo, credito="dias", credito_dias="15")
    publicar(equipo["admin"], f"/proveedores/{pid}/credito",
             {"empresa_id": str(_empresa_id("EMPRESA B")), "credito": "contado"})
    assert "EMPRESA B" not in equipo["creador"].get(f"/proveedores/{pid}").text
    texto = equipo["aprobador"].get(f"/proveedores/{pid}").text
    assert "EMPRESA A" in texto and "EMPRESA B" in texto


def test_editar_no_toca_el_credito(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo, credito="dias", credito_dias="15")
    r = publicar(equipo["creador"], f"/proveedores/{pid}/editar",
                 formulario_proveedor(ids_catalogo, correo="nuevo@ficticio.example"))
    assert r.status_code == 303
    assert _creditos(pid) == {_empresa_id("EMPRESA A"): ("dias", 15)}


def test_un_creador_sin_empresa_activa_no_registra(equipo, ids_catalogo):
    publicar(equipo["admin"], f"/empresas/{_empresa_id('EMPRESA A')}", {"nombre": "EMPRESA A"})  # desactiva
    r = equipo["creador"].get("/proveedores/nuevo", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/proveedores"
    assert "no tiene empresa asignada" in equipo["creador"].get("/proveedores").text
```

- [ ] **Paso 2: correr** `python -m pytest tests/test_proveedor_empresas.py -q`. Esperado: FALLA.
- [ ] **Paso 3: implementar** helpers y rutas con las firmas de Interfaces y el Comportamiento.
- [ ] **Paso 4: plantillas** `_credito_campos.html`, `proveedor_form.html` (quitar la sección de crédito actual, añadir la tarjeta para creadores) y `proveedor_ficha.html` (reemplazar `<dt>Crédito</dt>` por la tarjeta «Crédito por empresa»). Leer primero `app/static/app.js` (`actualizarCondicionales`) para confirmar que los `id` con sufijo funcionan.
- [ ] **Paso 5: actualizar aserciones antiguas** en `tests/test_experiencia.py` (el crédito se lee ahora de `ProveedorCredito`).
- [ ] **Paso 6: punto de control.** `python -m pytest -q` pasa completo.

---

### Tarea 5: Vistas del revisor, validaciones y exportación

**Archivos:**
- Modificar: `app/rutas/proveedores.py` (`listado`, `exportar`), `app/rutas/aprobaciones.py`, `app/templates/_proveedores_tabla.html`, `app/templates/aprobaciones.html`, `app/validaciones.py`, `app/exportacion.py`
- Crear: `tests/test_vistas_revisor.py`
- Actualizar: `tests/test_proveedores.py:162-186` (la regla `sin_credito`), `tests/test_exportacion.py` (`libro_proveedores`)

**Interfaces:**
- Consume: `servicios.empresas_visibles`, `Proveedor.credito_texto_de`, `Proveedor.credito_de`.
- Produce: `exportacion.libro_proveedores(proveedores, empresas=()) -> Workbook`, con una columna `f"CREDITO {empresa.nombre}"` por empresa, **después de `CORREO`**, valor `credito.texto_excel(...)` o vacío; se elimina la columna `DIAS CREDITO` de este libro (el libro de pago masivo no cambia).
- Contexto `empresas_cols: List[Empresa]` en las plantillas del listado y de revisiones (`servicios.empresas_visibles(sesion, u)`).
- Regla nueva de validación `sin_credito`: el proveedor no tiene **ninguna** fila en `creditos`; título «Sin crédito en ninguna empresa»; detalle «No tiene condición de crédito en ninguna empresa.»

- [ ] **Paso 1: escribir pruebas** en `tests/test_vistas_revisor.py`:

```python
import io

import openpyxl

from app import db
from ayudas import publicar
from test_proveedor_empresas import _empresa_id
from test_web import _crear_proveedor, equipo  # noqa: F401


def _dos_creditos(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo, credito="contado")
    publicar(equipo["creador2"], f"/proveedores/{pid}/credito", {
        "empresa_id": str(_empresa_id("EMPRESA B")), "credito": "dias", "credito_dias": "15"})
    return pid


def test_el_revisor_ve_una_columna_por_empresa(equipo, ids_catalogo):
    _dos_creditos(equipo, ids_catalogo)
    texto = equipo["aprobador"].get("/proveedores").text
    for esperado in ("EMPRESA A", "EMPRESA B", "Contado", "15 días"):
        assert esperado in texto
    solo_a = equipo["creador"].get("/proveedores").text
    assert "EMPRESA A" in solo_a and "EMPRESA B" not in solo_a and "15 días" not in solo_a


def test_la_tarjeta_de_revision_muestra_los_creditos(equipo, ids_catalogo):
    _dos_creditos(equipo, ids_catalogo)
    texto = equipo["aprobador"].get("/aprobaciones").text
    assert "EMPRESA A" in texto and "EMPRESA B" in texto and "15 días" in texto


def test_empresa_desactivada_oculta_la_columna_y_conserva_los_creditos(equipo, ids_catalogo):
    pid = _dos_creditos(equipo, ids_catalogo)
    b = _empresa_id("EMPRESA B")
    publicar(equipo["admin"], f"/empresas/{b}", {"nombre": "EMPRESA B"})  # desactiva
    assert "EMPRESA B" not in equipo["aprobador"].get("/proveedores").text
    publicar(equipo["admin"], f"/empresas/{b}", {"nombre": "EMPRESA B", "activo": "1"})
    assert "15 días" in equipo["aprobador"].get("/proveedores").text


def test_sin_empresas_creadas_nada_se_rompe(cliente, ids_catalogo):
    from ayudas import CLAVE_ADMIN, entrar
    entrar(cliente, "admin", CLAVE_ADMIN)
    for ruta in ("/proveedores", "/proveedores/nuevo", "/aprobaciones", "/validaciones"):
        assert cliente.get(ruta).status_code == 200
    assert cliente.get("/proveedores/exportar").status_code == 200


def test_exportar_proveedores_con_una_columna_por_empresa(equipo, ids_catalogo):
    _dos_creditos(equipo, ids_catalogo)
    contenido = equipo["aprobador"].get("/proveedores/exportar").content
    hoja = openpyxl.load_workbook(io.BytesIO(contenido)).active
    filas = list(hoja.iter_rows(values_only=True))
    encabezado, datos = filas[0], dict(zip(filas[0], filas[1]))
    assert "CREDITO EMPRESA A" in encabezado and "CREDITO EMPRESA B" in encabezado
    assert "DIAS CREDITO" not in encabezado
    assert (datos["CREDITO EMPRESA A"], datos["CREDITO EMPRESA B"]) == ("CONTADO", "15")


def test_sin_credito_significa_sin_ninguna_empresa(equipo, ids_catalogo):
    _crear_proveedor(equipo["creador"], ids_catalogo, credito="")
    assert "Sin crédito en ninguna empresa" in equipo["admin"].get("/validaciones").text
```

- [ ] **Paso 2: correr** `python -m pytest tests/test_vistas_revisor.py -q`. Esperado: FALLA.
- [ ] **Paso 3: implementar.** `listado`: añadir `empresas_cols` al contexto y `selectinload(Proveedor.creditos)` a la consulta paginada. `_proveedores_tabla.html`: reemplazar la columna «Crédito» por un `<th>` y un `<td>` por empresa de `empresas_cols` (`{{ p.credito_texto_de(e.id) }}`) y ajustar el `colspan` del mensaje vacío a `6 + empresas_cols|length`. `aprobaciones.html`/`aprobaciones.py`: pasar `empresas_cols` y mostrar una línea «<empresa>: <crédito>» por empresa en lugar de `Crédito`. `validaciones.py`: nueva regla. `exportar`: pasar `empresas=servicios.empresas_visibles(sesion, u)`.
- [ ] **Paso 4: actualizar** `tests/test_proveedores.py` (la prueba de `sin_credito` crea créditos con `ayudas.con_credito`) y `tests/test_exportacion.py::test_exportar_listado_de_proveedores` (nuevo encabezado, `ESTADO REVISION`).
- [ ] **Paso 5: punto de control.** `python -m pytest -q` pasa completo.

---

### Tarea 6: Importación del Excel con empresa

**Archivos:**
- Modificar: `app/importacion.py`, `app/cli.py`, `tests/test_importacion.py`

**Interfaces:**
- Consume: `servicios.aplicar_credito`, `servicios.empresas_activas`, `servicios.normalizar`.
- Produce: `importacion.importar(db, ruta, usuario, empresa: Optional[Empresa] = None) -> Resumen`; `Resumen.creditos: int` (créditos guardados) y una línea nueva en `lineas()`: «Créditos importados: N» o, si no se indicó empresa, «Créditos del Excel: no importados (indique --empresa)».
- CLI: opción `--empresa NOMBRE` de `importar-proveedores`; se busca entre las empresas activas por `normalizar`; si no existe → «ERROR: la empresa indicada no existe; créela antes en Administración → Empresas.» y código 1.

**Comportamiento:** el diccionario `datos` que se pasa a `validar_datos` y `crear_proveedor` **ya no lleva** `credito_tipo`/`credito_valor`; el crédito leído se guarda aparte y, solo si hay `empresa`, se aplica con `aplicar_credito` justo después de crear el proveedor. La alarma «Condición de crédito no reconocida» se mantiene. Proveedores que ya existían no se tocan (como hoy, tampoco sus créditos).

- [ ] **Paso 1: actualizar y ampliar pruebas** en `tests/test_importacion.py`:
  - Las aserciones de las líneas 70–74, 178–179 leen `ProveedorCredito` de la empresa indicada en lugar de `Proveedor.credito_tipo`.
  - Nueva prueba `test_sin_empresa_no_importa_creditos`: `importar(db, ruta, usuario)` crea los proveedores, `Proveedor.credito_tipo is None`, no hay filas en `proveedor_creditos` y `resumen.lineas()` contiene «no importados».
  - Nueva prueba `test_la_empresa_inexistente_en_el_cli_da_error`: el CLI con `--empresa NOEXISTE` devuelve 1 y escribe «no existe».
- [ ] **Paso 2: correr** `python -m pytest tests/test_importacion.py -q`. Esperado: FALLA.
- [ ] **Paso 3: implementar** según Comportamiento.
- [ ] **Paso 4: punto de control.** `python -m pytest -q` pasa completo.

---

### Tarea 7: Documentación y verificación final

**Archivos:** `README.md`, `CHANGELOG.md`, `PROMPT.md`

- [ ] **Paso 1:** en `README.md` y `PROMPT.md`, cambiar «aprobación/aprobador» por «revisión/revisor» en el texto visible, y añadir una sección «Empresas y crédito por empresa»: cómo crear empresas, asignar la empresa a cada creador, qué ve cada perfil y la opción `--empresa` de la importación.
- [ ] **Paso 2:** en `CHANGELOG.md` añadir una entrada nueva (sin reescribir las anteriores) que liste los cambios, indique que **la facturación por empresa queda pendiente** y que **no se incluye migración de datos**: no arrancar contra la base anterior.
- [ ] **Paso 3: verificación completa.** `python -m pytest -q` debe terminar en verde. Después, con una base nueva y siguiendo el arranque del README: iniciar sesión como administrador, crear dos empresas y dos creadores, registrar un proveedor con cada creador usando el mismo número de ID y comprobar en pantalla que queda **un solo** proveedor con dos créditos, y que el revisor ve las dos columnas. Anotar en el informe final qué se probó en el navegador y qué solo con pruebas automáticas.

---

## Autorrevisión

- **Cobertura del spec:** empresas (T2), empresa por usuario (T2), crédito por empresa (T3), carga del proveedor existente (T4), columnas del revisor (T5), renombre (T1), historial del crédito con empresa (T3), importación con empresa (T6), documentación (T7). Fuera de alcance, como el spec: facturas por empresa, pago masivo, migración.
- **Tipos consistentes:** `aplicar_credito`/`guardar_credito` (T3) son las que usan T4 y T6; `empresas_visibles` (T3) alimenta T4 y T5; `credito_texto_de` (T3) se usa en T5.
- **Deuda conocida:** `Proveedor.credito_tipo/credito_valor`, `servicios.aplicar_cambios` (rama `credito_tipo`) y `crear_proveedor` (copia de `credito_*`) siguen vivos solo para facturación; se retiran cuando se reactive.
