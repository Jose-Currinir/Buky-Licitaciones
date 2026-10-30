"""Informe visual local: un HTML autocontenido, sin red ni dependencias, con modo claro y oscuro.

Todo dato externo (nombres, compradores, regiones) se escapa: proviene de la API o del usuario.
El estándar visual es la base monocroma Butake; el color solo marca la decisión (punto + palabra).
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

import base_empresa as base
from i18n import tr
from presentacion import action_text, event_text

DECISION_ORDER = ['participar', 'participar_condicionado', 'no_participar']
DECISION_TONE = {'participar': 'ok', 'participar_condicionado': 'warn', 'no_participar': 'bad'}
TIMELINE_DAYS = 14
CARDS = 12
WEEKDAYS = ['lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom']

CSS = """
:root{--bg:#f5f5f5;--surface:#fff;--soft:#f0f0f0;--line:#e0e0e0;--line-strong:#858585;--text:#0a0a0a;--muted:#525252;
--ink:#111;--ok:#15803d;--warn:#b45309;--bad:#b91c1c;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#0a0a0a;--surface:#141414;--soft:#1c1c1c;--line:#2e2e2e;--line-strong:#6e6e6e;
--text:#fafafa;--muted:#a3a3a3;--ink:#f5f5f5;--ok:#4ade80;--warn:#fbbf24;--bad:#f87171}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
-webkit-font-smoothing:antialiased}
main{max-width:1080px;margin:0 auto;padding:32px 16px 64px;display:grid;grid-template-columns:minmax(0,1fr);gap:24px}
main>*,.opp,.opp-top>div{min-width:0}
.opp h3,.who{overflow-wrap:anywhere}
header{display:grid;gap:6px}
.eyebrow{font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
h1{font-size:28px;line-height:1.2;margin:0;font-weight:700;letter-spacing:-.01em}
h2{font-size:17px;margin:0 0 12px;font-weight:650}
.meta{color:var(--muted);font-size:13px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.chip{border:1px solid var(--line);background:var(--surface);border-radius:999px;padding:2px 10px;font-size:12px;color:var(--muted)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px}
.kpi .value{font-size:26px;font-weight:700;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.kpi .label{font-size:13px;color:var(--muted)}
.state{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600}
.state::before{content:"";width:8px;height:8px;border-radius:50%;background:currentColor}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
.list{display:grid;gap:12px}
.opp{display:grid;gap:8px}
.opp-top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap}
.opp h3{font-size:16px;margin:0;font-weight:650;line-height:1.35}
.opp .who{color:var(--muted);font-size:13px}
.facts{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px;color:var(--muted)}
.facts b{color:var(--text);font-weight:600;font-variant-numeric:tabular-nums}
.clock{height:6px;background:var(--soft);border-radius:999px;overflow:hidden}
.clock span{display:block;height:100%;background:var(--ink);border-radius:999px}
.clock.urgent span{background:var(--warn)}
ul.notes{margin:0;padding-left:18px;font-size:13px}
.shared{font-size:13px;color:var(--muted);margin:-4px 0 12px}
.shared b{color:var(--text);font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-weight:600;color:var(--muted);font-size:12px;padding:8px 8px 8px 0;border-bottom:1px solid var(--line)}
td{padding:10px 8px 10px 0;border-bottom:1px solid var(--line);vertical-align:top}
td.num{font-variant-numeric:tabular-nums;white-space:nowrap}
tr:last-child td{border-bottom:0}
.scroll{overflow-x:auto}
ul.notes li{margin:2px 0}
.next{font-size:13px;border-left:3px solid var(--ink);padding-left:10px}
.code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:var(--muted)}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.bars{display:grid;gap:8px}
.bar{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 12px;font-size:13px}
.bar .track{grid-column:1/-1;height:8px;background:var(--soft);border-radius:999px;overflow:hidden}
.bar .track span{display:block;height:100%;background:var(--ink)}
.bar .name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar .num{color:var(--muted);font-variant-numeric:tabular-nums}
.timeline{display:grid;grid-template-columns:repeat(14,1fr);gap:4px;align-items:end;height:120px}
.day{display:grid;gap:4px;align-items:end;height:100%;grid-template-rows:1fr auto}
.day .col{background:var(--ink);border-radius:4px 4px 0 0;min-height:2px;align-self:end}
.day .col.zero{background:var(--line)}
.day small{font-size:10px;color:var(--muted);text-align:center;font-variant-numeric:tabular-nums}
.empty{color:var(--muted);font-size:14px}
footer{color:var(--muted);font-size:12px;display:grid;gap:4px}
@media (max-width:560px){h1{font-size:23px}.timeline{gap:2px}.day small{font-size:9px}.kpi .value{font-size:22px}table{min-width:560px}}
@media (forced-colors:active){.state::before,.clock span,.bar .track span,.day .col{background:CanvasText}}
"""


def _zone(company):
    try:
        return ZoneInfo(company.get('preferencias', {}).get('zona_horaria') or 'America/Santiago')
    except Exception:
        return ZoneInfo('America/Santiago')


def money(value, currency='CLP'):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if currency in (None, 'CLP'):
        return '$' + f'{round(value):,}'.replace(',', '.')
    return f'{value:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.') + ' ' + str(currency)


def money_short(value):
    """Monto compacto para las cifras grandes del resumen: $246,4 M."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    for limit, suffix in [(1e9, ' mil M'), (1e6, ' M')]:
        if abs(value) >= limit:
            return '$' + f'{value / limit:.1f}'.replace('.', ',') + suffix
    return money(value)


def when(moment, zone):
    local = moment.astimezone(zone)
    return WEEKDAYS[local.weekday()] + ' ' + local.strftime('%d-%m %H:%M')


def remaining(closing, now):
    delta = closing - now
    hours = delta.total_seconds() / 3600
    if hours < 0:
        return tr('report.closed')
    if hours < 48:
        return tr('report.in_hours', horas=max(1, round(hours)))
    return tr('report.in_days', dias=delta.days, horas=round((delta.total_seconds() - delta.days * 86400) / 3600))


def _closing(item):
    try:
        return base.moment(item['fecha_cierre']) if item.get('fecha_cierre') else None
    except base.DataError:
        return None


def _bars(rows, value_label):
    if not rows:
        return f'<p class="empty">{escape(tr("report.no_data"))}</p>'
    top = max(count for _, count, _ in rows) or 1
    parts = []
    for name, count, extra in rows:
        detail = escape(value_label(count, extra))
        parts.append(
            f'<div class="bar"><span class="name" title="{escape(name)}">{escape(name)}</span>'
            f'<span class="num">{detail}</span><span class="track"><span style="width:{max(2, round(count / top * 100))}%"></span></span></div>'
        )
    return '<div class="bars">' + ''.join(parts) + '</div>'


def render(company, evaluations, now=None, stage_counts=None, last_sync=None, limit=30):
    """HTML del informe. `evaluations` son pares oportunidad/evaluación ya ordenados por prioridad."""
    now = now or datetime.now(timezone.utc)
    zone = _zone(company)
    local_now = now.astimezone(zone)
    from viabilidad import catalog_raw, latest_facts
    facts = latest_facts(company)
    catalog = catalog_raw(facts)
    catalog = [catalog] if isinstance(catalog, str) else catalog
    name = company.get('nombre') or base.display_rut(company['rut'])

    decisions = Counter(entry['evaluacion']['decision'] for entry in evaluations)
    viable = [entry for entry in evaluations if entry['evaluacion']['decision'] != 'no_participar']
    open_amount = sum(entry['oportunidad']['monto'] for entry in viable
                      if isinstance(entry['oportunidad'].get('monto'), (int, float)) and entry['oportunidad'].get('moneda') in (None, 'CLP'))
    soon = sum(1 for entry in viable if (_closing(entry['oportunidad']) or now + timedelta(days=99)) - now <= timedelta(hours=72))

    kpis = [
        (str(len(evaluations)), tr('report.kpi_active'), ''),
        (str(decisions['participar']), tr('viability.decision.participar'), 'ok'),
        (str(decisions['participar_condicionado']), tr('viability.decision.participar_condicionado'), 'warn'),
        (str(decisions['no_participar']), tr('viability.decision.no_participar'), 'bad'),
        (money_short(open_amount) or '$0', tr('report.kpi_amount'), ''),
        (str(soon), tr('report.kpi_soon'), ''),
    ]
    kpi_parts = []
    for value, label, tone in kpis:
        shown = '<span class="state ' + tone + '">' + escape(label) + '</span>' if tone else escape(label)
        kpi_parts.append('<div class="card kpi"><div class="value">' + escape(value) + '</div><div class="label">' + shown + '</div></div>')
    kpi_html = ''.join(kpi_parts)

    shown = evaluations[:min(limit, CARDS)]
    note_counts = Counter(event_text(event) for entry in shown for event in entry['evaluacion']['bloqueos'] + entry['evaluacion']['pendientes'])
    # Un pendiente presente en casi todas las tarjetas se dice una sola vez arriba.
    shared = [note for note, count in note_counts.items() if len(shown) >= 3 and count >= 0.6 * len(shown)]
    cards = []
    for entry in shown:
        item, evaluation = entry['oportunidad'], entry['evaluacion']
        tone = DECISION_TONE[evaluation['decision']]
        closing = _closing(item)
        facts_html = []
        if closing:
            facts_html.append(f'{escape(tr("report.closes"))} <b>{escape(when(closing, zone))}</b> · {escape(remaining(closing, now))}')
        amount = money(item.get('monto'), item.get('moneda'))
        if amount:
            facts_html.append(f'{escape(tr("report.amount"))} <b>{escape(amount)}</b>')
        if item.get('ofertas_recibidas') is not None:
            facts_html.append(f'{escape(tr("report.offers"))} <b>{escape(str(item["ofertas_recibidas"]))}</b>')
        facts_html.append(escape(tr('viability.fit_label', valor=tr('viability.fit.' + evaluation['ajuste_comercial']))))
        clock = ''
        if closing and closing > now:
            hours = (closing - now).total_seconds() / 3600
            left = max(2, min(100, round(hours / (TIMELINE_DAYS * 24) * 100)))
            clock = f'<div class="clock{" urgent" if hours <= 72 else ""}" role="img" aria-label="{escape(remaining(closing, now))}"><span style="width:{left}%"></span></div>'
        notes = [text for text in (event_text(event) for event in evaluation['bloqueos'] + evaluation['pendientes']) if text not in shared][:4]
        notes_html = '<ul class="notes">' + ''.join(f'<li>{escape(note)}</li>' for note in notes) + '</ul>' if notes else ''
        actions = evaluation['proximas_acciones']
        next_html = f'<div class="next">{escape(tr("report.next"))}: {escape(action_text(actions[0]))}</div>' if actions else ''
        who = ' · '.join(escape(value) for value in [item.get('comprador'), item.get('region_comprador')] if value)
        cards.append(
            f'<article class="card opp"><div class="opp-top"><div><h3>{escape(item["nombre"])}</h3>'
            f'<div class="who">{who}</div></div><span class="state {tone}">{escape(tr("viability.decision." + evaluation["decision"]))}</span></div>'
            '<div class="facts">' + ''.join('<span>' + fact + '</span>' for fact in facts_html) + f'</div>{clock}{notes_html}{next_html}'
            f'<div class="code">{escape(item["codigo"])} · {escape(item.get("mecanismo", ""))}</div></article>'
        )
    if not cards:
        cards.append(f'<p class="empty card">{escape(tr("viability.none"))}</p>')
    rows = []
    for entry in evaluations[len(shown):limit]:
        item, evaluation = entry['oportunidad'], entry['evaluacion']
        closing = _closing(item)
        rows.append(
            '<tr><td><span class="state ' + DECISION_TONE[evaluation['decision']] + '">' + escape(tr('viability.decision.' + evaluation['decision'])) + '</span></td>'
            '<td>' + escape(item['nombre']) + '<div class="code">' + escape(item['codigo']) + '</div></td>'
            '<td>' + escape(item.get('comprador') or '') + '</td>'
            '<td class="num">' + (escape(when(closing, zone)) if closing else '') + '</td>'
            '<td class="num">' + escape(money(item.get('monto'), item.get('moneda')) or '') + '</td></tr>'
        )
    table_html = ''
    if rows:
        headers = ''.join('<th>' + escape(tr(key)) + '</th>' for key in ['report.col_decision', 'report.col_name', 'report.col_buyer', 'report.closes', 'report.amount'])
        table_html = ('<section class="card"><h2>' + escape(tr('report.others')) + '</h2><div class="scroll"><table><thead><tr>'
                      + headers + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div></section>')
    more = len(evaluations) - min(limit, len(evaluations))
    if more > 0:
        table_html += f'<p class="empty">{escape(tr("today.more", cantidad=more))}</p>'
    shared_html = '<p class="shared"><b>' + escape(tr('report.shared')) + '</b> ' + escape(' · '.join(shared)) + '</p>' if shared else ''

    days = []
    start = local_now.date()
    per_day = Counter()
    for entry in viable:
        closing = _closing(entry['oportunidad'])
        if closing:
            day = closing.astimezone(zone).date()
            if 0 <= (day - start).days < TIMELINE_DAYS:
                per_day[day] += 1
    peak = max(per_day.values(), default=0) or 1
    for offset in range(TIMELINE_DAYS):
        day = start + timedelta(days=offset)
        count = per_day[day]
        label = tr('report.timeline_day', fecha=day.strftime('%d-%m'), cantidad=count)
        days.append(
            f'<div class="day" title="{escape(label)}"><div class="col{" zero" if not count else ""}" style="height:{max(2, round(count / peak * 100))}%" aria-label="{escape(label)}"></div>'
            f'<small>{day.strftime("%d")}</small></div>'
        )

    regions, buyers = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for entry in viable:
        item = entry['oportunidad']
        amount = item['monto'] if isinstance(item.get('monto'), (int, float)) and item.get('moneda') in (None, 'CLP') else 0
        for bucket, key in [(regions, item.get('region_comprador') or tr('report.unknown')), (buyers, item.get('comprador') or tr('report.unknown'))]:
            bucket[key][0] += 1
            bucket[key][1] += amount
    region_rows = sorted(((key, value[0], value[1]) for key, value in regions.items()), key=lambda row: (-row[1], row[0]))[:8]
    buyer_rows = sorted(((key, value[0], value[1]) for key, value in buyers.items()), key=lambda row: (-row[1], row[0]))[:8]
    count_label = lambda count, amount: tr('report.count_amount', cantidad=count, monto=money(amount) or '$0')

    hidden = stage_counts or {}
    hidden_text = ', '.join(tr('today.stage.' + stage, cantidad=hidden[stage]) for stage in ['por_verificar', 'no_iniciadas', 'planificadas'] if hidden.get(stage))
    sync_text = tr('report.synced', fecha=base.moment(last_sync).astimezone(zone).strftime('%d-%m-%Y %H:%M')) if last_sync else tr('report.not_synced')
    title = tr('report.title', nombre=name)
    chips = ''.join('<span class="chip">' + escape(str(term)) + '</span>' for term in catalog) or '<span class="chip">' + escape(tr('report.no_catalog')) + '</span>'
    hidden_html = '<span>' + escape(tr('today.hidden', detalle=hidden_text)) + '</span>' if hidden_text else ''
    timeline_title = escape(tr('report.timeline', dias=TIMELINE_DAYS))

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>{escape(title)}</title><style>{CSS}</style></head>
<body><main>
<header><div class="eyebrow">{escape(tr('app.name'))}</div><h1>{escape(tr('report.heading'))}</h1>
<div class="meta">{escape(name)} · {escape(base.display_rut(company['rut']))} · {escape(tr('report.generated', fecha=local_now.strftime('%d-%m-%Y %H:%M')))} · {escape(sync_text)}</div>
<div class="chips">{chips}</div></header>
<section class="kpis" aria-label="{escape(tr('report.summary'))}">{kpi_html}</section>
<section><h2>{escape(tr('report.priorities'))}</h2>{shared_html}<div class="list">{''.join(cards)}</div></section>
{table_html}
<section class="card"><h2>{timeline_title}</h2><div class="timeline" role="img" aria-label="{timeline_title}">{''.join(days)}</div></section>
<section class="grid2"><div class="card"><h2>{escape(tr('report.by_region'))}</h2>{_bars(region_rows, count_label)}</div>
<div class="card"><h2>{escape(tr('report.by_buyer'))}</h2>{_bars(buyer_rows, count_label)}</div></section>
<footer><span>{escape(tr('report.footer_scope'))}</span>{hidden_html}
<span>{escape(tr('report.footer_region'))}</span></footer>
</main></body></html>
"""
