# Manejo de Proveedores

Aplicación web para llevar el control de proveedores (identificación, datos bancarios, condición de crédito), registrar facturas, avisar de vencimientos y generar el archivo de pago masivo al banco. Interfaz en español. Python 3.11 + FastAPI + Jinja2 + HTMX + SQLite, en un solo contenedor.

> **Estado:** probada en Docker (Linux) el 2026-11-16: imagen construida, 154 pruebas pasan, recorrido completo por HTTP y recorrido de pantallas en Firefox verificados. Falta repetirlo en la máquina Windows de destino. Ver `CHANGELOG.md`.

## Requisitos

- Docker con Docker Compose, en el equipo donde correrá la app.

## Levantarla

1. Copie `.env.example` como `.env` y complete al menos:
   - `ADMIN_USUARIO`, `ADMIN_NOMBRE`, `ADMIN_CLAVE`: primer administrador (solo se usa si aún no existe ningún usuario).
   - `CLAVE_SESION`: texto largo y al azar (40+ caracteres). Para generarlo:
     `docker compose run --rm app python -c "import secrets; print(secrets.token_urlsafe(48))"`
2. `docker compose up -d`
3. Abra `http://NOMBRE-O-IP-DEL-EQUIPO:8000` (el puerto se cambia con `PUERTO` en `.env`).

La app reinicia sola con el equipo (`restart: unless-stopped`). Arranca **vacía**: los proveedores se registran a mano o se importan desde un Excel (ver «Importar proveedores»). El catálogo de instituciones financieras (con los códigos oficiales) viene incluido y se carga al crear la base.

> **Linux:** la app corre con el usuario 10001. Antes del primer arranque cree la carpeta de respaldos con permisos para él: `mkdir respaldos && sudo chown 10001 respaldos`. Si no, el respaldo diario falla por permisos. En Docker Desktop (Windows) no hace falta.

## Perfiles

| Perfil | Puede |
|---|---|
| Creador | Trabaja para una empresa: registra y edita proveedores (y facturas) y el crédito que su empresa tiene con ellos |
| Revisor | Ve el crédito de todas las empresas y marca como revisados o rechaza proveedores en «Revisiones» |
| Administrador | Empresas, usuarios, catálogos y configuración; puede cambiar el crédito de cualquier empresa |

Flujo de revisión: un proveedor nuevo queda *Pendiente*; si se cambian sus datos bancarios o de identificación vuelve a *Pendiente*; nadie revisa lo que él mismo creó o modificó; solo los proveedores revisados entran en el pago masivo. Lo que se comprueba al revisar es que el proveedor esté creado en la otra plataforma. Cambiar el crédito de una empresa **no** devuelve el proveedor a *Pendiente*.

## Empresas y crédito por empresa

Cada proveedor existe **una sola vez**, pero cada empresa le maneja su propio crédito (contado, 15 días, fin de mes…).

1. **Crear las empresas**: Administración → Empresas. Se pueden renombrar y desactivar; una empresa desactivada desaparece de las pantallas, pero sus créditos se conservan y reaparecen al activarla.
2. **Asignar la empresa a cada creador**: Administración → Usuarios, columna «Empresa». Es obligatoria para el perfil Creador; un creador sin empresa activa no puede registrar proveedores.
3. **Qué ve cada perfil**:
   - El creador ve y cambia solo el crédito de su empresa (en el listado, la ficha y el historial).
   - El revisor ve una columna de crédito por cada empresa activa en el listado, en «Revisiones» y en la exportación; no puede cambiarlos.
   - El administrador ve todas y puede cambiar cualquiera desde la ficha del proveedor.
4. **Proveedor ya registrado**: si un creador registra un proveedor con un tipo y número de ID que ya existe, la app no crea otro ni cambia sus datos: solo añade el crédito de la empresa del creador y lo lleva a la ficha. El formulario lo avisa mientras se escribe.
5. Los cambios de crédito quedan en el historial como «Crédito · NOMBRE DE LA EMPRESA».

> **Sin migración todavía:** esta versión necesita una base nueva. No la arranque contra una base creada con una versión anterior (le falta la empresa de los usuarios); la migración de los datos actuales se definirá aparte.

## Facturas (apagadas por ahora)

Por ahora la app solo registra proveedores. Las facturas, el panel de pagos, las alarmas de vencimiento y el archivo de pago masivo están **ocultos, no eliminados**: se controlan con `FACTURACION_ACTIVA` en `.env` (por defecto `false`).

- Apagado: no aparecen «Panel» ni «Facturas» en el menú, el inicio es la lista de proveedores, y las direcciones `/facturas…` responden «no existe». La tarea diaria solo hace el respaldo.
- Para volver a usarlas: poner `FACTURACION_ACTIVA=true` en `.env` y ejecutar `docker compose up -d` (no basta `restart`). Los datos de facturas que ya existan en la base se conservan.
- La facturación todavía no usa el crédito por empresa: calcula los vencimientos con el crédito antiguo del proveedor, que ya no se edita en pantalla. La facturación por empresa queda pendiente.

## Validación de cédula y RUC

