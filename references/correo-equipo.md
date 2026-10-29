# Avisos por correo al titular y al equipo

La skill **no envía correos ni guarda contraseñas de correo**. Guarda el equipo de cada perfil en `estado.sqlite3` y prepara borradores en una bandeja de salida. Quien envía es el **complemento de correo del asistente**: Gmail en ChatGPT, o la herramienta de correo equivalente en Codex, Claude u otro host. Así la autorización y los permisos los gestiona el usuario en su asistente, no Buky.

## 1. Comprobar el complemento antes de ofrecer envíos

Revisa qué herramientas de correo tienes disponibles en esta conversación:

- **Puede enviar**: úsala tras la confirmación del usuario (paso 4).
- **Solo puede crear borradores**: crea el borrador en el correo del usuario y dile que lo revise y pulse «Enviar».
- **Solo lectura o ninguna**: explica en una frase cómo habilitarlo y sigue con el resto del flujo:

> Para que pueda enviar correos, activa el complemento de Gmail: en ChatGPT abre **Configuración → Aplicaciones**, elige **Gmail** y pulsa **Conectar**. Luego vuelve a este chat y selecciónalo en las herramientas del mensaje. Los nombres del menú pueden variar según la versión.

Mientras tanto puedes configurar el equipo y dejar los borradores listos, o mostrar el correo para copiarlo. No inventes una capacidad de envío que no aparece en tus herramientas, no pidas contraseñas ni propongas SMTP. Si Google Contacts u otro directorio está conectado, puedes usarlo para **buscar** el correo de una persona que el usuario nombró, y confirmar el resultado antes de agregarla.

## 2. Menú

Cuando el usuario pida configurar el correo, avisos o el equipo, consulta primero el estado y ofrece un menú numerado corto, en este orden y adaptado a lo que ya existe:

```bash
python3 "<SKILL_DIR>/scripts/buky.py" --data-dir "<DATA_DIR>" --json equipo listar --rut "<RUT>"
python3 "<SKILL_DIR>/scripts/buky.py" --data-dir "<DATA_DIR>" --json aviso pendientes --rut "<RUT>"
```

> **Correo y equipo de <perfil>** — Gmail: conectado / no conectado
> 1. Recibir los avisos yo mismo (agregarme como titular)
> 2. Agregar a alguien del equipo
> 3. Ver, editar o quitar personas
> 4. Enviar ahora el resumen de «qué conviene licitar hoy»
> 5. Enviar un recordatorio o un mensaje
> 6. Avisos automáticos de cierre por correo: activados / desactivados
>
> Responde con un número o dímelo con tus palabras.

Si el equipo está vacío, destaca la opción 1 como siguiente paso. Si hay borradores pendientes, ofrécelos antes del menú: «Tienes 2 avisos listos para enviar. ¿Los reviso contigo?». Haz una pregunta a la vez; nunca muestres los comandos al usuario.

## 3. Equipo

Cada persona pertenece a un solo perfil (RUT). Rol `titular` es el propio usuario (`--para yo`); `equipo` son los demás. `--avisos` indica qué recibe de forma predeterminada: `recordatorios`, `resumen`, ambos o ninguno (vacío).

```bash
python3 "<SKILL_DIR>/scripts/buky.py" --data-dir "<DATA_DIR>" --json equipo agregar --rut "<RUT>" --nombre "<NOMBRE>" --correo "<CORREO>" --rol titular
python3 "<SKILL_DIR>/scripts/buky.py" --data-dir "<DATA_DIR>" --json equipo agregar --rut "<RUT>" --nombre "<NOMBRE>" --correo "<CORREO>" --avisos resumen
python3 "<SKILL_DIR>/scripts/buky.py" --data-dir "<DATA_DIR>" --json equipo editar --rut "<RUT>" --id "<ID>" --avisos recordatorios resumen
python3 "<SKILL_DIR>/scripts/buky.py" --data-dir "<DATA_DIR>" --json equipo quitar --rut "<RUT>" --id "<ID>"
```

