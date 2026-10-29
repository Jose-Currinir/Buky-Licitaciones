# Vistas de oportunidades

## Dos dimensiones

Conservar estado oficial y etapa comercial derivada por separado. Recalcular etapa con hora actual en cada consulta; un proceso puede vencer sin cambiar aún su etiqueta publicada. Nunca usar una fecha genérica FechaInicio como apertura de ofertas sin verificar su significado en la fuente.

| Vista | Regla | Acción |
| --- | --- | --- |
| Planificadas | PAC o anuncio previo oficial; sin proceso abierto identificado | Prepararse; fecha referencial |
| Aún no comienzan | Proceso publicado con fecha de inicio de ofertas futura y verificada | Revisar bases y agenda |
| Comenzaron / abiertas | Estado oficial abierto, cierre futuro verificado, sin apertura futura | Evaluar y preparar oferta |
| Por cerrar | Abierta y faltan como máximo 72 horas, umbral configurable | Priorizar según esfuerzo pendiente |
| Cerradas | Estado cerrado/adjudicado/desierto/cancelado/revocado/OC emitida o cierre <= ahora | Omitir de oportunidades por defecto |
| Suspendidas | Estado oficial suspendido | Fuera de oportunidades activas; revisar novedades |
| Por verificar | Estado/fecha/zona faltante, desconocido o contradictorio | Verificar antes de sugerir postular |

Por cerrar es un subconjunto de abiertas para filtrar, pero se muestra en una sola sección para evitar duplicados. Umbral expresado en horas corridas, no días hábiles. A igualdad con el cierre, ya está cerrada. Una fecha futura no reabre un estado oficial cerrado; una fecha vencida invalida una etiqueta publicada desactualizada. Una planificación no se convierte en abierta porque llegue el mes previsto. No conviertas medianoche de un mes estimado en un cierre real.

## Fuentes

Procesos actuales: APIs v1/v2, ficha y modificaciones oficiales. Futuro: PAC y anuncios verificables, mediante portal/descargas disponibles; no hay colector PAC implementado aquí. Recurrencias inferidas del histórico se muestran aparte como señales, sin código de licitación inventado ni enlace de postulación. Relaciona plan y proceso solo con evidencia de correspondencia; no sumarlos como dos negocios confirmados.

## Consulta habitual

1. Cargar el perfil elegido, su tipo, catálogo y preferencias guardadas. En persona natural, distinguir exploración de habilitación para ofertar según el estado de inicio de actividades.
2. Buscar por familias/sinónimos y ampliar si la cobertura es insuficiente; obtener detalle cuando el listado no tenga campos necesarios. Deduplicar términos y aprovechar caché sin cambiar la fecha original de consulta. No reintentar tras 429 ni agotar el presupuesto local.
3. Deduplicar por mecanismo/código, guardar cada página válida, sus fuentes, versiones y estado oficial antes de continuar. Si una página falla, conservar las anteriores e informar cobertura/parcialidad y términos pendientes. Reconciliar cierres/modificaciones, no solo nuevas publicaciones.
4. Filtrar por mecanismo, rubro, región de entrega (no confundir con región del comprador), comprador, monto/moneda, elegibilidad, plazo y exclusiones. Desconocidos de un filtro explícito van a pendientes, no pasan silenciosamente.
5. Omitir cerradas y suspendidas por defecto. Recalcular etapas con fechas verificadas. Mostrar separadas planificadas, futuras, abiertas y por cerrar; informar cuántas quedaron por verificar.
6. Ordenar por afinidad y factibilidad y, dentro de urgencia comparable, por cierre. Explicar por qué coincide, bloqueos y esfuerzo. Urgencia no vuelve viable una oferta imposible.

Comandos naturales: «busca oportunidades», «aún no comienzan», «comenzaron», «por cerrar en 48 horas», «omite cerradas», «incluye cerradas», «solo Compra Ágil», «excluye este rubro». Persistir preferencias cuando el usuario las establezca. Incluir cerradas para histórico no cambia por sí solo el filtro habitual de oportunidades.

Ficha por oportunidad: código/identificador de planificación, título, mecanismo, comprador, presupuesto y base tributaria, entrega, estado oficial, etapa derivada, apertura/cierre con zona, tiempo restante, afinidad explicada, requisitos pendientes, enlace, última consulta y cobertura. No prometer postulación o disponibilidad si no hay fecha/estado verificados.

El script local clasifica JSON normalizado y filtra cerradas. El asistente adapta los campos originales con trazabilidad; el script no infiere una zona horaria ni transforma planes en procesos reales.