Al guardar un proveedor se revisa el número de identificación con el dígito verificador oficial (módulo 10 y módulo 11), contrastado con la implementación de referencia de [python-stdnum](https://arthurdejong.org/python-stdnum/):

| Caso | Qué se revisa | Si no cumple |
|---|---|---|
| Cédula | 10 dígitos, provincia (01-24, 30, 50), tercer dígito 0-6, módulo 10 | **No se guarda** |
| RUC de persona natural (tercer dígito 0-5) | Cédula válida + establecimiento distinto de 000 | **No se guarda** |
| RUC de sociedad privada (9) o pública (6) | Módulo 11 y establecimiento | **Solo aviso**: se guarda y queda en «Validaciones» |
| Pasaporte | No se revisa | — |

En los RUC de sociedades no se bloquea porque el SRI no garantiza ese cálculo para todos los RUC y se han reportado RUC reales que no lo cumplen. El formulario avisa mientras se escribe, al guardar muestra una advertencia amarilla («Se guardó igual; confírmelo en el SRI»), y la pantalla «Validaciones» lista lo ya guardado o importado que no pasa la revisión. Si un RUC de sociedad sale como dudoso, confírmelo en la consulta pública del SRI.

## Alarmas

El panel inicial muestra facturas vencidas, que vencen hoy y las de los próximos N días. El vencimiento se calcula con la condición de crédito del proveedor (N días, fin de mes o día fijo del mes). El envío por correo existe pero está apagado: se activa con `CORREO_ACTIVO=true` y los datos `SMTP_*` en `.env`.

## Importar proveedores desde un Excel

Carga los proveedores de un libro con hojas que tengan las columnas `TIPO ID`, `NUMERO ID`, `TIPO CTA`, `NUMERO CTA` y `BANCOS` (el nombre va en la primera columna). Las demás hojas se ignoran. Copie el archivo a la carpeta `datos/` (no se sube a git) y ejecute:

```
docker compose run --rm --no-deps app python -m app.cli importar-proveedores /app/datos/ARCHIVO.xlsx --usuario admin
docker compose run --rm --no-deps app python -m app.cli importar-proveedores /app/datos/ARCHIVO.xlsx --usuario admin --empresa "NOMBRE DE LA EMPRESA" --aplicar
```

- Sin `--aplicar` solo **simula** y muestra el resumen. Con `--aplicar` hace antes un respaldo y guarda todo en una sola transacción.
- `--empresa` indica a qué empresa pertenece la columna de crédito del Excel (sin distinguir mayúsculas ni tildes; la empresa debe existir y estar activa). Sin `--empresa` los proveedores se importan igual, pero **sin crédito**, y el resumen lo indica.
- Cada proveedor se identifica por tipo + número de ID. Si ya existe se deja como está (también su crédito), así que se puede volver a correr sin duplicar ni pisar cambios hechos a mano.
- Los marcados `OK` en la columna `REGISTRADO` entran **revisados** (queda anotado en su historial); el resto queda **pendiente** de revisión.
- Lo que no se puede importar (ID vacío o con largo incorrecto, otra cuenta para el mismo ID, etc.) se omite y se lista por hoja y fila, sin mostrar datos personales. Un proveedor con dos cuentas distintas en el Excel entra con la de la primera fila; la otra debe revisarse a mano.
- Un banco, un correo o un crédito que no se reconocen no impiden la importación: el proveedor entra sin ese dato y se avisa (el correo inválido queda en las notas). La pantalla «Validaciones» los muestra.

## Comandos de mantenimiento

Se ejecutan dentro del contenedor:

```
docker compose exec app python -m app.cli respaldar
docker compose exec app python -m app.cli clave USUARIO
docker compose exec app python -m app.cli cargar-catalogos [ruta.xlsx]
```

- `respaldar`: crea un respaldo ahora.
- `clave`: cambia la contraseña de un usuario (la pide por teclado).
- `cargar-catalogos`: agrega catálogos desde la hoja de catálogos del Excel (`datos/proveedores.xlsx`, montado en solo lectura). No importa proveedores.

## Respaldos y restauración

- La tarea diaria (a `HORA_TAREA_DIARIA`, por defecto 07:00) crea un respaldo en la carpeta `respaldos/` junto a `docker-compose.yml` y conserva los últimos `RESPALDOS_CONSERVAR` (30). Archivos: `proveedores-AAAAMMDD-HHMMSS.db`.
- La base de datos vive en el volumen de Docker `bd` (`/bd/proveedores.db`).
- **Restaurar:**
  1. `docker compose stop app`
  2. Borrar los archivos auxiliares de SQLite y copiar el respaldo elegido sobre `/bd/proveedores.db` del volumen, por ejemplo:
     `docker compose run --rm -v "%cd%/respaldos:/respaldos" app sh -c "rm -f /bd/proveedores.db-wal /bd/proveedores.db-shm && cp /respaldos/proveedores-AAAAMMDD-HHMMSS.db /bd/proveedores.db"`
     (los `-wal` y `-shm` de la base anterior no deben quedar junto a la restaurada)
  3. `docker compose up -d`

  En Linux/macOS use `"$(pwd)/respaldos:/respaldos"` en lugar de `"%cd%/respaldos:/respaldos"` (este último es para `cmd` de Windows). Procedimiento probado en Linux.

## Actualizar

1. Haga un respaldo (`respaldar`).
2. Reemplace el código del proyecto por la versión nueva (sin tocar `.env`, `datos/` ni `respaldos/`).
3. `docker compose up -d --build`

La base de datos está en un volumen, así que sobrevive a la reconstrucción de la imagen.

## Pruebas

La imagen incluye las dependencias de pruebas:

```
docker compose run --rm app pytest
```

Las pruebas usan datos inventados.

## Primera prueba en la máquina de destino

1. `docker compose up -d` y entrar con el administrador inicial.
2. Correr las pruebas dentro del contenedor.
3. Comprobar que el catálogo de instituciones cargó con sus códigos.
4. Crear las empresas, un usuario creador por empresa y un revisor.
5. Recorrido completo: crear proveedor → registrar el mismo proveedor con el creador de otra empresa (queda uno solo, con dos créditos) → marcarlo como revisado con el revisor → comprobar que el revisor ve una columna por empresa.

## Datos confidenciales

`datos/proveedores.xlsx`, la base de datos, los respaldos y `.env` no deben subirse a git ni a ningún servicio (ya están en `.gitignore`).
