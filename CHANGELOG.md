# Changelog — Manejo de Proveedores

## [Sin publicar] — 2026-11-13 · Sesión 1 (en pausa)

**Estado: código escrito, nada ejecutado.** El trabajo se detuvo a pedido del usuario antes de terminar. En esta máquina solo se desarrolla; la app se probará en otra. Lo único comprobado es que los 29 archivos Python no tienen errores de sintaxis y que toda plantilla referenciada existe. No se instalaron dependencias, no se corrieron las pruebas, no se arrancó la app y no se construyó la imagen de Docker.

### Decisiones tomadas en la sesión

- **Stack**: Python 3.11 + FastAPI + Jinja2 + HTMX + SQLite, un solo contenedor. Interfaz en español.
- **No se importan proveedores del Excel.** La app arranca vacía y el personal los registra a mano. Del Excel se conserva solo la estructura (campos, formato de pago masivo, catálogos).
- **Catálogo de instituciones financieras**: se mantiene completo y con los mismos códigos del Excel, porque los asigna el Estado ecuatoriano. Viene incluido en la app (`app/semilla/instituciones_financieras.csv`, 459 filas) y se carga al crear la base.
- **`Hoja 2`** (lista de apoyo CREADO / CREDITO): se ignora.
- **Dos perfiles de trabajo más el administrador**:
  - *Creador*: registra y edita proveedores y facturas.
  - *Aprobador*: aprueba o rechaza proveedores en la pantalla "Aprobaciones".
  - *Administrador*: usuarios, catálogos, configuración.
- **Flujo de aprobación**: proveedor nuevo queda Pendiente; si se cambian sus datos bancarios o de identificación vuelve a Pendiente; nadie aprueba lo que él mismo creó o modificó; solo los aprobados entran en el pago masivo.
- **Alarmas**: avisos de vencimiento dentro de la app (vencido / vence hoy / próximos N días). Envío por correo preparado pero apagado por defecto. *Supuesto sin confirmar por el usuario.*
- **Condición de crédito**: tres tipos — N días (contado = 0), fin de mes, día fijo del mes. *Supuesto sin confirmar.*
- **Exportación de pago masivo**: mismas columnas y orden que `Hoja 1`.
- **Moneda por defecto**: USD.

### Escrito (sin ejecutar)

- **Núcleo** (`app/`): `main.py`, `web.py`, `config.py`, `db.py`, `modelos.py`, `servicios.py`, `seguridad.py`, `credito.py`, `validaciones.py`, `exportacion.py`, `catalogos.py`, `tareas.py`, `cli.py`.
- **Rutas** (`app/rutas/`): `sesion`, `proveedores`, `aprobaciones`, `facturas`, `administracion`.
- **Plantillas** (`app/templates/`): inicio de sesión, panel, proveedores (lista, ficha, formulario), aprobaciones, facturas, historial, validaciones, catálogos, usuarios, configuración, cambio de clave, error.
- **Estáticos**: `estilo.css` y `htmx.min.js` local (la app no depende de internet).
- **Semilla**: catálogo de instituciones financieras con sus códigos oficiales.
- **Pruebas** (`tests/`): 85 pruebas en 7 archivos — crédito, catálogos, aprobación, proveedores, exportación, facturas y web. Usan datos inventados.
- **Despliegue**: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `requirements.txt`, `requirements-dev.txt`, `pytest.ini`.
- **`.gitignore`**: excluye `datos/`, la base de datos, respaldos, `.env`, archivos Excel y el entorno virtual.

### Sesión 12 · 2026-11-24 · Créditos antiguos a Hiltexpoy e importación de las demás empresas

