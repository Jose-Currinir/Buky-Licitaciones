# Histórico y competencia

## Histórico propio y demanda del rubro

Con perfil mínimo, consulta en paralelo lógico dos universos: ventas públicas de la empresa por código/RUT, y compras del rubro por productos, sinónimos y compradores. No limites el mercado a clientes o productos que la empresa ya vendió. Parte por 24 meses como ventana ajustable e informa el período realmente cubierto; ampliar según estacionalidad y disponibilidad, no bloquear el primer informe esperando una descarga exhaustiva.

Para períodos extensos prioriza descargas oficiales de Datos Abiertos; usa API para detalles y cambios. Mapea las columnas reales de cada archivo a un contrato normalizado, conserva el origen y documenta campos faltantes. No adivines nombres de columnas ni endpoints de descarga. La API no asegura que un filtro por proveedor revele todas las participaciones: distinguir órdenes emitidas, aceptadas, adjudicaciones y cotizaciones observables. No calcular tasa de adjudicación sin conocer el universo de participaciones.

Métricas: compradores recurrentes, procesos/OC únicos, montos por moneda/condición tributaria, productos, estacionalidad, plazos y resultados conocidos. No contar el monto de una OC y el de su adjudicación dos veces. Mantener anulaciones y versiones, excluirlas de sumas comerciales según el indicador y describir la regla. Una orden aceptada no prueba ingreso pagado.

## Diagnóstico de mejora y desarrollo

`butake.py diagnostico --rut` resume lo guardado: condiciones del perfil que bloquean o dejan pendientes muchas oportunidades, regiones fuera de cobertura, requisitos que se repiten, líneas de compra cercanas que se repiten fuera del catálogo, compradores frecuentes de lo afín y procesos afines que cerraron con dos ofertas o menos. Es local y determinista; su alcance es el de las oportunidades sincronizadas. Las líneas cercanas se forman con pares de palabras de los títulos: interprétalas y confírmalas con el usuario antes de tocar el catálogo. Con historial propio (`registro` de tipo `historico_propio`) informa además cuántos registros respaldan la experiencia.

## Competidores observados

Identifica proveedores que cotizan o adjudican productos comparables ante compradores compartidos. Agrupa por RUT; razón social es una etiqueta mutable. Distingue oferente observado, adjudicatario y proveedor incumbente; no declares competidor confirmado solo por compartir giro.

Entrega por proveedor: RUT/razón social, rubros comparables, compradores, procesos compartidos, adjudicaciones/OC verificadas, precios comparables y fecha de última observación. Cada afirmación debe apuntar al proceso y fuente. No atribuyas colusión, conflictos ni capacidad técnica sin pruebas.

Compara precios por unidad, especificación, cantidad, moneda, fecha, impuestos, despacho, garantía y SLA. Si no son comparables, segmenta o informa rangos con advertencia concreta; no promedies indiscriminadamente. Usa mediana y dispersión cuando haya suficientes observaciones, con n y cobertura. Si no se ven ofertas perdedoras, el informe es de adjudicatarios observados, no de toda la competencia.

## Anticipación

Busca PAC y contratos próximos a vencer con fecha documentada. Una compra repetida puede sugerir recurrencia: etiquetarla hipótesis con fundamento y ventana, nunca oportunidad publicada. No calcular vencimientos sumando plazos no confirmados a una fecha de OC. Mantener señales separadas de procesos disponibles para ofertar.

Salidas: histórico propio, mapa de compradores, competencia observada y señales de demanda futura; cada una con período, filtros, cobertura, fuentes y fecha de corte. Usa base_empresa.py registro para guardar métricas/relaciones con referencias a sus evidencias. El script persiste registros normalizados; la adquisición y el análisis los realiza el asistente con las herramientas disponibles.
