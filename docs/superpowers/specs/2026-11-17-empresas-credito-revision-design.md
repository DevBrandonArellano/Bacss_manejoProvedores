# Empresas, crédito por empresa y "Revisión" — diseño

Fecha: 2026-11-17 · Estado: aprobado por el usuario el 2026-11-17, con dos recortes (facturas por empresa y migración de datos quedan fuera por ahora)

## Intención y por qué

Cuatro personas registran proveedores, cada una para una empresa distinta. Muchas veces es **el mismo proveedor** y cada empresa le maneja un crédito distinto (contado, 15 días, 90 días…). Quien revisa necesita ver de un vistazo los créditos de todas las empresas. Además, el nombre "Aprobación" confunde con otros procesos de las empresas: lo que realmente se comprueba es que el proveedor esté creado en otra plataforma, así que pasa a llamarse **Revisión**.

## Objetivos

1. Lista de **empresas** administrable desde la app (crear, renombrar, desactivar).
2. Cada usuario **creador** queda asignado a una empresa al crearlo.
3. Un proveedor existe **una sola vez**; su crédito se guarda **por empresa**.
4. Si el creador intenta registrar un proveedor que ya existe (mismo tipo + número de ID), la app lo **carga** y solo le pide el crédito de su empresa.
5. El revisor y el administrador ven una **columna de crédito por cada empresa activa**.
6. Textos visibles: "Aprobación" → "Revisión".

## No objetivos

- No hay revisión por empresa: se revisa una vez por proveedor.
- No se renombran tablas ni columnas internas de la base de datos.
- No se cambian los tipos de crédito existentes (días, fin de mes, día fijo del mes).

## Antiobjetivos (sería un fracaso aunque funcione)

- Duplicar proveedores para poder tener otro crédito.
- Que un creador cambie el crédito de otra empresa sin darse cuenta.
- Perder los créditos ya cargados al migrar.

## Enfoques considerados

| Enfoque | Qué implica | Resultado |
|---|---|---|
| **A. Tabla de empresas + crédito por pareja proveedor–empresa** | Las columnas de la pantalla salen de la lista de empresas | **Elegido.** Una quinta empresa no exige tocar el programa |
| B. Cuatro columnas fijas en `Proveedor` | Lo más simple hoy | Descartado: rígido, y cada cambio de empresas es un cambio de código |
| C. Un registro de proveedor por empresa | Datos duplicados | Descartado: impide ver los créditos juntos y duplica datos bancarios |

El usuario aceptó A al decir que se necesita "una lista de empresas".

## Decisiones del usuario

- Los proveedores son compartidos entre empresas.
- Al registrar uno que ya existe, se carga y solo se añade el crédito de la otra empresa.
- Lista de empresas; cada usuario que añade información tiene una empresa asignada.
- "Aprobación" se renombra "Revisión".

## Diseño

### Datos
- Nueva tabla `empresas` (`id`, `nombre`, `activo`).
- `Usuario.empresa_id` (opcional; obligatorio en la práctica para el rol creador).
- Nueva tabla `proveedor_creditos` (`proveedor_id`, `empresa_id`, `credito_tipo`, `credito_valor`; único por pareja).
- El historial de cambios registra los cambios de crédito indicando la empresa.

### Comportamiento
- **Registrar proveedor**: al escribir tipo + número de ID se busca el proveedor. Si existe, se muestra su ficha y la acción "Añadir crédito de <mi empresa>"; si ya tiene crédito de mi empresa, se puede editar. Si no existe, el formulario actual con el crédito de mi empresa.
- **Permisos**: el creador ve y edita solo el crédito de su empresa. Revisor y administrador ven todas las empresas; el administrador puede editar el crédito de cualquiera.
- **Lista y ficha de proveedores** (revisor/administrador): una columna por empresa activa; "—" si no tiene crédito con esa empresa.
- **Revisión**: sin cambios de lógica. Añadir el crédito de otra empresa **no** reabre la revisión; un cambio de datos sensibles (identificación, cuenta, banco) sí, como hoy.
- **Facturas y pago masivo: fuera de alcance por ahora.** La facturación sigue desactivada hasta nuevo aviso; esta entrega solo trabaja proveedores. No se tocan las facturas, el cálculo de vencimientos ni la exportación de pago.
- **Importación del Excel**: pide la empresa a la que pertenece el crédito del archivo.

### Datos existentes (migración: **diferida**)
- El usuario definirá más adelante cómo se migran los datos actuales. En esta entrega se trabaja sobre una base nueva: las tablas nuevas se crean al arrancar, como hoy.
- Se conservan, sin usarse, las columnas `credito_tipo` y `credito_valor` de `Proveedor`, para no perder los créditos ya guardados cuando llegue la migración.
- Un creador sin empresa asignada no puede registrar proveedores hasta que el administrador se la asigne.

### Renombre visible
"Aprobación" → "Revisión"; rol "Aprobador" → "Revisor"; estados "Pendiente / Revisado / Rechazado"; menús, títulos, textos de ayuda, README, CHANGELOG y PROMPT. Se mantienen los valores guardados en la base de datos.

## Supuestos míos (a confirmar)

1. Revisión una vez por proveedor, no por empresa.
2. El crédito no es dato sensible: cambiarlo no reabre la revisión.
3. Cualquier creador puede corregir los datos compartidos de un proveedor ya existente (como hoy); los cambios sensibles reabren la revisión.
4. Un usuario pertenece a una sola empresa.

## Pendiente

- Cómo migrar los datos actuales y a qué empresa corresponde el crédito del Excel ya importado: lo decide el usuario después de esta entrega.
- Facturas por empresa: se retoman cuando el usuario reactive la facturación.
- Detalles de pantalla, a criterio de quien construya, respetando el estilo actual.
