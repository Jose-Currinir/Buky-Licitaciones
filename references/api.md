# Integración con Mercado Público

Verificado documentalmente el 2026-10-29. Revalidar documentación antes de modificar el cliente o confiar en un comportamiento no probado.

## Dos contratos distintos

V1: https://api.mercadopublico.cl/servicios/v1/publico/
Recursos JSON: licitaciones.json y ordenesdecompra.json. Autenticación: ticket en query. Consulta por codigo o por fecha (ddmmaaaa), estado y, donde corresponda, codigoorganismo/codigoproveedor. No mezclar estos parámetros con los de v2. Consultar la guía vigente para las combinaciones válidas. Las listas y los detalles tienen estructuras diferentes; guardar respuesta original antes de normalizar.

V2: https://api2.mercadopublico.cl/v2/compra-agil
GET listado; GET /{codigo} detalle. Header ticket. Filtros: q o id (excluyentes), estado, region, fechas de publicación; cambios por ttl_cambio_ms o cambio_desde/cambio_hasta. Páginas de 1 a N con tamano_pagina máximo 50. Respuesta envuelta en success, payload y errors; comprobar también success aunque HTTP sea 200.

No hay filtro codigo_organismo en v2; filtrar localmente. La existencia de orden_compra.id_orden_compra es mejor indicador de OC emitida que asumir el estado oc_emitida. Campos de documentos pueden aportar solo id/nombre: no inventar URLs de descarga. La visibilidad de cotizaciones depende de etapa/llamado.

## Comportamiento real observado (30-10-2026, con ticket)

- **v2 Compra Ágil**: `tamano_pagina` debe estar entre 10 y 50 (la API responde 400 con 1–9). Sin `estado`, una búsqueda devuelve hasta 10.000 resultados; con `estado=publicada` (lo que usa la sincronización) bajan a decenas. Cada solicitud tardó entre 12 y 18 s, y hubo respuestas 504 que se resolvieron reintentando.
- **v2, campos**: vienen anidados (`estado.codigo`, `fechas.fecha_cierre`, `institucion.organismo_comprador`, `institucion.nombre_region`, `montos.monto_disponible_clp`, `convocatoria.estado_convocatoria`, `resumen.total_ofertas_recibidas`, `documentos[].nombre`). `fechas.fecha_cierre` viene sin zona (hora de Chile), mientras `fecha_cierre_primer_llamado` rotula esa misma hora local como `Z`: no la uses como UTC.
- **v1 Licitaciones**: el listado por fecha trae solo `CodigoExterno`, `Nombre`, `CodigoEstado` y `FechaCierre` (sin zona) para más de 1.000 procesos por día. El detalle por código agrega comprador, comuna, región, descripción, tipo e ítems con categoría. Estados verificados: 5 publicada, 6 cerrada, 7 desierta, 8 adjudicada, 15 revocada.
- **Cuota**: la guía describe el 429 como cuota **diaria** agotada, que se repone al cambiar el día calendario. En la prueba apareció un 429 tras unas 35 solicitudes del día, así que la cuota real de un ticket puede ser mucho menor que 10.000: sincroniza con pocos términos y bien elegidos.
- La región de `institucion` y de `Comprador` es la del **comprador**; se guarda como `region_comprador`, nunca como región de entrega.

La sincronización de licitaciones por fecha descarta las cerradas y las ajenas al catálogo, y trae el detalle de hasta 20 procesos.

## Consumo y límites

Las condiciones generales publicadas fijan 10.000 solicitudes/día por ticket, monitoreo también por IP y recomiendan las descargas masivas entre 22:00 y 07:00. La guía v2 menciona cuotas por tipo: aplicar 10.000 como referencia conservadora y confirmar con soporte antes de asumir otra. Cada página, detalle y reintento consume solicitudes. No eludir límites con tickets, IPs o clientes paralelos.

`ApiExecutor` comparte estas protecciones entre consultas y perfiles de un mismo directorio de datos:

