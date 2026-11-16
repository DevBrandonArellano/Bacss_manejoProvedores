# Manejo de Proveedores (BACSS)

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

La app reinicia sola con el equipo (`restart: unless-stopped`). Arranca **vacía**: los proveedores se registran a mano. El catálogo de instituciones financieras (con los códigos oficiales) viene incluido y se carga al crear la base.

> **Linux:** la app corre con el usuario 10001. Antes del primer arranque cree la carpeta de respaldos con permisos para él: `mkdir respaldos && sudo chown 10001 respaldos`. Si no, el respaldo diario falla por permisos. En Docker Desktop (Windows) no hace falta.

## Perfiles

| Perfil | Puede |
|---|---|
| Creador | Registrar y editar proveedores y facturas |
| Aprobador | Aprobar o rechazar proveedores en «Aprobaciones» |
| Administrador | Usuarios, catálogos y configuración |

Flujo de aprobación: un proveedor nuevo queda *Pendiente*; si se cambian sus datos bancarios o de identificación vuelve a *Pendiente*; nadie aprueba lo que él mismo creó o modificó; solo los proveedores aprobados entran en el pago masivo.

## Facturas (apagadas por ahora)

Por ahora la app solo registra proveedores. Las facturas, el panel de pagos, las alarmas de vencimiento y el archivo de pago masivo están **ocultos, no eliminados**: se controlan con `FACTURACION_ACTIVA` en `.env` (por defecto `false`).

- Apagado: no aparecen «Panel» ni «Facturas» en el menú, el inicio es la lista de proveedores, y las direcciones `/facturas…` responden «no existe». La tarea diaria solo hace el respaldo.
- Para volver a usarlas: poner `FACTURACION_ACTIVA=true` en `.env` y ejecutar `docker compose up -d` (no basta `restart`). Los datos de facturas que ya existan en la base se conservan.
- Las condiciones de crédito de cada proveedor se siguen guardando.

## Alarmas

El panel inicial muestra facturas vencidas, que vencen hoy y las de los próximos N días. El vencimiento se calcula con la condición de crédito del proveedor (N días, fin de mes o día fijo del mes). El envío por correo existe pero está apagado: se activa con `CORREO_ACTIVO=true` y los datos `SMTP_*` en `.env`.

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
4. Crear un usuario creador y otro aprobador.
5. Recorrido completo: crear proveedor → aprobarlo con el otro usuario → registrar factura → verla en el panel el día que corresponde → exportar pago masivo.

## Datos confidenciales

`datos/proveedores.xlsx`, la base de datos, los respaldos y `.env` no deben subirse a git ni a ningún servicio (ya están en `.gitignore`).
