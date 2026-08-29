# 수익화(§19) 설계문서 — 구독/결제 아키텍처 (2026-08-28)

P4(지도·지역구·대표·표결·법안·후보 전량) 완료 후 착수하는 수익화 단계. PRD §19가 아키텍처 결론을 이미 냈고(백엔드 재설계 불필요, 컴포넌트 추가), 이 문서는 그 위에 **현행(2026) 스펙 검증 + 구체 설계 + 미결 결정**을 얹는다. 리서치는 공식 문서 실측 기준.

## 0. 목표와 원칙

- **목표**: 첫날부터의 운영 목표인 수익화. 제품이 기능 완성됐으니 구독을 얹는다.
- **원칙 충돌 없는 것만 유료화**(PRD §19.3): **원자료 화면 열람은 영구 무료**(핵심 가치·poliwiki 벤치마크). 유료는 그 위의 편의(광고 제거·알림·대량 접근)만.
- **카드정보 무취급**: Stripe 호스팅 결제 UI만 사용, 우리 서버는 카드 데이터를 절대 다루지 않음(PCI 범위 최소화).

## 1. 아키텍처 — 백엔드 유지, 4개 컴포넌트 추가

PRD §19.1 결론대로 Neon Postgres + Vercel + GitHub Actions ETL은 그대로. 얹을 것:

| 컴포넌트 | 역할 | 상태 |
|---|---|---|
| 인증(Auth) | 로그인/세션 | **결정 필요(§2)** |
| 결제(Payments) | Stripe 구독 | 설계 확정(§3) |
| DB 역할 분리 | ETL role vs 웹앱 role | 설계 확정(§4) |
| 레이트리밋 | 유료 API 접근 유료화 시에만 | **지금 안 함**(OQ-7 의존) |

**force-dynamic이 오히려 이점**(§19.1): 지금 페이지가 매 요청 DB 직접 조회라, 로그인 상태별 개인화 화면과 잘 맞음. 비용 리스크로 지적됐던 특성이 구독에선 장점.

## 2. ⚠️ 인증 — Neon Auth가 바뀌었다 (결정 필요)