- Ritmo inicial de 0,5 segundos entre solicitudes reales y caché privada de 600 segundos. La clave elimina `ticket` antes de calcular el hash; no se almacenan URLs v1 con credencial. Los archivos se guardan con permisos privados en `<DATA_DIR>/cache/api`. En la ejecución independiente de `mercado_publico.py`, el directorio operativo es la carpeta que contiene `--out`.
- Una respuesta reutilizada conserva `consultado_en` original y se cuenta en `respuestas_cache`; nunca se presenta como una observación nueva. Un acierto de caché no hace red. Los contadores `solicitudes_reales` y `reintentos` permiten revisar el consumo local, no el saldo oficial del ticket.
- Presupuesto local de 100 intentos reales por sincronización manual y 25 por perfil en el servicio. Incluye reintentos y frena el lote al agotarse; no es una cuota adicional ni reemplaza el límite oficial.
- Como máximo tres intentos por solicitud para errores de red, timeout y HTTP 500/502/503/504, con esperas exponenciales de 1 y 2 segundos además del ritmo. No reintentar 400/401/403/404: corregir filtros, credencial o código según corresponda.
- HTTP 429 nunca se reintenta. Se detiene todo el lote y se guarda `api:no_antes_de` en SQLite para que otras consultas y perfiles no vuelvan a llamar durante el enfriamiento. Se respeta `Retry-After` en segundos o fecha HTTP. Si falta, se pausa hasta el más tardío entre las 00:01 UTC del día siguiente (ejemplo de la guía) y las 00:01 del día siguiente en Chile; no se garantiza que esa sea la hora efectiva de reposición. Una caché vigente puede seguir utilizándose sin red.

Cada página válida de Compra Ágil se conserva de inmediato con su fuente, advertencias y registros omitidos. Si falla la siguiente, los datos anteriores siguen disponibles y los conteos los incluyen. Guardar una página no marca completa la ventana ni el cursor incremental. El resultado informa `cobertura`, `consultas_pendientes`, `detenida_por_cuota`, `presupuesto_agotado` y `reintentar_en`; no ocultar una cobertura parcial ni repetir de inmediato la misma sincronización.

Para sincronización incremental, usar ventanas fijas con `cambio_desde`/`cambio_hasta` o el mecanismo `ttl_cambio_ms` documentado por la API, solapamiento y deduplicación. No usar una ventana relativa nueva para cada página. Los resultados pueden cambiar durante el barrido: reconciliar periódicamente y avanzar un cursor de ventana solo al completarla. El servicio opcional continúa procesando recordatorios y correo durante una pausa de Mercado Público.

## Ejemplos

Configura el ticket con `ticket_config.py` según [configuracion.md](configuracion.md), o mediante el entorno. No lo escribas en comandos que queden en el historial. Con un `.env`, añade `--env-file` a cada consulta.

```bash
python3 "<SKILL_DIR>/scripts/mercado_publico.py" agil --q "desarrollo software" --estado publicada --pagina 1 --tamano 50 --env-file "<DATA_DIR>/.env" --out "<DATA_DIR>/consultas/listado.json"
python3 "<SKILL_DIR>/scripts/mercado_publico.py" agil --codigo "<CODIGO>" --env-file "<DATA_DIR>/.env" --out "<DATA_DIR>/consultas/detalle.json"
python3 "<SKILL_DIR>/scripts/mercado_publico.py" licitaciones --fecha 29102026 --env-file "<DATA_DIR>/.env" --out "<DATA_DIR>/consultas/licitaciones.json"
python3 "<SKILL_DIR>/scripts/mercado_publico.py" ordenes --codigo "<CODIGO_OC>" --env-file "<DATA_DIR>/.env" --out "<DATA_DIR>/consultas/oc.json"
```

El cliente carga el `.env` privado solo al indicar `--env-file`; la variable de entorno tiene prioridad. Sin ticket, `--help` funciona y una consulta real falla con un mensaje de configuración.

## Identificar proveedor y consultar su actividad

GET https://api.mercadopublico.cl/servicios/v1/Publico/Empresas/BuscarProveedor con rutempresaproveedor formateado con puntos, guion y DV, y ticket en query. El cliente valida/normaliza el RUT y conserva la respuesta original; el asistente interpreta los campos documentados sin asumir que acreditan habilidad o actividad económica completa. Para listados v1 por proveedor se envía CodigoProveedor.

```bash
python3 "<SKILL_DIR>/scripts/mercado_publico.py" proveedor --rut "<RUT>" --env-file "<DATA_DIR>/.env" --out "<DATA_DIR>/consultas/identidad.json"
python3 "<SKILL_DIR>/scripts/mercado_publico.py" ordenes --proveedor "<CODIGO_PROVEEDOR>" --fecha 29102026 --env-file "<DATA_DIR>/.env" --out "<DATA_DIR>/consultas/ordenes.json"
```

El filtro por proveedor no implica un historial exhaustivo de ofertas. No hay consulta PAC implementada en este cliente. Ver [empresa.md](empresa.md) y [mercado.md](mercado.md) para completar la investigación.
