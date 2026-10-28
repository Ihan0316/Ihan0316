"""로컬 로그에서 숫자만 집계. 네트워크 접근·업로드·원본 변경 없음."""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP
from html import escape
import json
from pathlib import Path

KST = timezone(timedelta(hours=9))
FIELDS = ('input', 'cache_write', 'cache_read', 'output')
PRICE_FIELDS = ('input', 'cache_write_5m', 'cache_write_1h', 'cache_read', 'output')


def day_of(timestamp):
    return datetime.fromisoformat(timestamp.replace('Z', '+00:00')).astimezone(KST).date().isoformat()


def aggregate(home, pricing=None):
    claude = {}
    codex = defaultdict(list)
    diagnostics = {'files': 0, 'invalid_json_lines': 0, 'unusable_usage_records': 0,
                   'cache_lifetime_mismatch': 0, 'model_conflicts': 0, 'codex_request_counter_mismatch': 0}
    roots = [('claude', home / '.claude/projects'), ('codex', home / '.codex/sessions'),
             ('codex', home / '.codex/archived_sessions')]
    for source, root in roots:
        for path in sorted(root.rglob('*.jsonl')):
            diagnostics['files'] += 1
            session = str(path)
            model = 'UNKNOWN'
            with path.open(encoding='utf-8') as stream:
                for line in stream:
                    if not any(key in line for key in ('"usage"', '"token_count"', '"session_meta"', '"turn_context"')):
                        continue
                    try:
                        record = json.loads(line)
                    except (ValueError, UnicodeError):
                        diagnostics['invalid_json_lines'] += 1
                        continue
                    payload = record.get('payload') or {}
                    if source == 'codex' and record.get('type') == 'session_meta':
                        session = payload.get('id') or session
                    if source == 'codex' and record.get('type') == 'turn_context':
                        model = payload.get('model') or 'UNKNOWN'
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
                        ttl = usage.get('cache_creation') or {}
                        detail = {'input': counts['input'], 'cache_write_5m': ttl.get('ephemeral_5m_input_tokens', 0) or 0,
                                  'cache_write_1h': ttl.get('ephemeral_1h_input_tokens', 0) or 0,
                                  'cache_read': counts['cache_read'], 'output': counts['output']}
                        models = {message.get('model') or 'UNKNOWN'}
                        if key in claude:
                            previous, old_time, old_detail, old_models = claude[key]
                            counts = {k: max(previous[k], counts[k]) for k in FIELDS}
                            detail = {k: max(old_detail[k], detail[k]) for k in PRICE_FIELDS}
                            models |= old_models
                            timestamp = min(timestamp, old_time)
                        claude[key] = (counts, timestamp, detail, models)
                    elif record.get('type') == 'event_msg' and payload.get('type') == 'token_count':
                        info = payload.get('info') or {}
                        usage = info.get('total_token_usage')
                        timestamp = record.get('timestamp')
                        if usage and timestamp:
                            codex[session].append((timestamp, usage, info.get('last_token_usage') or {}, model))
    daily = defaultdict(lambda: defaultdict(int))
    totals = {source: dict.fromkeys(FIELDS, 0) for source in ('claude', 'codex')}
    model_totals = defaultdict(lambda: {'tokens': dict.fromkeys(FIELDS, 0), 'pricing_tokens': defaultdict(int),
                                      'unpriced_tokens': 0, 'long_context_requests': 0,
                                      'first_day': None, 'last_day': None})

    def model_bucket(model, timestamp):
        bucket = model_totals[model]
        day = day_of(timestamp)
        bucket['first_day'] = min(day, bucket['first_day'] or day)
        bucket['last_day'] = max(day, bucket['last_day'] or day)
        return bucket

    def add(source, counts, timestamp):
        d = day_of(timestamp)
        for key in FIELDS:
            totals[source][key] += counts[key]
        daily[d][source] += sum(counts.values())

    for counts, timestamp, detail, models in claude.values():
        add('claude', counts, timestamp)
        model = next(iter(models)) if len(models) == 1 else 'UNKNOWN_CONFLICT'
        bucket = model_bucket(model, timestamp)
        for key in FIELDS:
            bucket['tokens'][key] += counts[key]
        if len(models) != 1:
            diagnostics['model_conflicts'] += 1
            bucket['unpriced_tokens'] += sum(counts.values())
        elif detail['cache_write_5m'] + detail['cache_write_1h'] != counts['cache_write']:
            diagnostics['cache_lifetime_mismatch'] += 1
            bucket['unpriced_tokens'] += sum(counts.values())
        else:
            for key in PRICE_FIELDS:
                bucket['pricing_tokens'][key] += detail[key]
    seen = set()
    for events in codex.values():
        previous = dict.fromkeys(('input_tokens', 'cached_input_tokens', 'output_tokens'), 0)
        for timestamp, usage, last, model in sorted(events, key=lambda x: x[0]):
            current = {k: usage.get(k, 0) or 0 for k in previous}
            # 누적 값 감소는 새 카운터 구간. 반복 이벤트는 차이 0.
            reset = current['input_tokens'] + current['output_tokens'] < previous['input_tokens'] + previous['output_tokens']
            delta = {k: max(0, current[k] - (0 if reset else previous[k])) for k in current}
            previous = current
            signature = (timestamp, tuple(current.items()), model)
            if signature in seen:
                continue
            seen.add(signature)
            # Codex의 cached_input_tokens는 input_tokens에 이미 포함됨.
            cached = min(delta['cached_input_tokens'], delta['input_tokens'])
            counts = {'input': delta['input_tokens'] - cached, 'cache_write': 0,
                      'cache_read': cached, 'output': delta['output_tokens']}
            if sum(counts.values()):
                add('codex', counts, timestamp)
                bucket = model_bucket(model, timestamp)
                for key in FIELDS:
                    bucket['tokens'][key] += counts[key]
                # 장문 할증은 개별 요청 입력 크기로 결정. 증가분과 last 값이 다르면 추정하지 않음.
                mismatch = any(delta[k] != (last.get(k, 0) or 0) for k in delta)
                cache_writes = last.get('cache_write_input_tokens', 0) or 0
                if mismatch or cache_writes:
                    diagnostics['codex_request_counter_mismatch'] += 1
                    bucket['unpriced_tokens'] += sum(counts.values())
                else:
                    is_long = last.get('input_tokens', 0) > 272000
                    if is_long:
                        bucket['long_context_requests'] += 1
                    prefix = 'long_' if is_long else ''
                    for key in ('input', 'cache_read', 'output'):
                        bucket['pricing_tokens'][prefix + key] += counts[key]
    by_day = {d: dict(values) for d, values in sorted(daily.items()) if sum(values.values())}
    combined = {k: sum(t[k] for t in totals.values()) for k in FIELDS}
    input_total = sum(combined[k] for k in ('input', 'cache_write', 'cache_read'))
    result = {'schema_version': 2, 'generated_at': datetime.now(KST).isoformat(timespec='seconds'),
            'timezone': 'Asia/Seoul', 'coverage': 'retained local Claude Code and Codex logs only',
            'first_day': min(by_day) if by_day else None, 'last_day': max(by_day) if by_day else None,
            'totals': totals, 'total_tokens': sum(combined.values()),
            'cache_read_percent': round(100 * combined['cache_read'] / input_total, 1) if input_total else 0,
            'daily_tokens': by_day, 'diagnostics': diagnostics,
            'models': {model: dict(bucket, pricing_tokens=dict(bucket['pricing_tokens']))
                       for model, bucket in sorted(model_totals.items()) if sum(bucket['tokens'].values())}}
    if pricing:
        result['cost'] = calculate_cost(result['models'], pricing)
    return result


