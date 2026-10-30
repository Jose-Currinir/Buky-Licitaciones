# Base local por perfil

El código se instala una vez; los datos pertenecen a cada usuario y perfil. Nunca guardes la base dentro de la carpeta de skills ni junto a los scripts instalados: usa `<DATA_DIR>`, un directorio privado elegido por el usuario (por defecto `~/.buky/licitaciones`). `base_empresa.py` exige `--data-dir` explícito. No hay servidor, cuenta central ni sincronización de perfiles entre usuarios.

Base JSON por RUT normalizado: versión de esquema, `tipo_perfil` (`empresa` o `persona_natural`), nombre, `inicio_actividades` (`true`, `false` o `null`), hechos con evidencia, registros de mercado, preferencias, oportunidades y versiones anteriores. Las bases anteriores sin tipo se leen como `empresa`. Escritura atómica con bloqueo y rechazo de lecturas desactualizadas. Cada guardado real conserva un snapshot completo encadenado en historial/base; usa `historial` y `restaurar` según [versiones.md](versiones.md). No editar base.json a mano ni ejecutar escrituras concurrentes contra el perfil. Un cambio de RUT selecciona otra base; nunca modifica la anterior. El almacenamiento local no equivale a cifrado.

```bash
python3 "<SKILL_DIR>/scripts/base_empresa.py" --data-dir "<DATA_DIR>" init --rut "<RUT>" --tipo empresa
python3 "<SKILL_DIR>/scripts/base_empresa.py" --data-dir "<DATA_DIR>" init --rut "<RUT>" --tipo persona_natural
python3 "<SKILL_DIR>/scripts/base_empresa.py" --data-dir "<DATA_DIR>" hecho --rut "<RUT>" --archivo "<DATA_DIR>/entrada/hecho.json"
python3 "<SKILL_DIR>/scripts/base_empresa.py" --data-dir "<DATA_DIR>" registro --rut "<RUT>" --archivo "<DATA_DIR>/entrada/registro.json"
python3 "<SKILL_DIR>/scripts/base_empresa.py" --data-dir "<DATA_DIR>" preferencias --rut "<RUT>" --archivo "<DATA_DIR>/entrada/preferencias.json"
python3 "<SKILL_DIR>/scripts/base_empresa.py" --data-dir "<DATA_DIR>" importar --rut "<RUT>" --archivo "<DATA_DIR>/entrada/oportunidades.json"
python3 "<SKILL_DIR>/scripts/base_empresa.py" --data-dir "<DATA_DIR>" oportunidades --rut "<RUT>" --vista activas
```

El asistente sustituye rutas y RUT, y evita exhibir la base completa si contiene costos. Para exportar usa `--out` con un archivo nuevo en el espacio privado; sin `--out` el comando imprime JSON en la sesión. Para el directorio de perfiles y la actualización de identidad o inicio de actividades, usa la interfaz principal descrita en [empresa.md](empresa.md) y [asistente.md](asistente.md).

## Hecho

Para los hechos que usa la evaluación (catálogo, exclusiones, regiones, horas de preparación y margen mínimo) usa `buky.py catalogo` y `buky.py condiciones`; ver la tabla de [evaluacion.md](evaluacion.md). Este formato manual queda para otros antecedentes.


JSON objeto con campo, valor, estado (documentado/declarado/inferido/pendiente), fuente y consultado_en ISO-8601 con zona. Opcionales: documento, ubicacion, valido_hasta. Cada incorporación añade una evidencia; no destruye la anterior. Ejemplo: identidad_confirmada=true con estado declarado y fuente usuario. No etiquetar un dato como documentado sin evidencia localizada.

## Registro de mercado

JSON objeto con tipo (historico_propio/compra_rubro/competidor/senal), clave, fuente, consultado_en y datos (objeto libre). Dentro de datos mantener código de proceso, RUTs, cantidades, montos/moneda/impuestos, resultado y referencias cuando existan. La clave identifica el evento/relación; cada incorporación es una observación versionada, no una venta adicional. El análisis deduplica por identidad comercial; no sumar todas las observaciones.

## Oportunidades normalizadas

Lista JSON. Campos requeridos: codigo, mecanismo (licitacion/compra_agil/planificacion), nombre, estado_oficial, fuente, consultado_en. Para procesos: fecha_cierre ISO-8601 con zona cuando se conozca, fecha_inicio_ofertas solo si está verificada; para planificación usar fecha_estimada como texto y no fecha_cierre. Opcionales: comprador, rut_comprador, monto, moneda, region_entrega, url, razones_afinidad, pendientes y productos. Mantener nombres originales/archivo en fuente para auditar la adaptación. No convertir la región del comprador en región de entrega.

El importador rechaza duplicados de mecanismo/código dentro del lote, evita sobrescribir datos con consultas anteriores y conserva versiones; fecha de consulta no garantiza que la fuente sea la última modificación. Si detectas datos de origen más antiguos o discrepancias, resuélvelos antes de importar. Guarda el JSON original por separado. Un lote inválido no guarda cambios parciales.

## Preferencias

incluir_cerradas (bool, default false), horas_por_cerrar (número positivo, default 72), zona_horaria (IANA, default America/Santiago). Otros filtros comerciales se guardan como hechos o preferencias de catálogo y los aplica el asistente; el CLI implementa etapa, plazo y selección de cerradas, no un buscador semántico.

Para --vista: activas incluye abiertas y por_cerrar; futuras incluye planificadas y no_iniciadas; todas incluye cerradas solo con --incluir-cerradas o preferencia. --omitir-cerradas prevalece sobre esa preferencia. por_verificar y suspendidas requieren su propia vista o todas.

Para reanudar el recorrido, guardar como hechos los campos fase_actual y pendientes_alta con fuente/fecha; actualizar mediante nuevas observaciones y resolver por la versión más reciente que no esté contradicha. Esto no confirma identidad ni requisitos por sí solo.

El índice documentos y los metadatos _version los gestionan las utilidades. Consulta [versiones.md](versiones.md) para incorporar archivos, auditar el historial y exportar/restaurar el expediente con integridad. El .env vive en la raíz privada y no entra en revisiones.