Para «agregarme», usa el correo de la cuenta conectada en el complemento si la herramienta lo expone y confírmalo; si no, pregúntalo. Pide nombre y correo en una sola frase y confirma con una línea («Agregué a Ana <ana@empresa.cl>, recibirá el resumen diario»). `quitar` desactiva y conserva el historial; `equipo agregar` con el mismo correo la reactiva. Solo agrega correos que el usuario dio o confirmó.

## 4. Preparar, confirmar, enviar y registrar

```bash
python3 "<SKILL_DIR>/scripts/buky.py" --data-dir "<DATA_DIR>" --json aviso preparar --rut "<RUT>" --tipo resumen
python3 "<SKILL_DIR>/scripts/buky.py" --data-dir "<DATA_DIR>" --json aviso preparar --rut "<RUT>" --tipo recordatorio --recordatorio "<ID_RECORDATORIO>" --para yo
python3 "<SKILL_DIR>/scripts/buky.py" --data-dir "<DATA_DIR>" --json aviso preparar --rut "<RUT>" --tipo mensaje --para equipo --asunto "<ASUNTO>" --texto "<TEXTO>"
python3 "<SKILL_DIR>/scripts/buky.py" --data-dir "<DATA_DIR>" --json aviso enviado --id "<ID>" --referencia "<ID_DEL_MENSAJE>"
python3 "<SKILL_DIR>/scripts/buky.py" --data-dir "<DATA_DIR>" --json aviso descartar --id "<ID>"
```

`--para` acepta `yo`, `equipo`, `todos` o ids del equipo. Sin `--para`, el resumen va a quienes tienen `resumen` y el recordatorio a quienes tienen `recordatorios`. El borrador devuelve `para`, `asunto` y `cuerpo` ya listos: úsalos tal cual en la herramienta de correo, con todos los destinatarios en «Para», sin copia oculta ni adjuntos que el usuario no pidió.

Antes de cada envío muestra un resumen y espera un «sí» explícito:

> Voy a enviar desde tu Gmail:
> **Para:** ana@empresa.cl, yo@empresa.cl
> **Asunto:** [Buky Licitaciones] Qué conviene revisar hoy · 29-10-2026
> 3 oportunidades, la primera cierra el 02-11 a las 15:00. ¿Lo envío?

Tras enviar, marca `aviso enviado` con el id que devuelva la herramienta, si lo hay. Si el usuario cancela, usa `aviso descartar`. Si el envío falla, deja el borrador pendiente y di qué pasó. Una aprobación vale para ese correo; no envíes otros borradores en lote sin preguntar.

## 5. Avisos automáticos

```bash
python3 "<SKILL_DIR>/scripts/buky.py" --data-dir "<DATA_DIR>" --json servicio configurar --correo
python3 "<SKILL_DIR>/scripts/buky.py" --data-dir "<DATA_DIR>" --json servicio configurar --no-correo
```

Con `--correo`, cada recordatorio que el servicio local entrega también deja un borrador para quienes tienen `recordatorios`. El servicio **no envía**: los borradores esperan a la próxima conversación, donde los ofreces para enviar con el complemento. Explica esto al activarlo para que nadie espere un correo sin abrir el asistente. Activarlo no habilita el servicio; eso sigue requiriendo una orden explícita (ver asistente.md).

## Límites

- El contenido de los borradores sale de datos locales y del texto que aprobó el usuario. No incluyas costos, márgenes, tickets, tokens ni datos de otro perfil salvo que el usuario lo pida para ese envío.
- No respondas, reenvíes ni archives correos recibidos desde estos flujos; el análisis de correo entrante sigue siendo de solo lectura.
- No escribas a compradores, a ChileCompra ni a terceros fuera del equipo sin una instrucción concreta.
