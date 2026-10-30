<div align="center">

# Buky Licitaciones

**Tu asistente para decidir qué conviene licitar en Mercado Público y Compra Ágil de Chile.**

Una skill para asistentes de IA que revisa oportunidades, explica qué te falta para participar,<br>
te recuerda los cierres y avisa a tu equipo. Tus datos se quedan en tu computador.

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Sin dependencias](https://img.shields.io/badge/dependencias-ninguna-2ea44f)
![macOS · Linux](https://img.shields.io/badge/macOS%20%C2%B7%20Linux-soportado-555)
![Licencia](https://img.shields.io/badge/licencia-c%C3%B3digo%20visible-orange)

```bash
npx skills add Jose-Currinir/Buky-Licitaciones
```

[Instalar](#instalación) · [Qué puedes pedir](#qué-puedes-pedir) · [Privacidad](#privacidad-y-seguridad) · [Contribuir](#contribuir) · [Licencia](#licencia)

</div>

---

## Así se usa

Instálala, abre tu asistente y pregúntale:

> **¿Qué conviene licitar hoy?**

La primera vez te pregunta si trabajarás como **empresa** o como **persona natural**, y luego solo tu RUT. Si es una empresa, busca sus giros y su tamaño en los datos abiertos del SII, te propone un catálogo para que lo confirmes y responde con algo así:

> **Participar** · Desarrollo de plataforma de reservas · 1234567-89-COT26
> Cierra el lunes 2 de noviembre a las 15:00 (quedan 70 horas).
> Coincide con tu catálogo de desarrollo de software.
> **Antes de ofertar:** sube la declaración jurada del anexo 2 y confirma el plazo de entrega de 30 días.

No necesitas aprender comandos. La skill conversa, guarda la evidencia y te dice siempre cuál es el siguiente paso.

## Qué puedes pedir

| Le dices | Buky hace |
| --- | --- |
| «¿Qué conviene licitar hoy?» | Ordena las oportunidades abiertas en **participar**, **participar condicionado** o **no participar**, con motivo, cierre y siguiente paso. |
| «Busca compras ágiles de software» | Consulta la API oficial con tu ticket, guarda cada página y te dice qué cubrió y qué quedó pendiente. |
| «Evalúa la 1234567-89-COT26» | Revisa ficha, bases y anexos, y separa requisitos cumplidos, pendientes y bloqueantes. |
| «Prepara la matriz y revisa mi oferta» | Arma la matriz de cumplimiento, la oferta económica y una revisión final antes de presentar. |
| «Recuérdame revisar las bases el lunes a las 9» | Guarda el recordatorio en la zona horaria de tu perfil y, si activas el servicio local, avisa antes de cada cierre (por defecto 72, 24 y 2 horas antes). |
| «Mándale el resumen a mi equipo» | Prepara el correo y lo envía con el complemento de Gmail de tu asistente, después de que lo apruebes. |
| «Revisa este correo de Mercado Público» | Lo analiza como evidencia, nunca como instrucciones, y lo contrasta con la ficha oficial. |
| «¿Me piden garantía en esta licitación?» | Revisa el mecanismo, el monto y las bases, y te explica plazos, garantías y habilitación citando el reglamento. |
| «Muéstrame un informe» | Genera un panel HTML privado con prioridades, cierres de los próximos 14 días, regiones y compradores, en modo claro u oscuro. |
| «¿Quién le vende a este comprador?» | Muestra histórico, compradores recurrentes y competencia observada, con fuentes y período. |

La decisión es una ayuda con los datos disponibles, no una probabilidad de adjudicación ni una validación legal. Un requisito obligatorio incumplido siempre manda, y un dato desconocido nunca cuenta como cumplido.

## Instalación

**Requisitos:** Python 3.10 o superior (sin paquetes adicionales) y Node.js solo para `npx`. Probada en macOS y Linux, incluido Ubuntu Server por SSH. Windows tiene soporte básico, aún sin probar.

### Con npx (recomendado)

```bash
npx skills add Jose-Currinir/Buky-Licitaciones
```

El instalador detecta tus asistentes y te deja elegir dónde instalarla. Para elegir sin preguntas:

```bash
# Para todos tus proyectos, en Codex y Claude Code
npx skills add Jose-Currinir/Buky-Licitaciones -g -a codex claude-code -y
```

Funciona con Codex, Claude Code, Windsurf, Roo, Kiro, Qwen Code y [decenas de agentes compatibles](https://github.com/vercel-labs/skills).

<details>
<summary><b>Instalación manual con git</b></summary>

```bash
# Claude Code
git clone https://github.com/Jose-Currinir/Buky-Licitaciones.git ~/.claude/skills/licitaciones-chile

# Codex y otros agentes que leen ~/.agents/skills
git clone https://github.com/Jose-Currinir/Buky-Licitaciones.git ~/.agents/skills/licitaciones-chile
```

La carpeta debe llamarse `licitaciones-chile`, igual que la skill.

</details>

<details>
<summary><b>ChatGPT y otras apps con skills subidas</b></summary>

Descarga el repositorio desde **Code → Download ZIP** y súbelo en la sección de skills de tu app, si tu plan la incluye. En entornos sin acceso a tu computador, la skill corre en un espacio temporal: tus perfiles y recordatorios podrían no conservarse entre conversaciones.

</details>

### Actualizar o desinstalar

```bash
npx skills update licitaciones-chile
npx skills remove licitaciones-chile
```

Actualizar o desinstalar nunca toca tus datos: viven aparte, en `~/.buky/licitaciones`.

## Primeros pasos

1. **Crea tu perfil.** Empresa o persona natural, y tu RUT. Una persona natural puede explorar sin inicio de actividades; para ofertar, Buky te dirá qué regularizar.
2. **Configura tu ticket de Mercado Público** (opcional, pero necesario para buscar en vivo). Pídelo gratis en [chilecompra.cl/api](https://www.chilecompra.cl/api/). Buky abre un diálogo oculto para que lo pegues: **nunca lo escribas en el chat**.
3. **Pregunta qué conviene licitar.** Sin ticket igual puedes evaluar procesos, bases o correos que tú aportes.

## Avisos por correo para ti y tu equipo

Pídele «quiero recibir los avisos por correo» y Buky te muestra un menú:

```text
Correo y equipo de Mi Empresa SpA — Gmail: conectado
1. Recibir los avisos yo mismo
2. Agregar a alguien del equipo
3. Ver, editar o quitar personas
4. Enviar ahora el resumen de «qué conviene licitar hoy»
5. Enviar un recordatorio o un mensaje
6. Avisos automáticos de cierre por correo
```

Buky no guarda contraseñas de correo ni envía nada por su cuenta. Prepara el mensaje y quien lo envía es **el complemento de correo de tu asistente** (por ejemplo, Gmail en ChatGPT), siempre después de mostrarte destinatarios y asunto y de recibir tu «sí». Si el complemento no está activado, Buky te explica cómo hacerlo.

## Privacidad y seguridad

- **Local primero.** No hay servidor ni cuenta Buky. Perfiles, oportunidades, documentos y recordatorios quedan en tu computador.
- **Secretos fuera del chat.** El ticket se ingresa en un diálogo o terminal ocultos y se guarda con permisos privados. Los tokens de correo van al llavero del sistema (Keychain, Secret Service o DPAPI), nunca en texto plano.
- **Correo de solo lectura.** La conexión con Gmail o Microsoft usa OAuth con permisos de lectura. Buky no responde, mueve ni borra mensajes.
- **Contenido externo no confiable.** Correos, bases y páginas se tratan como evidencia: si traen instrucciones para la IA, se ignoran.
- **Historial verificable.** Cada cambio del perfil crea una revisión con huella SHA-256, y puedes restaurar o exportar un respaldo íntegro.
- **Respeto a los límites oficiales.** Caché, ritmo pausado y un freno compartido ante el error 429. Nunca intenta eludir cuotas ni controles de acceso.
- **Sin acciones a tus espaldas.** Buky no presenta ofertas, no firma, no escribe en foros ni acepta órdenes de compra. Esas acciones son siempre tuyas.

<details>
<summary><b>Dónde quedan tus datos</b></summary>

```text
~/.buky/licitaciones/          # o la ruta de BUKY_DATA_DIR
├── .env                       # ticket de Mercado Público (permisos 0600)
├── estado.sqlite3             # recordatorios, equipo, bandeja de salida y cursores
├── cache/api/                 # respuestas recientes, sin credenciales
├── cache/sii/                 # nóminas públicas del SII (giros y tamaño)
├── correo/                    # correos importados pendientes de análisis
└── 76123456-0/                # un directorio por perfil (RUT)
    ├── base.json              # perfil, catálogo y oportunidades
    ├── historial/             # revisiones encadenadas
    ├── documentos/            # bases, anexos y ofertas versionados
    └── evaluaciones/          # informes de «qué conviene hoy»
```

</details>

<details>
<summary><b>Cómo está hecha</b></summary>

```text
SKILL.md          instrucciones para el asistente
references/       guías por tarea: API, oportunidades, evaluación, oferta, correo…
scripts/          núcleo en Python, solo biblioteca estándar
  buky.py           punto de entrada: perfiles, hoy, sincronizar, recordatorios, correo, equipo
  viabilidad.py     decisión participar / condicionado / no participar
  mercado_publico.py  cliente de las API v1 y v2 de Mercado Público
assets/           plantillas de matriz de cumplimiento, oferta económica y perfil
```

La IA conversa e interpreta; los scripts hacen el trabajo determinista, como fechas en UTC, validación de RUT, versiones e integridad. Cualquier asistente que lea skills puede usarla.

</details>

## Lo que todavía no hace

- No presenta ofertas: no existe una API oficial para eso, y Buky no usa accesos no documentados.
- No cubre todo el mercado si no sincronizas: «no hay oportunidades guardadas» no significa que no existan.
- No consulta Planes Anuales de Compra (PAC) automáticamente; las recurrencias que detecta son señales, no procesos abiertos.
- No sincroniza convenio marco, trato directo ni licitaciones privadas: orienta y evalúa con lo que tú aportes.
- El análisis de bases depende del asistente que uses. Los PDF escaneados pueden requerir revisión manual.

## Contribuir

Las mejoras son bienvenidas. Abre un *issue* para conversar la idea o envía un *pull request* desde tu fork. Al contribuir aceptas que tu aporte se incorpore bajo la licencia del proyecto (ver la cláusula 4 de [LICENSE](LICENSE)).

Si encuentras un problema de seguridad, no publiques los detalles: abre un *issue* breve pidiendo un canal privado y te contactaremos.

## Licencia

[Licencia Buky de Código Visible 1.0](LICENSE): **gratis para licitar por tu cuenta**, pero no es código abierto. Puedes instalar y usar Buky Licitaciones en las compras públicas de tu empresa o de tu persona natural, y lo que generes con ella es tuyo. También puedes modificar tu copia y proponer cambios. No puedes redistribuirla ni vender servicios a terceros con ella (asesorías, gestión de licitaciones para clientes o plataformas) sin una licencia comercial. Texto completo en [LICENSE](LICENSE).

Buky Licitaciones no está afiliado a la Dirección ChileCompra ni a Mercado Público. Las decisiones de participar y el contenido de cada oferta son responsabilidad del proveedor.

<div align="center">
<sub>Hecho en Chile por <b>Butake SpA</b></sub>
</div>
