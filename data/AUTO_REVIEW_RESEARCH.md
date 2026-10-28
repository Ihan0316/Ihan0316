# 자동 승인 검토 모델·단가 확인

확인일: 2026-10-28, Asia/Seoul.

## 확인된 사실

- [OpenAI 공식 발표](https://x.com/OpenAI/status/2082878180478910571)는 ChatGPT 앱과 Codex CLI의 Auto-review를 GPT-5.4에서 GPT-5.6 Luna로 전환한다고 명시합니다. 브라우저에서 확인한 게시 시각은 한국시간 2026-07-31 02:17입니다.
- [Codex 공식 공개 소스](https://github.com/openai/codex/blob/main/codex-rs/model-provider/src/provider.rs)는 API 키 인증의 검토 모델을 `gpt-5.6-luna`, 그 외 기본 검토 모델 ID를 `codex-auto-review`로 구분합니다. 이는 클라이언트 요청 이름에 대한 증거이며 서버 내부 모델의 실시간 증명은 아닙니다.
- 로컬 모델 카탈로그의 `codex-auto-review` 설명은 `Automatic approval review model for Codex.`이고 `auto_review_model_override`는 null입니다. 검토 기록의 구조화된 모델 필드에는 `codex-auto-review`만 있으며, 실제 처리 모델 이름은 노출되지 않습니다.
- 이번 보관 기록의 자동 검토 날짜는 2026-10-26~2026-10-28로 위 발표 이후입니다. 따라서 카드의 API 환산에서는 공식 발표에 근거해 Luna로 매핑합니다. 개별 요청의 실제 처리 모델을 직접 관측했다는 뜻은 아닙니다.

## 공식 API 단가

[GPT-5.6 Luna 공식 모델 문서](https://developers.openai.com/api/docs/models/gpt-5.6-luna), 확인일 기준 Standard 가격, USD / 100만 토큰:

| 구분 | USD |
|---|---:|
| 일반 입력 | 0.20 |
| 캐시 읽기 | 0.02 |
| 캐시 생성 | 일반 입력의 1.25배 |
| 출력 | 1.20 |

입력 272,000 토큰 초과 요청은 문서의 장문 조건에 따라 요청 전체 입력에 2배, 출력에 1.5배를 적용합니다. 실제 검토 기록의 정상 집계분에는 장문 요청과 캐시 생성 토큰이 없습니다. 누적 증가분과 마지막 요청 사용량이 맞지 않는 기록은 금액에서 제외합니다.

## 실제 과금과 API 환산액

[현재 OpenAI 과금 안내](https://help.openai.com/en/articles/20001415-chatgpt-rate-card-enterprise-token-based-pricing)는 ChatGPT 계정으로 로그인한 Auto-review 안전 검토를 무료로 안내하며 플랜 사용 한도에도 포함하지 않는다고 명시합니다.

이 카드의 금액은 같은 토큰을 공개 API 단가로 평가한 비교용 추정액입니다. 실제 결제액이나 현재 구독 한도 사용량을 뜻하지 않습니다. 현재 무료 정책을 과거의 모든 사용 시점에 소급해 단정하지 않습니다.

## 남는 한계

서버가 개별 요청에서 실제 실행한 모델의 체크포인트·정확한 버전을 로컬 기록으로 확인할 수 없습니다. 공식 발표 이후 별칭의 서버 라우팅이 계속 동일했는지도 개별 요청 단위로 검증할 수 없습니다. 따라서 `공식 발표 기준 Luna 매핑`이라는 출처와 한계를 유지합니다.
