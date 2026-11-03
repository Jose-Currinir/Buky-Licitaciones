# Versiones, documentos y expedientes autocontenidos

## Tres ámbitos

- Código: la carpeta instalada de la skill y su archivo `VERSION`. Los datos de cada perfil siempre quedan fuera de esa carpeta.
- Información de empresa: cada guardado real crea un snapshot privado completo, fecha UTC, autor, motivo, número, huella SHA-256 y revisión anterior. Incluye hechos, preferencias, oportunidades e índice documental. No editar base.json a mano ni usar Git público para datos de empresa.
- Documentos: originales preservados por huella de contenido; versiones por ID documental, metadatos y estado. Un PDF escaneado y su OCR son documentos distintos vinculados con fuente; una modificación oficial de bases recibe nueva versión, no reemplaza el original.

Los hashes comprueban integridad local, no identidad del autor ni firma legal. Un autor «usuario» o «asistente» describe quién registró el cambio, no equivale a firma del representante. Las copias están en el mismo disco: hacer respaldos privados en otro almacenamiento cuando el usuario lo requiera; el historial por sí solo no protege de perder el disco.

## Registrar cambios que permitan retomar

Cada etapa termina guardando nuevos hechos/evidencias con fecha y fuente, fase_actual, pendientes_alta o pendientes del expediente, decisión y próximos pasos. El motivo de una revisión debe expresar el cambio concreto, no solo «actualización». No registrar secretos. Si no hay cambio en la base no se crea una revisión redundante.

```bash
python3 "<SKILL_DIR>/scripts/base_empresa.py" --data-dir "<DATA_DIR>" historial --rut "<RUT>"
python3 "<SKILL_DIR>/scripts/base_empresa.py" --data-dir "<DATA_DIR>" hecho --rut "<RUT>" --archivo "<DATA_DIR>/entrada/hecho.json" --autor asistente --motivo "Agrega certificado y vencimiento verificados"
python3 "<SKILL_DIR>/scripts/base_empresa.py" --data-dir "<DATA_DIR>" restaurar --rut "<RUT>" --revision "<REVISION>" --autor usuario --motivo "Recupera perfil anterior a corrección errónea"
```

Restaurar requiere petición concreta; crea una revisión nueva y conserva todas las anteriores. Se comprueban integridad y empresa. Escrituras simultáneas se bloquean y se rechaza una base leída antes de un cambio ajeno. Una escritura espera unos segundos si otra está en curso. El `.write.lock` guarda el proceso que lo creó: si ese proceso ya no existe, se retira solo; uno sin esos datos (de versiones anteriores) exige comprobar que no siga otro proceso antes de retirarlo a mano. Snapshots no referenciados tras un fallo no forman parte de la cadena activa; no borrarlos ni adoptarlos a ciegas. Si la integridad falla, detener escrituras y recuperar un respaldo verificado.

## Versiones de documentos

```bash
python3 "<SKILL_DIR>/scripts/documentos.py" agregar --data-dir "<DATA_DIR>" --rut "<RUT>" --id "bases-<CODIGO>" --archivo "<ARCHIVO_BASES>" --fuente "URL y sección del proceso" --proceso "<CODIGO>" --autor asistente --motivo "Incorpora bases originales" --estado fuente
python3 "<SKILL_DIR>/scripts/documentos.py" agregar --data-dir "<DATA_DIR>" --rut "<RUT>" --id "oferta-<CODIGO>" --archivo "<ARCHIVO_OFERTA>" --fuente "Borrador elaborado con evidencias de la matriz" --proceso "<CODIGO>" --autor asistente --motivo "Ajusta plazo según modificación oficial" --estado borrador
python3 "<SKILL_DIR>/scripts/documentos.py" listar --data-dir "<DATA_DIR>" --rut "<RUT>" --proceso "<CODIGO>" --historial
python3 "<SKILL_DIR>/scripts/documentos.py" comparar --data-dir "<DATA_DIR>" --rut "<RUT>" --id "bases-<CODIGO>" --v1 1 --v2 2
python3 "<SKILL_DIR>/scripts/documentos.py" verificar --data-dir "<DATA_DIR>" --rut "<RUT>"
```

Usar IDs estables y específicos del proceso; no reutilizar un ID en otra licitación. Versiones sucesivas conservan nombre original, bytes, SHA, procedencia, consulta, autor, motivo, proceso y estado. Nunca se recicla un número aunque se restaure una base anterior. Los objetos se guardan una sola vez por contenido. Para PDF/Word, la comparación del script es binaria/metadatos; usar herramientas de extracción y revisión visual para analizar diferencias de cláusulas o tablas. El diff textual funciona con texto UTF-8 pequeño.

Estados: fuente → borrador → revisado → listo → presentado, según el tipo de archivo. «Revisado» requiere contraste de fuentes; «listo» requiere revisión final y sin pendientes obligatorios; «presentado» requiere comprobante verificable. Cambiar el estado del registro no envía ni firma nada. Un archivo repetido con estado/motivo nuevo puede tener una versión nueva con el mismo hash.

## Respaldo autocontenido interno

```bash
python3 "<SKILL_DIR>/scripts/documentos.py" exportar --data-dir "<DATA_DIR>" --rut "<RUT>" --out "<DATA_DIR>/respaldos/<RUT>-<FECHA>.zip"
python3 "<SKILL_DIR>/scripts/documentos.py" verificar-paquete --rut "<RUT>" --archivo "<DATA_DIR>/respaldos/<RUT>-<FECHA>.zip"
python3 "<SKILL_DIR>/scripts/documentos.py" restaurar-paquete --data-dir "<DATA_DIR_NUEVO>" --rut "<RUT>" --archivo "<DATA_DIR>/respaldos/<RUT>-<FECHA>.zip"
```

El ZIP contiene CONTEXTO.md para retomar, base actual, cadena completa de revisiones, originales de todos los documentos referenciados (incluidos anteriores a restauraciones), VERSION de la skill en el manifiesto e inventario de archivos con tamaños y SHA-256. Excluye .env, lock y archivos externos no indexados. Comprueba integridad de cada archivo/cadena antes de restaurar; no reemplaza una empresa existente ni admite rutas fuera del expediente.

Es un respaldo **interno de toda la empresa** que puede incluir costos y borradores; no entregarlo al organismo comprador. Para presentar, preparar un paquete aparte solo con versiones finales y anexos requeridos por las bases, revisar su contenido y registrar los hashes/versiones presentados con el comprobante. Nunca inferir que un respaldo interno es la oferta final. Un paquete no exporta autenticación: el ticket se configura de nuevo en el destino.

## Actualizar la skill

`butake.py actualizacion` compara `VERSION` con el archivo `VERSION` público (`raw.githubusercontent.com`, solo ese archivo y sin datos del perfil), guarda el resultado 24 horas en `<DATA_DIR>/cache/actualizacion.json` y entrega el comando según cómo se instaló: `npx skills update licitaciones-chile`, `git pull` en un clon o el actualizador propio. `--forzar` ignora la caché; `BUTAKE_SIN_ACTUALIZACIONES=1` desactiva la comprobación y `BUTAKE_URL_VERSION` permite otro origen. Después de actualizar, el asistente debe reiniciarse o abrir una conversación nueva: SKILL.md se carga al inicio y una sesión abierta seguiría con las instrucciones anteriores.

Actualizar reemplaza solo la carpeta de la skill; `<DATA_DIR>` no se migra ni se borra. Lee `VERSION` para informar la versión instalada y, si existe `INSTALLATION.json`, el origen registrado por el instalador. Si el usuario modificó archivos de la skill, avísale antes de reemplazarlos.