- **`migrar-creditos`** (comando nuevo): pasa el crédito de las columnas antiguas a una empresa. Aplicado en la base real: 135 créditos a **Hiltexpoy** (dato indicado por el usuario: lo cargado era de esa empresa).
- **Importador**: acepta los encabezados de los Excel de las otras empresas (`Tipo de Identificación`, `Identificación`, `Nombre Beneficiario`, `Banco`, `Tipo de Cuenta`, `Cuenta`, `Correo Electrónico`), «Cuenta Corriente/Ahorros» y bancos abreviados («B. DEL PICHINCHA»). «FDM» se lee como fin de mes.
- **Proveedor ya registrado**: con `--empresa`, el importador le añade el crédito de esa empresa si no lo tenía (antes lo ignoraba por completo). Sus datos no se tocan.
- **Carga real** (cada paso con su respaldo): Hiltexpoy (`DATOS BANCARIOS PROVEEDORES.xlsx`, hoja HILTEXPOY): 9 nuevos y 10 créditos, 2 filas sin número de ID omitidas. Interfibra: 52 nuevos, sin créditos (el libro no trae esa columna), 2 omitidas. Jaltextiles: 45 nuevos y 101 créditos, 1 con crédito no reconocido (fila 113). Resultado: 252 proveedores (59 revisados, 193 pendientes); créditos: Hiltexpoy 145, Jaltextiles 101.
- **Corrección posterior (mismo día)**: el usuario aclaró los archivos: `HILTEXPOY.xlsx` es el de Hiltexpoy y `PROVEEDORES RIBEL.xlsx` (el «archivo madre» de la primera carga, con las hojas RIBEL e HILTEXPOY) trae a Ribel. Los créditos antiguos, que mezclaban ambas hojas, se habían pasado todos a Hiltexpoy. Se igualó el crédito de cada empresa a su hoja: Hiltexpoy 124 iguales, 5 corregidos y 16 quitados (eran de proveedores solo de Ribel); Ribel 87 créditos nuevos. Todo con respaldo (`proveedores-20261124-145249.db`) y anotado en el historial. Estado final: 252 proveedores; créditos Hiltexpoy 129, Jaltextiles 101, Ribel 87.
- **Pendiente del usuario**: revisar las filas omitidas (ID vacío, mismo ID con otra cuenta, tipo de cuenta «Pro Pyme» no existente), la fila de Ribel sin proveedor en la base y asignar crédito a Interfibra (su libro no trae esa columna).
- Pruebas: +3 y 1 caso nuevo (248 en total, todas pasan; se corren en `.venv` local).

### Sesión 11 · 2026-11-24 · Migración de columnas y encabezados de crédito más cortos

- **Migración automática de columnas** (`app/db.py`, `_agregar_columnas_faltantes`): tras `create_all`, agrega con `ALTER TABLE` las columnas `usuarios.empresa_id` e `historial.empresa_id` (con el índice `ix_historial_empresa_id`) si una base anterior no las tiene. Es repetible y no pierde datos. Los usuarios existentes quedan con `empresa_id` vacío: a cada creador hay que asignarle su empresa.
- **Sigue pendiente**: los registros viejos del historial (205, todos de alta o de revisión) quedan sin empresa.
- **Encabezados de crédito** en el listado de proveedores: «Créd. XXX» (3 primeras letras de la empresa) con el nombre completo en el `title`, para ahorrar ancho.
- Prueba nueva `tests/test_migracion.py` (base antigua → columnas añadidas, usuario conservado, segundo arranque sin error). Se ejecuta desde la sesión 12.

### Sesión 10 · 2026-11-17 · Empresas, crédito por empresa y «Revisión»

Plan: `docs/superpowers/plans/2026-11-17-empresas-credito-revision.md` (spec en `docs/superpowers/specs/`). Rama `feat/empresas-credito-revision`, sin commit.