**리서치 실측**: Neon Auth가 재구축됨. 신규 프로젝트는 이제 두 갈래:
- **Managed Better Auth**(현재 기본, [Better Auth](https://www.better-auth.com/) 오픈소스 기반, **Beta**): 사용자를 Postgres `neon_auth` 스키마에 **직접** 저장(웹훅 동기화 없음, DB가 정본), SQL 조인 가능, RLS 호환. 무료 **60,000 MAU**까지. **AWS 전용**(우리 프로젝트 AWS Ohio라 OK), IP Allow/Private Networking과 비호환.
- **Legacy Stack Auth**: `neon_auth.users_sync` 테이블 비동기 동기화. **신규 프로젝트엔 아카이브됨**.

즉 PRD §19가 전제한 "Neon Auth = Stack Auth `users_sync`"는 **옛 모델**. 지금 고르면 Better Auth(Beta)다.

**옵션 3개 (선택 필요):**

| 옵션 | 장점 | 단점 |
|---|---|---|
| **A. Neon Auth(Managed Better Auth)** | 신원이 우리 Neon DB에 있어 SQL 조인·브랜칭, 최소 의존성 원칙 부합, 동기화 지연 없음 | **Beta**(프로덕션 수익화엔 리스크), AWS·네트워크 제약 |
| **B. Better Auth 직접(self-host) 또는 Auth.js** | 성숙·안정, 우리 Postgres에 직접 기록(신원 우리 DB 유지), 벤더 추가 없음 | 배선을 더 소유, 호스팅 관리 UI 없음 |
| **C. Clerk** | 성숙한 호스팅 제품, UI·조직 기능 완비 | 신원이 Clerk에 있음(웹훅 동기화), 벤더+비용 추가, "신원 우리 DB" 원칙 이탈 |

**내 권장: B(Auth.js/NextAuth + Postgres adapter) 또는 B'(Better Auth 라이브러리 직접)**. 이유 — 수익화는 프로덕션이라 **Beta 의존은 피하는 게 안전**하고, PRD의 "신원을 우리 DB에" + "최소 의존성" 원칙은 B에서도 충족(Postgres adapter가 우리 Neon에 user 테이블 기록). Neon Auth(A)는 GA 되면 재검토. → **§11에서 확정.**

**Next.js App Router 통합 공통**: 세션 쓰는 서버 컴포넌트는 `force-dynamic`(우리 현재 모델과 일치). 라우트 보호는 middleware(Next 16은 `proxy.ts`).

## 3. 결제 — Stripe Checkout 구독 (설계 확정)

리서치 실측 기준:

- **Stripe Checkout `subscription` 모드**(Stripe 호스팅 페이지) — 카드 데이터 우리 서버 미접촉, PCI 최소. Elements는 결제 UI 임베드 필요 시에만.
- **호스팅 Customer Portal** — 플랜 변경·결제수단·해지·인보이스를 사용자 셀프서비스. 우리가 구현할 범위 최소.
- **동기화 웹훅**(로컬 Subscription 레코드 유지): `checkout.session.completed`, `customer.subscription.created/updated/deleted`, `invoice.paid`, `invoice.payment_failed`. `invoice.paid`+status=active에 접근 부여, `canceled/unpaid`에 회수. status 전이(trialing/active/past_due/canceled/unpaid/incomplete) 추적.
- **서명 검증**: `stripe.webhooks.constructEvent(rawBody, sig, whsec_...)`, **원본 바디 그대로**(App Router는 `await request.text()`로 raw 취득, bodyParser 설정 불필요). 5분 replay 허용, 이벤트 ID 로깅으로 중복·순서없음 처리.
- **로컬 개발**: `stripe listen --forward-to localhost:PORT/api/webhooks/stripe`가 `whsec_` 출력, `stripe trigger`로 이벤트 발생.
- **수수료**: 미국 카드 2.9% + 30¢/건, 설치·월정액 없음.
- **주의**: 웹훅 라우트를 Edge 런타임에 두면 `constructEventAsync` 써야 함(Node 런타임이면 동기 버전 OK). `STRIPE_SECRET_KEY`/`STRIPE_WEBHOOK_SECRET`에 `NEXT_PUBLIC_` 절대 금지.

## 4. DB 역할 분리 (설계 확정, P6 하드닝)

지금 웹앱은 ETL과 같은 `neondb_owner`로 접속. 구독 도입 시:
- **`etl_writer` role**: 공공데이터(bill/vote/member/district/candidate…) 쓰기. GitHub Actions·로컬 ETL이 사용.
- **`webapp` role**: 공공데이터 **읽기 전용** + 사용자/구독 테이블 **읽기·쓰기**. Vercel 런타임이 사용.
- 사용자/결제 테이블은 webapp만 쓰기, ETL은 접근 없음. dbmate 마이그레이션으로 role·GRANT 정의(스키마 소유자 원칙).
- Neon Auth(A) 선택 시 `neon_auth` 스키마 권한도 webapp에 부여.

## 5. 데이터 모델 (§6 확장, dbmate 마이그레이션)

```
-- 신원: 선택한 Auth가 관리(Neon Auth면 neon_auth 스키마, Auth.js면 아래를 adapter가 생성)
user(id PK, email, created_at, ...)

subscription(
  stripe_subscription_id  TEXT PK,          -- 자연키(기존 fec_candidate_id 등과 동일 원칙)
  user_id                 FK → user(id),
  stripe_customer_id      TEXT NOT NULL,
  plan                    TEXT,
  status                  TEXT CHECK (status IN ('trialing','active','past_due','canceled','unpaid','incomplete')),
  current_period_end      TIMESTAMPTZ,
  created_at, updated_at
)
```
자연키 우선(§6 원칙): `stripe_subscription_id`/`stripe_customer_id` 그대로 자연키. 멱등 upsert(웹훅 재전송·순서없음 대비).

## 6. 유료화 대상 — OQ-7 (결정 필요)

PRD §19.3 후보(원칙 충돌 없는 것만):

| 후보 | 필요 컴포넌트 | 착수 난이도 | 선결 조건 |
|---|---|---|---|
| 광고 제거 | Auth+결제 | 낮음 | **먼저 광고를 붙여야 함**(지금 광고 없음) |
| 관심 의원/법안 알림 | Auth+결제+이메일(Resend 등) | 중간 | 알림 기능 신규 구현 |
| 저장/워치리스트·개인화 | Auth+결제 | 낮음 | — |
| 대량 다운로드/API 접근 | Auth+결제+레이트리밋 | 높음 | 레이트리밋 도입 |
| **원자료 열람 유료화** | — | — | **채택 안 함(원칙 충돌)** |

**내 권장 첫 유료 기능**: **저장/워치리스트 + 알림**(개인화 계열). 이유 — (1) 광고 제거는 광고를 먼저 붙여야 해서 선결이 크고, (2) 개인화(관심 의원·법안 저장, 변경 알림)는 "로그인 가치"가 명확해 무료 가입→유료 전환 퍼널이 자연스럽고, (3) 원자료 무료 원칙과 무충돌. → **§11에서 확정.**

## 7. 게이팅 방식

- 무료: 원자료 전량 열람(현재 그대로). 로그인 없이.
- 유료: 세션(로그인) + `subscription.status ∈ {trialing, active}` 확인 후 기능 노출. force-dynamic이라 요청마다 판정 가능.
- 게이팅은 **서버에서**(라우트·서버 컴포넌트) — 클라이언트 우회 불가. 무료 사용자에겐 정직한 업셀 화면(FC 원칙: 오해 없는 카피).

## 8. Vercel Pro (결제 전 필수)

- Vercel Hobby는 **비상업 전용**(약관). 수익화 앱은 **Pro 필수**($20/seat/월, $20 사용크레딧 포함). "수익화 landing page만 있어도 첫날부터 commercial".
- → **결제 기능 라이브 전에 Pro 전환** 필요. 기부는 Hobby에서 허용되나 구독 과금은 아님.

## 9. 시퀀싱 — 얇은 슬라이스

P4처럼 얇게 관통 검증:

1. **슬라이스 0(Auth)**: 인증 붙이기(로그인/로그아웃/세션), user 테이블, 보호 라우트 1개. 결제 없이 "로그인" 자체 검증.
2. **DB 역할 분리**: etl_writer / webapp role 마이그레이션, Vercel `DATABASE_URL`을 webapp role로 전환. (기존 Neon 비번 교체 경험 재사용.)
3. **구독(Stripe)**: subscription 테이블, Checkout(subscription) + Customer Portal + 웹훅 라우트. **테스트 모드**로 전 라이프사이클(체험→활성→해지→연체) 검증(Stripe CLI).
4. **게이팅 1개 기능**: §6 확정 기능을 무료/유료로 게이트. 실제 브라우저 end-to-end.
5. **Vercel Pro 전환 + 라이브**: 실결제 전환, 프로덕션 웹훅 엔드포인트 등록.

각 단계 로컬 먼저 → 검증 → 배포. CLI 실행 / Cowork 리뷰.

## 10. 리스크

| 리스크 | 완화 |
|---|---|
| Neon Auth Beta 불안정 | 옵션 B(성숙한 Auth.js/Better Auth 직접) 권장, Neon Auth는 GA 후 |
| 웹훅 유실·중복·순서없음 | 이벤트 ID 로깅 멱등, 서명 검증, status는 웹훅이 정본 |
| 카드정보 취급 리스크 | Stripe 호스팅 Checkout만, 서버 미접촉 |
| ETL/웹앱 권한 혼재 | role 분리(§4)로 결제 테이블을 ETL에서 격리 |
| Hobby 약관 위반 | 결제 라이브 전 Pro 전환 |
| 원자료 유료화 유혹 | 명시적 배제(§0·§6), 개인화·편의만 유료 |

## 11. 결정 (2026-08-28)

- **A. 인증**: ✅ **Better Auth 라이브러리 직접**(2026-08-28 실측 확정). 근거: (1) Auth.js README가 신규 프로젝트에 Better Auth 권고(Auth.js가 Better Auth에 합류), (2) "Beta 회피"가 실은 Auth.js에 부메랑 — NextAuth v5는 3년째 beta, Better Auth 1.7.2는 GA, (3) Postgres 1급 내장(기존 pg Pool 주입)·`@auth/core`의 preact 런타임 의존 회피·`drizzle-orm ^0.45.2` peer 정확 일치, (4) 옵션 A(Neon Auth Managed)의 정체가 Better Auth라 GA 시 업그레이드 경로 동일. **주의**: `@better-auth/cli migrate` 금지 — `generate`로 schema.sql만 뽑아 dbmate 마이그레이션(0009_auth.sql)에 수동 이관, dbmate 단일 정본 유지. snake_case는 `fields` 매핑. proxy.ts는 게이팅 아님(§7, "낙관적 리다이렉트"만), 텔레메트리 `BETTER_AUTH_TELEMETRY=0` 명시.
- **B. 첫 유료 기능**: ✅ **저장·워치리스트 + 알림**(관심 의원·법안 저장 + 변경 알림). 개인화 계열, 원자료 무료 원칙 무충돌.
- **C. 요금제**(미결): 무료/유료 티어·가격·체험판. → 구독(Stripe) 슬라이스 착수 전 결정. 슬라이스 0(Auth)엔 불필요.
- **D. Vercel Pro 전환 시점**: 결제 라이브 직전(슬라이스 5).
- **E. 이메일 발송**: 알림 기능에 Resend 등 필요 — 게이팅 슬라이스(4) 착수 시 결정.

## 12. 착수 순서 요약

미결 A~E 확정 → 슬라이스 0(Auth) → DB 역할 분리 → 구독(Stripe 테스트모드) → 게이팅 1개 → Vercel Pro+라이브. P4와 동일하게 "리서치·설계 먼저, 로컬 검증 먼저, CLI 실행/Cowork 리뷰".
