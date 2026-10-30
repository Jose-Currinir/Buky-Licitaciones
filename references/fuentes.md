# Fuentes y vigencia

Última revisión documental: 2026-10-30 (reglamento y mecanismos) y 2026-10-29 (API). El 2026-10-30 se validaron con un ticket real consultas de solo lectura de Compra Ágil y licitaciones (ver [api.md](api.md)); el resto del cliente se prueba con simulaciones.

- API y condiciones: https://www.chilecompra.cl/api/
- Guía Compra Ágil v2, versión 3.1 mayo 2026: https://www.chilecompra.cl/wp-content/uploads/2026/05/Documentacion_API_Compra_Agil-3-1.pdf
- Compra Ágil proveedor: https://www.chilecompra.cl/compra-agil-proveedor/
- Registro de Proveedores: https://www.chilecompra.cl/registro-de-proveedores/
- Orientación Compra Ágil: https://ayuda.mercadopublico.cl/preguntasfrecuentes/article/KA-01941/es-es
- Ley 21.634 (reforma, consultar también texto consolidado vigente de Ley 19.886): https://www.bcn.cl/leychile/navegar?idNorma=1198903
- Reglamento, Decreto 661, publicación oficial 2024-12-12: https://www.diariooficial.interior.gob.cl/publicaciones/2024/12/12/44022-B/01/2583778.pdf
- Texto del Decreto 661 publicado por ChileCompra (BCN, generado 2025-02-26), base de [mecanismos.md](mecanismos.md): https://www.chilecompra.cl/wp-content/uploads/2025/02/Decreto-661_12-DIC-2024.pdf
- Nóminas de personas jurídicas del SII (actividades económicas, empresas con tramo de ventas, razón social; datos abiertos): https://www.sii.cl/sobre_el_sii/nominapersonasjuridicas.html. El SII no garantiza su exactitud ni vigencia.
- Valor UTM: https://www.sii.cl/valores_y_fechas/utm/utm2026.htm (buscar año y mes aplicables).
- Planes Anuales de Compra: https://www.chilecompra.cl/planes-de-compra/
- Datos abiertos e histórico: https://www.chilecompra.cl/datos-abiertos/

Las bases específicas, modificaciones y respuestas oficiales del proceso determinan sus requisitos dentro del marco vigente. Para afirmaciones legales verifica versión, entrada en vigor y transitorios en fuentes primarias, y cita artículo aplicable; un resumen de esta skill no sustituye esa comprobación. Si no se puede verificar, identifica la incertidumbre y su efecto sobre la decisión.

Mantener un registro por expediente: URL, título, versión/fecha, consulta UTC, archivo local y página/sección. No copiar manuales enteros: conservar enlaces y notas operativas propias. Ante cambios de API o discrepancias con la guía, guardar un ejemplo anonimizado en el expediente e informar la diferencia al usuario, sin datos de proveedores reales.


## Extracción web acotada

Para Mercado Público usar los mecanismos oficiales de API y descargas; no construir un scraper paralelo para evitar autenticación o cuota. En otros sitios públicos pertinentes, hacer extracciones puntuales con caché, baja concurrencia y una ventana/alcance explícitos. Respetar condiciones de uso, robots.txt cuando aplique y `Retry-After`; detenerse ante 429 o restricciones del sitio. Nunca eludir login, CAPTCHA, bloqueos, límites por IP ni controles de acceso. Conservar URL y hora de consulta, no borrar evidencia parcial y declarar qué páginas o secciones quedaron fuera. Una página pública no autoriza recolectar datos personales innecesarios ni suponer que su contenido está vigente.