- **«Aprobación» → «Revisión» (solo lo visible)**: menú y pantalla «Revisiones», perfil «Revisor», estado «Revisado», botón «Marcar como revisado», mensajes, historial («Estado de revisión»), importador, CLI y la columna `ESTADO REVISION` de la exportación de proveedores. No cambian rutas (`/aprobaciones`), clases CSS, funciones ni valores guardados (`"aprobado"`). Una prueba recorre las pantallas y falla si aparece «aprob…» en el texto visible.
- **Empresas**: tabla nueva `empresas`; pantalla Administración → Empresas (crear, renombrar, desactivar; el nombre no se repite sin importar mayúsculas ni tildes).
- **Empresa por usuario**: `usuarios.empresa_id`. Obligatoria para el creador activo; solo el creador la guarda. Columna «Empresa» en Usuarios.
- **Crédito por empresa**: tabla nueva `proveedor_creditos` (una fila por proveedor y empresa). El creador ve y cambia solo el de su empresa (comprobado en el servidor; un `empresa_id` manipulado se rechaza con 403 o se ignora); el revisor ve todos y no cambia ninguno; el administrador cambia cualquiera desde la ficha. El crédito **no** es dato sensible: cambiarlo no reabre la revisión. Queda en el historial como «Crédito · EMPRESA».
- **Alta de un proveedor ya registrado** (mismo tipo y número de ID, también con espacios): no se crea otro ni se cambian sus datos; solo se añade el crédito de la empresa del creador y se abre su ficha, avisando si está desactivado. El formulario lo avisa mientras se escribe.
- **El formulario de proveedor ya no lleva el crédito**, salvo el alta de un creador («Crédito con <su empresa>»). Editar un proveedor no toca el crédito. Ficha con la tarjeta «Crédito por empresa».
- **Revisor**: listado con una columna de crédito por empresa activa; «Revisiones» muestra «EMPRESA: crédito» por cada una; la exportación de proveedores trae `CREDITO <EMPRESA>` después de `CORREO` y ya no `DIAS CREDITO`. Una empresa desactivada desaparece de las columnas y sus créditos reaparecen al activarla.
- **Historial**: el creador no ve los cambios de crédito de otras empresas (ficha y «Historial de cambios»). El filtro usa la columna nueva `historial.empresa_id` y no el nombre de la empresa, así que renombrar una empresa (o darle a otra su nombre anterior) no muestra ni oculta registros que no correspondan; el texto «Crédito · EMPRESA» guarda el nombre que tenía la empresa en ese momento.
- **Validaciones**: «Sin crédito en ninguna empresa» reemplaza a «Sin condición de crédito».
- **Importación**: nueva opción `--empresa NOMBRE`; el crédito del Excel se guarda para esa empresa. Sin `--empresa` se importan los proveedores sin crédito y el resumen lo dice; una empresa inexistente da error.
- Pruebas: +29 en 5 archivos nuevos (`test_revision_textos`, `test_empresas`, `test_credito_empresas`, `test_proveedor_empresas`, `test_vistas_revisor`) y 3 en `test_importacion`; aserciones antiguas ajustadas a los textos y al crédito por empresa. Las pruebas corren en un `.venv` local con `requirements-dev.txt`.
- **Pendiente — facturación por empresa**: la facturación (apagada) sigue calculando vencimientos con las columnas antiguas `proveedores.credito_tipo/credito_valor`, que ninguna pantalla escribe ya. Se retoma cuando se reactive la facturación.
- **Migración de datos**: ver sesión 11 (solo cubre las columnas nuevas; los créditos antiguos no se trasladan).

### Sesión 9 · 2026-11-16 · Los aprobados salen de «Validaciones»

- Decisión del usuario: una vez aprobado, el proveedor ya fue revisado y no debe aparecer en «Validaciones» (p. ej. un RUC de sociedad dudoso). Solo se listan los pendientes y rechazados.
- Los duplicados (cuenta, ID, nombre) se siguen buscando contra **todos** los proveedores: un pendiente que repite la cuenta de uno aprobado sigue avisándose.
- Si a un aprobado se le cambia un dato sensible vuelve a Pendiente y sus avisos reaparecen. La ficha tampoco muestra avisos de validación a los aprobados.
- Pruebas: +1 → 209/209.

### Sesión 8 · 2026-11-16 · Correos repetidos ya no se avisan

