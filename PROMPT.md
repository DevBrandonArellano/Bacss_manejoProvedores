# Prompt para Claude Code — Manejo de Proveedores

Copia todo lo que está debajo de la línea y pégalo en Claude Code abierto en la carpeta del proyecto.

---

Quiero que construyas en esta carpeta una aplicación web pequeña llamada **Manejo de Proveedores**. Sirve para llevar el control de los proveedores de una empresa (datos de identificación, datos bancarios, días de crédito) y avisar con alarmas de los pagos que se acercan o están vencidos. Hoy todo eso vive en un Excel que se mantiene a mano; la app lo reemplaza.

## Contexto de uso

- Correrá en Docker, en una computadora con Windows que nunca se apaga, y se usará desde el navegador en esa máquina y en otras de la misma red local.
- La usan pocas personas (administración / cuentas por pagar). No es un sistema público.
- Guarda datos sensibles (números de cuenta bancaria, identificaciones, correos), así que debe pedir usuario y contraseña y no exponer nada sin iniciar sesión.
- Toda la interfaz va en español.

## Punto de partida: el Excel

El archivo está en `datos/proveedores.xlsx`. **Antes de diseñar nada, ábrelo e inspecciónalo** (encabezados, tipos, valores distintos por columna, filas vacías, duplicados) y cuéntame lo que encontraste. Lo que ya sé de su estructura:

| Hoja | Contenido | Columnas |
|---|---|---|
| `HILTEXPOY` | Maestro de proveedores (~1000 filas) | nombre (primera columna, sin encabezado), DÍAS CREDITO, REGISTRADO, TIPO ID, NUMERO ID, TIPO CTA, NUMERO CTA, BANCOS, CORREO |
| `Hoja 1` | Formato de pago masivo al banco | NOMBRE, TIPO, CONTRAPARTIDA, MONEDA, VALOR, FORMA DE PAGO, TIPO CTA, NUMERO CTA, REFERENCIA, TIPO ID, NUMERO ID, NOMBRE BENEFICIARIO, CODIGOS BANCOS, correo, DIAS CREDITO |
| `Hoja 2` | Lista de apoyo: CREADO / CREDITO | — |
| `Hoja2` | Catálogos: tipos de ID y códigos de instituciones financieras | — |

Los encabezados tienen espacios sobrantes y acentos; no confíes en los nombres exactos. Los números de cuenta e identificación deben tratarse siempre como **texto** (no perder ceros a la izquierda). El archivo es confidencial: no lo subas a ningún servicio, no lo incluyas en git (agrégalo a `.gitignore` junto con la base de datos) y no pegues datos reales en tus respuestas.

## Qué debe hacer

1. **Gestión de proveedores**: listar, buscar (por nombre, identificación, banco), filtrar, crear, editar y desactivar proveedores. Desactivar en lugar de borrar. Campos: nombre, tipo y número de ID, tipo y número de cuenta, banco (del catálogo), correo, días de crédito, estado (registrado en el banco sí/no), notas.
2. **Catálogos**: bancos con su código de institución financiera, tipos de ID y tipos de cuenta, cargados desde el Excel y editables.
3. **Importación inicial**: un comando o pantalla que cargue el Excel a la base de datos, que se pueda volver a correr sin duplicar (identifica al proveedor por tipo + número de ID) y que al final muestre un resumen: importados, actualizados, omitidos y por qué.
4. **Validaciones**: avisar de proveedores con datos incompletos o sospechosos (sin cuenta, sin banco, correo mal formado, identificación duplicada, misma cuenta en dos proveedores).
5. **Cuentas por pagar y alarmas**: registrar facturas o compras por proveedor (fecha, número, valor, moneda). La fecha de vencimiento se calcula con los días de crédito del proveedor. Un panel inicial muestra lo vencido, lo que vence hoy y lo que vence en los próximos N días (N configurable), y permite marcar como pagado.
6. **Exportación**: generar un Excel con el mismo formato de `Hoja 1` (pago masivo) a partir de las facturas seleccionadas, y exportar el listado de proveedores.
7. **Historial**: guardar quién cambió qué y cuándo en los datos bancarios de un proveedor, porque un cambio de cuenta es el punto clásico de fraude.
8. **Usuarios**: inicio de sesión con contraseña cifrada; el primer usuario administrador se crea con variables de entorno.

### Supuesto que debes confirmar conmigo

Las alarmas están definidas arriba como **avisos de vencimiento de pago según los días de crédito, visibles dentro de la app**. Es una suposición: pregúntame antes de construir esa parte si las alarmas son eso u otra cosa, y si además deben enviarse por correo. Deja el envío por correo preparado pero apagado por defecto.

## Cómo construirla

- **Un solo contenedor**, levantado con `docker compose up -d`, con `restart: unless-stopped` para que vuelva sola tras un reinicio de la máquina.
- **Python + FastAPI**, plantillas en el servidor (Jinja2 + HTMX) y **SQLite** en un volumen de Docker. Es un programa pequeño de pocos usuarios: no quiero un frontend separado ni un servidor de base de datos que mantener. Si ves una razón de peso para otra cosa, dímela antes de cambiarlo.
- Revisión de alarmas con una tarea programada dentro de la misma app, una vez al día.
- Respaldo automático diario de la base de datos a una carpeta montada del equipo, conservando los últimos 30.
- Configuración por archivo `.env` (con un `.env.example` sin secretos): puerto, usuario administrador inicial, clave de sesión, datos de correo.
- Pruebas automáticas para la importación, el cálculo de vencimientos y la exportación del archivo de pago, que son las partes donde un error cuesta dinero.
- Un `README.md` en español con: cómo levantarla, cómo importar el Excel, cómo respaldar y restaurar, y cómo actualizarla.

## Cómo trabajar

1. Inspecciona el Excel y resume lo que encontraste (sin mostrar datos reales).
2. Proponme el modelo de datos y las pantallas, y hazme las preguntas que cambien lo que vas a construir. Espera mi visto bueno.
3. Construye por etapas, en este orden: proveedores + importación → validaciones → cuentas por pagar y alarmas → exportación → historial y respaldos. Al terminar cada etapa, levántala en Docker y comprueba en el navegador que funciona antes de seguir.
4. Al final dime con claridad qué quedó funcionando y verificado, y qué no.

Está terminada cuando puedo ejecutar `docker compose up -d`, entrar con mi usuario, ver todos los proveedores del Excel importados, crear y editar uno, registrar una factura y verla aparecer en el panel de alarmas el día que corresponde.
