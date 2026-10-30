# Seguimiento

## Vigilancia y alertas

En consultas puntuales, informa cuándo se verificó el estado; no prometas vigilancia continua. Para alertas solicitadas, define filtros, frecuencia, destinatario y evento significativo; usa el servicio local o el programador disponible, con presupuesto de cuota y deduplicación por código y versión. Notifica nuevas coincidencias, cambios relevantes y cierres según lo acordado, sin repetir resultados sin cambios. Los avisos de cierre y su configuración están en [asistente.md](asistente.md).

## Adjudicación

Tras la adjudicación registra resolución, puntajes, motivos y enlace; no deduzcas el ganador de un arreglo parcial de cotizaciones. Si no se adjudica al usuario, compara datos públicos y registra aprendizajes sin copiar ofertas ajenas como propias.

## Orden de compra

`evaluar --codigo` no consulta órdenes de compra: trabaja con la ficha, el PDF o el correo que aporte el usuario, o consulta `mercado_publico.py ordenes` según [api.md](api.md). Verifica qué identificador admite la API antes de usarlo: el ID interno y el código externo no son intercambiables sin comprobarlo.

Antes de recomendar aceptarla, contrasta la orden con la oferta presentada y las bases: productos, cantidades, precios netos e impuestos, plazo y lugar de entrega, garantías y condiciones de pago. Cualquier diferencia se informa como bloqueo o pendiente. Aceptar, rechazar o pedir cambios es una acción del usuario en el portal; preparar un calendario no equivale a aceptar la orden.

## Ejecución del contrato

Extrae del contrato y la orden los hitos de aceptación, garantías, entregas, recepción conforme, facturación y pago, y ofrece recordatorios para cada uno. Consultas, reclamos o impugnaciones requieren fundamentos y plazos vigentes: verifica fuentes oficiales antes de orientar y no envíes nada sin autorización.