- Decisión del usuario: varios proveedores comparten correo porque es el de la persona de compras, que gestiona los pagos directo con ellos. Se quitó el grupo «Mismo correo en varios proveedores» de «Validaciones» (eran 58 avisos de ruido sobre los 146 importados). Siguen los avisos de correo vacío o mal formado.

### Sesión 7 · 2026-11-16 · Validación de cédula y RUC

- Nuevo `app/identificacion.py`: cédula (módulo 10, provincia, tercer dígito), RUC de persona natural (cédula + establecimiento) y RUC de sociedades privadas/públicas (módulo 11). Reglas contrastadas con python-stdnum (`stdnum/ec/ci.py` y `ruc.py`); las otras fuentes consultadas (guías, gists, paquetes) no coincidían entre sí en el RUC de sociedades.
- **Bloquea** (no se guarda): cédula y RUC de persona natural inválidos. **Solo avisa**: RUC de sociedades (6 y 9) y tercer dígito 7/8, porque el SRI no garantiza el módulo 11 y hay RUC reales que no lo cumplen (hilo de python-stdnum-users, 2021). Pasaportes no se revisan.
- Pedido del usuario confirmado: en sociedades el RUC **nunca bloquea**; además de avisar al escribir, al guardar (alta o edición) se muestra una advertencia «se guardó igual; confírmelo en el SRI» y queda en «Validaciones» y en la ficha. Cubierto por prueba de punta a punta (208/208).
- Conectado en tres lugares: al guardar (`servicios.validar_datos`), aviso en vivo en el formulario (`/proveedores/verificar`) y la pantalla «Validaciones» (dos grupos nuevos, también para lo ya guardado).
- Efecto sobre los 146 proveedores importados (solo conteos): las 55 cédulas y los 2 RUC de persona natural son válidos; 84 de 89 RUC de sociedades cumplen el módulo 11 y 5 quedan como «dudosos» para confirmar en el SRI.
- Pruebas: +26 (`tests/test_identificacion.py`, con números fabricados y los ejemplos públicos de python-stdnum) y 4 pruebas existentes ajustadas porque usaban números de prueba que ya no pasan el verificador → 207/207.
- Sin verificar: contra la documentación oficial del SRI (no se encontró; solo fuentes secundarias y python-stdnum).

### Sesión 6 · 2026-11-16 · Importación de proveedores desde Excel

- Nuevo comando `python -m app.cli importar-proveedores RUTA --usuario U [--aplicar]` (módulo `app/importacion.py`): simula por defecto; con `--aplicar` respalda y guarda en una transacción. Detecta las hojas por encabezados y reutiliza el alta manual (historial y validaciones). Se puede repetir sin duplicar.
- Decisión del usuario: lo marcado `OK` en REGISTRADO ya estaba aprobado → se importa **aprobado** (con constancia en el historial); lo demás, pendiente.
- Carga real (libro «DATOS BANCARIOS PROVEEDORES», hojas RIBEL y HILTEXPOY): 227 filas con datos → **146 importados** (59 aprobados, 87 pendientes), 70 repetidos idénticos entre las dos hojas, 11 omitidos (2 sin tipo de ID, 2 sin número de ID, 1 RUC de largo incorrecto y 6 con otra cuenta/banco para un mismo ID). 5 importados con algo que revisar (2 bancos fuera del catálogo, 2 correos inválidos, 1 crédito no reconocido).
- Pruebas: +11 (`tests/test_importacion.py`, con libros inventados) → 181/181.
- Pendiente del usuario: decidir qué hacer con los 11 omitidos y con los proveedores que tienen dos cuentas (la app guarda una por proveedor).

### Sesión 5 · 2026-11-16 · Facturación oculta (solo proveedores)

