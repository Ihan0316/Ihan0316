# AI API 환산액 확인 기록

- 집계 시각: 2026-10-28T10:05:42+09:00
- 보관 기록: 2026-07-03 ~ 2026-10-28, Asia/Seoul
- API 환산 추정액: **USD 11200.98 / KRW 14,872,087**
- 단가 기준일: 2026-10-28; 환율 기준일: 2026-10-27
- 환산 토큰: 15,227,968,217 / 전체 15,230,213,012 (99.99%)

현재 공개된 Standard·global API 단가를 과거 보관 토큰에 일괄 적용한 비교용 추정액입니다. 당시 청구액·구독료·절감액·실제 결제액이 아닙니다. Fast/Ultrafast·Batch/Flex·지역 할증·할인·부가세·도구 호출료는 이 표준 토큰 환산 기준에 포함하지 않습니다.

## 모델별 확인

| 모델 | 토큰 | USD 환산액 |
|---|---:|---:|
| claude-fable-5 | 1,252,151,495 | 1,885.14 |
| claude-fable-5-1 | 914,579,190 | 821.39 |
| claude-opus-4-8 | 393,792,266 | 526.49 |
| claude-opus-5 | 8,092,955,447 | 6,061.62 |
| claude-opus-5-5 | 4,071,841,436 | 1,791.06 |
| claude-sonnet-4-6 | 114,414 | 0.26 |
| claude-sonnet-5 | 38,200,407 | 10.92 |
| claude-sonnet-5-5 | 12,972,273 | 6.79 |
| codex-auto-review | 107,563,295 | 3.89 |
| gpt-6.1-sol | 346,042,789 | 93.42 |

모델별 표시 금액은 소수 둘째 자리 반올림값입니다. 합계는 반올림 전 금액을 합산한 뒤 반올림합니다.

## 공식 단가 근거

- [Anthropic 공식 가격표](https://platform.claude.com/docs/en/about-claude/pricing): Claude 8개 모델의 일반 입력·5분 캐시 생성·1시간 캐시 생성·캐시 읽기·출력 단가를 각각 적용.
- [OpenAI 공식 GPT-6.1 Sol 문서](https://developers.openai.com/api/docs/models/gpt-6.1-sol): 입력 $2, 캐시 읽기 $0.10, 출력 $10 / 100만 토큰. 요청 입력이 272,000 토큰을 초과하면 해당 요청 전체 입력·캐시 2배, 출력 1.5배 적용.
- [OpenAI 공식 전환 발표](https://x.com/OpenAI/status/2082878180478910571): ChatGPT 앱·Codex CLI 자동 검토를 GPT-5.6 Luna로 전환한다고 명시했습니다. 한국시간 2026-07-31 발표. 이 날짜 이후의 `codex-auto-review` 기록만 Luna로 매핑한 비교용 추정입니다. 개별 요청의 실제 처리 모델은 로컬 로그에 공개되지 않습니다.
- [Luna 공식 API 단가](https://developers.openai.com/api/docs/models/gpt-5.6-luna): 일반 입력 $0.20, 캐시 읽기 $0.02, 출력 $1.20 / 100만 토큰. 장문 조건은 모델 문서 기준으로 적용합니다.
- [현재 ChatGPT 인증 과금 안내](https://help.openai.com/en/articles/20001415-chatgpt-rate-card-enterprise-token-based-pricing): 자동 승인 안전 검토는 무료이며 플랜 사용 한도에 포함되지 않습니다. 이 사실과 API 환산액은 서로 다른 기준입니다. 과거 청구 정책이나 실제 결제액으로 소급하지 않습니다.
- 캐시 수명 불일치·모델 충돌·개별 요청 토큰과 누적 증가분 불일치가 있으면 해당 요청을 금액에서 제외합니다.
- Codex 캐시 쓰기가 0이 아닌데 세부 수명을 확인하지 못한 요청 역시 금액에서 제외합니다.

## 환율 근거

- [ECB 기준환율](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html), 2026-10-27: 1 EUR = 1.1150 USD, 1480.44 KRW.
- 교차환율: 1480.44 ÷ 1.1150 = 1327.74887892 KRW/USD.
- 원화는 반올림 전 달러 합계 × 반올림 전 교차환율로 계산하고 마지막에 원 단위로 반올림합니다.

## 미환산 범위

- codex-auto-review: 2,244,795 토큰

[자동 검토 모델 조사 근거](./AUTO_REVIEW_RESEARCH.md)


## 파싱 진단

```json
{
  "files": 961,
  "invalid_json_lines": 0,
  "unusable_usage_records": 0,
  "cache_lifetime_mismatch": 0,
  "model_conflicts": 0,
  "codex_request_counter_mismatch": 1
}
```

단가·환율 스냅샷은 `ai-pricing.json`에 보관합니다. 재집계 스크립트는 네트워크에 접속하지 않으므로, 날짜가 지난 단가와 환율은 새 공식 자료로 확인 후 직접 갱신해야 합니다.
