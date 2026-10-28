"""로컬 로그에서 숫자만 집계. 네트워크 접근·업로드·원본 변경 없음."""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone, date
from html import escape
import json
from pathlib import Path

KST = timezone(timedelta(hours=9))
FIELDS = ('input', 'cache_write', 'cache_read', 'output')


def day_of(timestamp):
    return datetime.fromisoformat(timestamp.replace('Z', '+00:00')).astimezone(KST).date().isoformat()


def aggregate(home):
    claude = {}
    codex = defaultdict(list)
    diagnostics = {'files': 0, 'invalid_json_lines': 0, 'unusable_usage_records': 0}
    roots = [('claude', home / '.claude/projects'), ('codex', home / '.codex/sessions'),
             ('codex', home / '.codex/archived_sessions')]
    for source, root in roots:
        for path in sorted(root.rglob('*.jsonl')):
            diagnostics['files'] += 1
            session = str(path)
            with path.open(encoding='utf-8') as stream:
                for line in stream:
                    if not any(key in line for key in ('"usage"', '"token_count"', '"session_meta"')):
                        continue
                    try:
                        record = json.loads(line)
                    except (ValueError, UnicodeError):
                        diagnostics['invalid_json_lines'] += 1
                        continue
                    payload = record.get('payload') or {}
                    if source == 'codex' and record.get('type') == 'session_meta':
                        session = payload.get('id') or session
                    if source == 'claude':
                        message = record.get('message') or {}
                        usage = message.get('usage')
                        if record.get('type') != 'assistant' or not usage:
                            continue
                        ident = message.get('id')
                        timestamp = record.get('timestamp')
                        if not ident or not timestamp:
                            diagnostics['unusable_usage_records'] += 1
                            continue
                        counts = dict(zip(FIELDS, (usage.get(k, 0) or 0 for k in
                            ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens'))))
                        key = (ident, record.get('requestId'))
                        if key in claude:
                            previous, old_time = claude[key]
                            counts = {k: max(previous[k], counts[k]) for k in FIELDS}
                            timestamp = min(timestamp, old_time)
                        claude[key] = (counts, timestamp)
                    elif record.get('type') == 'event_msg' and payload.get('type') == 'token_count':
                        info = payload.get('info') or {}
                        usage = info.get('total_token_usage')
                        timestamp = record.get('timestamp')
                        if usage and timestamp:
                            codex[session].append((timestamp, usage))
    daily = defaultdict(lambda: defaultdict(int))
    totals = {source: dict.fromkeys(FIELDS, 0) for source in ('claude', 'codex')}

    def add(source, counts, timestamp):
        d = day_of(timestamp)
        for key in FIELDS:
            totals[source][key] += counts[key]
        daily[d][source] += sum(counts.values())

    for counts, timestamp in claude.values():
        add('claude', counts, timestamp)
    seen = set()
    for events in codex.values():
        previous = dict.fromkeys(('input_tokens', 'cached_input_tokens', 'output_tokens'), 0)
        for timestamp, usage in sorted(events, key=lambda x: x[0]):
            current = {k: usage.get(k, 0) or 0 for k in previous}
            # 누적 값 감소는 새 카운터 구간. 반복 이벤트는 차이 0.
            reset = current['input_tokens'] + current['output_tokens'] < previous['input_tokens'] + previous['output_tokens']
            delta = {k: max(0, current[k] - (0 if reset else previous[k])) for k in current}
            previous = current
            signature = (timestamp, tuple(current.items()))
            if signature in seen:
                continue
            seen.add(signature)
            # Codex의 cached_input_tokens는 input_tokens에 이미 포함됨.
            cached = min(delta['cached_input_tokens'], delta['input_tokens'])
            counts = {'input': delta['input_tokens'] - cached, 'cache_write': 0,
                      'cache_read': cached, 'output': delta['output_tokens']}
            if sum(counts.values()):
                add('codex', counts, timestamp)
    by_day = {d: dict(values) for d, values in sorted(daily.items()) if sum(values.values())}
    combined = {k: sum(t[k] for t in totals.values()) for k in FIELDS}
    input_total = sum(combined[k] for k in ('input', 'cache_write', 'cache_read'))
    return {'schema_version': 1, 'generated_at': datetime.now(KST).isoformat(timespec='seconds'),
            'timezone': 'Asia/Seoul', 'coverage': 'retained local Claude Code and Codex logs only',
            'first_day': min(by_day) if by_day else None, 'last_day': max(by_day) if by_day else None,
            'totals': totals, 'total_tokens': sum(combined.values()),
            'cache_read_percent': round(100 * combined['cache_read'] / input_total, 1) if input_total else 0,
            'daily_tokens': by_day, 'diagnostics': diagnostics}


def compact(value):
    for size, suffix in ((1_000_000_000, 'B'), (1_000_000, 'M'), (1_000, 'K')):
        if value >= size:
            return f'{value / size:.2f}'.rstrip('0').rstrip('.') + suffix
    return str(value)


def render(data, dark=False, mobile=False):
    bg, fg, muted, border, accent = ('#111316', '#F4EDE3', '#B8ADA0', '#554B3A', '#DFC38C') if dark else ('#FFFCF6', '#29231F', '#786957', '#D8C7A6', '#8B6731')
    shades = ['#252621', '#4B4435', '#776345', '#B29564', '#DFC38C'] if dark else ['#EEE7DA', '#DBCCAF', '#B99B67', '#99763E', '#765221']
    w, h = (600, 460) if mobile else (1200, 282)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-labelledby="title desc">',
             '<title id="title">Ihan · AI 사용 기록</title>',
             f'<desc id="desc">보관된 로컬 Claude Code·Codex 로그 기준 {data["total_tokens"]:,} 토큰. 입력 중 캐시 읽기 {data["cache_read_percent"]}%. 최근 26주 사용량. 실제 결제액 아님.</desc>',
             f'<rect x="1" y="1" width="{w-2}" height="{h-2}" rx="16" fill="{bg}" stroke="{border}"/>']

    def text(x, y, value, size=14, color=None, weight=400, mono=False, anchor=None):
        family = "'Consolas','SFMono-Regular',monospace" if mono else "'Malgun Gothic','Apple SD Gothic Neo','Segoe UI',sans-serif"
        extra = f' text-anchor="{anchor}"' if anchor else ''
        parts.append(f'<text x="{x}" y="{y}" fill="{color or fg}" font-family="{family}" font-size="{size}" font-weight="{weight}"{extra}>{escape(str(value))}</text>')

    text(28, 35, 'AI / USAGE LOG', 13, accent, 600, True)
    text(w-28, 35, '@Ihan0316', 13, muted, mono=True, anchor='end')
    text(28, 65, f'{data["first_day"]} — {data["last_day"]} · KST', 12, muted)
    text(28, 107, '보관 기록 누적 토큰', 13, muted)
    text(28, 164, compact(data['total_tokens']), 52, accent, 600, True)
    text(28, 194, f'입력 중 캐시 읽기 {data["cache_read_percent"]:.1f}%', 13, muted)
    sx, sy = (330, 107) if mobile else (365, 107)
    text(sx, sy, 'SOURCE / TOKENS', 12, muted, mono=True)
    for i, (source, label) in enumerate((('claude', 'Claude Code'), ('codex', 'Codex'))):
        text(sx, sy + 36 + i*37, label, 15)
        text(sx + (240 if mobile else 235), sy + 36 + i*37,
             compact(sum(data['totals'][source].values())), 18, accent, 600, True, 'end')
    if not mobile:
        parts.append(f'<path d="M335 87V207 M650 87V207" stroke="{border}"/>')
    gx, gy, cell, gap = (28, 267, 15, 5) if mobile else (686, 110, 13, 5)
    text(gx, gy-15, '최근 26주 · 일별 토큰', 12, muted)
    today = datetime.fromisoformat(data['generated_at']).date()
    sunday = today - timedelta(days=(today.weekday()+1) % 7)
    start = sunday - timedelta(weeks=25)
    values = {d: sum(v.values()) for d, v in data['daily_tokens'].items()}
    peak = max((v for d, v in values.items() if start <= date.fromisoformat(d) <= today), default=1)
    for week in range(26):
        for row in range(7):
            day = start + timedelta(weeks=week, days=row)
            if day > today:
                continue
            value = values.get(day.isoformat(), 0)
            level = 0 if not value else 1 if value <= peak*.10 else 2 if value <= peak*.30 else 3 if value <= peak*.60 else 4
            x, y = gx + week*(cell+gap), gy + row*(cell+gap)
            parts.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="3" fill="{shades[level]}"><title>{day}: {value:,} tokens</title></rect>')
    footer_y = 422 if mobile else 243
    text(28, footer_y, '로컬 보관 로그 기준 · 전체 계정 사용량과 다를 수 있음', 12, muted)
    text(28, footer_y+20, f'수동 갱신 스냅샷 · {data["generated_at"][:10]} · 결제액 미표시', 11, muted)
    parts.append('</svg>\n')
    return '\n'.join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    data = aggregate(args.home)
    for folder in ('assets', 'data'):
        (args.output / folder).mkdir(parents=True, exist_ok=True)
    (args.output / 'data/ai-usage.json').write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    for dark in (False, True):
        for mobile in (False, True):
            name = 'ai-usage-' + ('mobile-' if mobile else '') + ('dark' if dark else 'light') + '.svg'
            (args.output / 'assets' / name).write_text(render(data, dark, mobile), encoding='utf-8')
    print(json.dumps({k: v for k, v in data.items() if k != 'daily_tokens'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