- Decisión del usuario: por ahora solo se registran proveedores; las funciones de facturación se ocultan **sin borrar código**.
- Nueva variable `FACTURACION_ACTIVA` (por defecto `false`; documentada en `.env.example` y README). Apagada:
  - todo el router de facturas responde 404 (incluye pago en lote, vista previa y exportación de pago masivo);
  - sin «Panel» ni «Facturas» en el menú; `/` redirige a `/proveedores`;
  - la ficha, aprobaciones, usuarios, configuración y validaciones no mencionan facturas ni alarmas; las rutas `/configuracion` (días de aviso y contrapartida) y `/configuracion/revisar-alarmas` dan 404;
  - la tarea diaria solo respalda (no revisa alarmas ni envía correo).
- Las pruebas arrancan con el interruptor en `true` (conftest) para conservar la cobertura de facturas; +16 pruebas del modo apagado (`tests/test_sin_facturacion.py`) → 170/170.
- Verificado en Firefox con la app real: el menú queda en Proveedores / Aprobaciones / Control / Administración y `/facturas` da 404. Las tablas de facturas no se tocan.
- Los estilos y el JavaScript de facturas siguen cargándose (inofensivos); no se separaron.

### Sesión 4 · 2026-11-16 · Mejoras de uso (revisión de experiencia de usuario)

Hecho a partir de una revisión de las pantallas; sin dependencias nuevas ni internet (`app/static/app.js` propio + HTMX local). Todo es mejora progresiva: sin JavaScript los formularios siguen funcionando.

- **Buscador de bancos y de proveedores** (en vez de listas de 459 y ~1000 entradas): escribir filtra sin tildes, flechas + Enter, «Más usados» arriba.
- **Vista previa del vencimiento** al registrar una factura (`GET /facturas/vencimiento`, misma regla de `credito.calcular_vencimiento`), con día de la semana y aviso si el proveedor no está aprobado o no tiene crédito definido.
- **Condición de crédito**: solo se muestra el campo que corresponde (días / día del mes).
- **Barra de selección de facturas**: «N seleccionadas · total», **Exportar pago masivo** y **Marcar pagadas** (nuevo `POST /facturas/pagar-lote`); botones desactivados sin selección.
- **Panel**: tarjetas con el monto como cifra principal y enlaces a su tabla; se ocultan las tablas vacías; «Todo al día» cuando no hay nada.
- **Menú**: «Control» (Validaciones, Historial) y «Administración» (Catálogos, Usuarios, Configuración) como desplegables.
- **Proveedores**: ordenar por columna y páginas de 50 (`orden`, `dir`, `pagina`), conservando filtros y búsqueda en vivo.
- **Facturas**: filtros en vivo con la URL actualizada.
- **Formularios**: validación al salir del campo (largo de cédula/RUC según el tipo, correo) y aviso en vivo de identificación o cuenta ya usadas por otro proveedor (`GET /proveedores/verificar`).
- **Pantallas vacías** que guían al primer paso; avisos con ✕ (los de éxito se cierran solos); «Guardar y registrar otra»; el navegador puede recordar el usuario; ícono de la app; foco visible con teclado.
- Las respuestas parciales de HTMX ya no consumen los avisos pendientes.
- **Pruebas**: +13 (`tests/test_experiencia.py`) → 154/154. Además, recorrido en Firefox headless (Selenium, fuera del proyecto): buscador, validaciones, crédito condicional, aviso de duplicados, vista previa, barra de selección, menús, orden y vista móvil de 390 px. Ese recorrido encontró un error real (la barra de selección no se actualizaba) que ya está corregido.
- README: el procedimiento de restauración ahora borra `proveedores.db-wal` y `-shm` antes de copiar el respaldo.
- Sin verificar: Chrome/Edge/Safari (solo Firefox), lectores de pantalla, y la máquina Windows de destino.

### Sesión 3 · 2026-11-16 (primera ejecución, Docker en Linux)

- `docker compose build`: las dependencias de `requirements*.txt` instalan juntas sin conflictos.
- `pytest` en el contenedor: 139/141 al inicio. Las 2 fallas eran de las pruebas, no de la app; corregidas → **141/141**.
  - `test_nadie_aprueba_su_propia_modificacion`: esperaba «usted mismo creó» para el creador, pero el servidor (correctamente) responde antes «Su perfil no permite aprobar».
  - `test_no_se_reabre_una_anulada_si_hay_otra_con_el_mismo_numero`: faltaba `commit()` tras anular (la sesión tiene `autoflush=False`; las rutas sí hacen commit).