def calculate_cost(models, pricing):
    total = Decimal(0)
    priced_tokens = 0
    unpriced = {}
    by_model = {}
    mappings = {}
    for model, bucket in models.items():
        count = sum(bucket['tokens'].values())
        rates = pricing['models'].get(model)
        alias = pricing.get('model_aliases', {}).get(model)
        if not rates and alias and bucket.get('first_day') and bucket['first_day'] >= alias['effective_from']:
            rates = pricing['models'].get(alias['target'])
            if rates:
                mappings[model] = dict(alias, source=pricing['sources']['auto_review_mapping'])
        if not rates:
            unpriced[model] = count
            continue
        amount = Decimal(0)
        for key, tokens in bucket['pricing_tokens'].items():
            long = key.startswith('long_')
            category = key[5:] if long else key
            multiplier = Decimal(rates.get('long_output_multiplier' if category == 'output' else 'long_input_multiplier', '1')) if long else Decimal(1)
            if category not in rates and tokens:
                raise ValueError(f'Missing verified rate: {model}/{category}')
            amount += Decimal(tokens) * Decimal(rates.get(category, '0')) * multiplier / Decimal(1_000_000)
        total += amount
        priced_tokens += count - bucket['unpriced_tokens']
        if bucket['unpriced_tokens']:
            unpriced[model] = bucket['unpriced_tokens']
        by_model[model] = str(amount)
    fx = pricing['fx']
    rate = Decimal(fx['krw_per_eur']) / Decimal(fx['usd_per_eur'])
    return {'basis': pricing['basis'], 'price_date': pricing['verified_on'], 'fx_date': fx['date'],
            'usd': str(total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'krw': str((total * rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP)),
            'krw_per_usd': str(rate), 'usd_by_model_unrounded': by_model,
            'priced_tokens': priced_tokens, 'unpriced_tokens_by_model': unpriced, 'model_mappings': mappings,
            'coverage_percent': round(100 * priced_tokens / sum(sum(b['tokens'].values()) for b in models.values()), 2)
                                if any(sum(b['tokens'].values()) for b in models.values()) else 0}


def compact(value):
    for size, suffix in ((1_000_000_000, 'B'), (1_000_000, 'M'), (1_000, 'K')):
        if value >= size:
            return f'{value / size:.2f}'.rstrip('0').rstrip('.') + suffix
    return str(value)


def render(data, dark=False, mobile=False):
    bg, fg, muted, border, accent = ('#111316', '#F4EDE3', '#B8ADA0', '#554B3A', '#DFC38C') if dark else ('#FFFCF6', '#29231F', '#786957', '#D8C7A6', '#8B6731')
    shades = ['#252621', '#4B4435', '#776345', '#B29564', '#DFC38C'] if dark else ['#EEE7DA', '#DBCCAF', '#B99B67', '#99763E', '#765221']
    w, h = (600, 620) if mobile else (1200, 350)
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
    cost = data.get('cost')
    text(sx, sy, 'API 환산 추정액 · 표준 단가', 13, muted)
    if cost:
        text(sx, sy+41, f"$ {Decimal(cost['usd']):,.2f}", 30, accent, 600, True)
        text(sx, sy+80, f"₩ {int(cost['krw']):,}", 25, accent, 600, True)
        text(sx, sy+109, f"환산 범위: 전체 토큰의 {cost['coverage_percent']:.2f}%", 12, muted)
        note = '검토 모델: 공식 발표로 Luna 매핑' if cost.get('model_mappings') else '단가·사용 기록 미확인 부분 제외'
        text(sx, sy+130, note, 12, muted)
    else:
        text(sx, sy+41, '단가 자료 없음', 22, muted)
    for i, (source, label) in enumerate((('claude', 'Claude Code'), ('codex', 'Codex'))):
        x = 28 + i*300 if mobile else 28
        y = 275 if mobile else 229 + i*27
        text(x, y, label, 13, muted)
        text(x + (245 if mobile else 277), y,
             compact(sum(data['totals'][source].values())), 16, accent, 600, True, 'end')
    if not mobile:
        parts.append(f'<path d="M335 87V267 M650 87V267" stroke="{border}"/>')
    gx, gy, cell, gap = (28, 335, 15, 5) if mobile else (686, 110, 13, 5)
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
    footer_y = 515 if mobile else 296
    text(28, footer_y, 'API 환산액 ≠ 실제 결제액 · 보관된 로컬 기록 기준', 12, muted)
    if cost:
        text(28, footer_y+21, f"단가 {cost['price_date']} · 환율 {cost['fx_date']} · USD/KRW {Decimal(cost['krw_per_usd']):,.2f}", 11, muted)
        text(28, footer_y+41 if mobile else footer_y+38,
             f"수동 갱신 {data['generated_at'][:10]} · 환산 제외 {compact(sum(cost['unpriced_tokens_by_model'].values()))} tokens", 11, muted)
    parts.append('</svg>\n')
    return '\n'.join(parts)


def cost_report(data, pricing):
    cost = data['cost']
    lines = ['# AI API 환산액 확인 기록', '',
             f"- 집계 시각: {data['generated_at']}",
             f"- 보관 기록: {data['first_day']} ~ {data['last_day']}, Asia/Seoul",
             f"- API 환산 추정액: **USD {cost['usd']} / KRW {int(cost['krw']):,}**",
             f"- 단가 기준일: {cost['price_date']}; 환율 기준일: {cost['fx_date']}",
             f"- 환산 토큰: {cost['priced_tokens']:,} / 전체 {data['total_tokens']:,} ({cost['coverage_percent']:.2f}%)", '',
             '현재 공개된 Standard·global API 단가를 과거 보관 토큰에 일괄 적용한 비교용 추정액입니다. 당시 청구액·구독료·절감액·실제 결제액이 아닙니다. Fast/Ultrafast·Batch/Flex·지역 할증·할인·부가세·도구 호출료는 이 표준 토큰 환산 기준에 포함하지 않습니다.', '',
             '## 모델별 확인', '', '| 모델 | 토큰 | USD 환산액 |', '|---|---:|---:|']
    for model, bucket in data['models'].items():
        amount = cost['usd_by_model_unrounded'].get(model)
        display = f"{Decimal(amount):,.2f}" if amount is not None else '공개 단가 미확인: 제외'
        lines.append(f"| {model} | {sum(bucket['tokens'].values()):,} | {display} |")
    lines += ['', '모델별 표시 금액은 소수 둘째 자리 반올림값입니다. 합계는 반올림 전 금액을 합산한 뒤 반올림합니다.', '',
              '## 공식 단가 근거', '',
              f"- [Anthropic 공식 가격표]({pricing['sources']['anthropic']}): Claude 8개 모델의 일반 입력·5분 캐시 생성·1시간 캐시 생성·캐시 읽기·출력 단가를 각각 적용.",
              f"- [OpenAI 공식 GPT-6.1 Sol 문서]({pricing['sources']['openai']}): 입력 $2, 캐시 읽기 $0.10, 출력 $10 / 100만 토큰. 요청 입력이 272,000 토큰을 초과하면 해당 요청 전체 입력·캐시 2배, 출력 1.5배 적용.",
              f"- [OpenAI 공식 전환 발표]({pricing['sources']['auto_review_mapping']}): ChatGPT 앱·Codex CLI 자동 검토를 GPT-5.6 Luna로 전환한다고 명시했습니다. 한국시간 2026-07-31 발표. 이 날짜 이후의 `codex-auto-review` 기록만 Luna로 매핑한 비교용 추정입니다. 개별 요청의 실제 처리 모델은 로컬 로그에 공개되지 않습니다.",
              f"- [Luna 공식 API 단가]({pricing['sources']['openai_luna']}): 일반 입력 $0.20, 캐시 읽기 $0.02, 출력 $1.20 / 100만 토큰. 장문 조건은 모델 문서 기준으로 적용합니다.",
              f"- [현재 ChatGPT 인증 과금 안내]({pricing['sources']['auto_review_billing']}): 자동 승인 안전 검토는 무료이며 플랜 사용 한도에 포함되지 않습니다. 이 사실과 API 환산액은 서로 다른 기준입니다. 과거 청구 정책이나 실제 결제액으로 소급하지 않습니다.",
              '- 캐시 수명 불일치·모델 충돌·개별 요청 토큰과 누적 증가분 불일치가 있으면 해당 요청을 금액에서 제외합니다.',
              '- Codex 캐시 쓰기가 0이 아닌데 세부 수명을 확인하지 못한 요청 역시 금액에서 제외합니다.', '',
              '## 환율 근거', '',
              f"- [ECB 기준환율]({pricing['sources']['exchange']}), {cost['fx_date']}: 1 EUR = {pricing['fx']['usd_per_eur']} USD, {pricing['fx']['krw_per_eur']} KRW.",
              f"- 교차환율: {pricing['fx']['krw_per_eur']} ÷ {pricing['fx']['usd_per_eur']} = {Decimal(cost['krw_per_usd']):.8f} KRW/USD.",
              '- 원화는 반올림 전 달러 합계 × 반올림 전 교차환율로 계산하고 마지막에 원 단위로 반올림합니다.', '',
              '## 미환산 범위', '']
    for model, tokens in cost['unpriced_tokens_by_model'].items():
        lines.append(f'- {model}: {tokens:,} 토큰')
    if not cost['unpriced_tokens_by_model']:
        lines.append('- 없음')
    lines += ['', '[자동 검토 모델 조사 근거](./AUTO_REVIEW_RESEARCH.md)', '']
    lines += ['', '## 파싱 진단', '', '```json', json.dumps(data['diagnostics'], ensure_ascii=False, indent=2), '```', '',
              '단가·환율 스냅샷은 `ai-pricing.json`에 보관합니다. 재집계 스크립트는 네트워크에 접속하지 않으므로, 날짜가 지난 단가와 환율은 새 공식 자료로 확인 후 직접 갱신해야 합니다.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--pricing', type=Path, default=Path(__file__).resolve().parents[1] / 'data/ai-pricing.json')
    args = parser.parse_args()
    pricing = json.loads(args.pricing.read_text(encoding='utf-8'))
    data = aggregate(args.home, pricing)
    for folder in ('assets', 'data'):
        (args.output / folder).mkdir(parents=True, exist_ok=True)
    (args.output / 'data/ai-usage.json').write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (args.output / 'data/AI_USAGE_COST.md').write_text(cost_report(data, pricing), encoding='utf-8')
    for dark in (False, True):
        for mobile in (False, True):
            name = 'ai-usage-' + ('mobile-' if mobile else '') + ('dark' if dark else 'light') + '.svg'
            (args.output / 'assets' / name).write_text(render(data, dark, mobile), encoding='utf-8')
    print(json.dumps({k: v for k, v in data.items() if k != 'daily_tokens'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