- App arriba con `docker compose up -d`, healthcheck `healthy`, sin sesión redirige a `/login`.
- Recorrido completo por HTTP contra la app en marcha (datos inventados): login admin → catálogo con 459 instituciones → alta de creador y aprobador → creador registra proveedor (queda Pendiente, no puede aprobarlo: 403) → aprobador lo aprueba → facturas vencida / vence hoy / próxima aparecen en el panel → exportación de pago masivo con las 15 columnas de `Hoja 1` → exportación de proveedores → cambio de cuenta devuelve a Pendiente, queda en historial y bloquea la exportación → todas las pantallas de administración responden 200 → respaldo manual creado en `respaldos/`.
- Restauración desde respaldo probada (en Linux con `$(pwd)` en lugar de `%cd%`).
- Sin verificar aún: envío de correo, tarea diaria a la hora programada, carga de catálogos desde Excel (no hay `datos/proveedores.xlsx` en esta máquina), interfaz en navegador real, y la máquina Windows de destino.

### Sesión 2 · 2026-11-16 (sin ejecutar nada; Docker no está en esta máquina)

- Se escribió `README.md`.
- Revisión de solo lectura por tres agentes (code-reviewer, security-engineer, devops-engineer). Resultado: 0 bloqueantes. Las 14 versiones de `requirements*.txt` existen en PyPI (no se comprobó su compatibilidad entre sí). Los campos usados en las 17 plantillas existen en el modelo, no queda importación de proveedores y la separación de funciones se valida en el servidor.
- Corregido (sin ejecutar las pruebas): reabrir una factura anulada ya no permite duplicar número (+1 prueba); un respaldo fallido se borra; `ADMIN_CLAVE` ya no trae valor de ejemplo y el administrador no se crea con el valor antiguo; `TAREAS_ACTIVAS` documentada en `.env.example`; nota de permisos de `respaldos/` en Linux.
- **Decisiones del usuario pendientes** (hallazgos MAJOR): formato de `TIPO ID` / `TIPO` / `FORMA DE PAGO` en el pago masivo; HTTPS y cookie segura; doble control en pagos y reapertura de facturas; bitácora de altas y cambios de rol de usuarios; si el administrador puede aprobar; enmascarar cuentas y auditar la exportación de proveedores; qué cambios (correo, crédito) devuelven a Pendiente.

### Pendiente para la próxima sesión

1. ~~README~~ y ~~revisión de código~~: hechos en la sesión 2.
3. **Versiones de `requirements.txt`**: existen en PyPI; falta confirmar que instalan juntas al construir la imagen.
4. **Códigos repetidos en el catálogo de instituciones**: el Excel trae 5 códigos repetidos. Falta listarlos y que el usuario decida qué hacer con ellos.
5. **Confirmar con el usuario** los dos supuestos marcados arriba (alarmas y condición de crédito) y el valor de `CONTRAPARTIDA` en el archivo de pago.
6. **Primera prueba en la máquina de destino** (requiere Docker instalado allí):
   - `docker compose up -d` y entrar con el administrador inicial;
   - correr las pruebas dentro del contenedor;
   - comprobar que el catálogo de instituciones cargó con sus códigos;
   - crear los usuarios creador y aprobador;
   - recorrido completo: crear proveedor → aprobarlo con el otro usuario → registrar factura → verla en el panel el día que corresponde → exportar pago masivo.

### Notas

- El Excel `datos/proveedores.xlsx` es confidencial: no se sube a ningún servicio ni a git, y no se copiaron datos de proveedores a ningún archivo del proyecto.
- `PROMPT.md` es el encargo original; este changelog recoge los cambios de alcance posteriores, que tienen prioridad sobre él.
