# CivicLens — 세션 핸드오프 메모 (2026-08-21 기준)

새 Cowork 세션에서 이 문서를 먼저 읽고 이어서 진행할 것. CLI(Claude Code) 세션도 필요시 이 문서를 참고.

## 프로젝트 한 줄 요약

CivicLens: 미국 연방의회(Congress) 투명성 대시보드. 이념/평가 라벨 없이 1차 공식 출처(Congress.gov, GovInfo, senate.gov, clerk.house.gov, FEC, Census)의 사실만 제공. poliwiki.kr 벤치마킹. **최종 목표: 결제/광고를 통한 수익화.**

- Live: https://civiclens-web-livid.vercel.app
- Repo: `CSan0725/civiclens` (public, GitHub)
- PRD: `PRD-US-Political-Tracker-v1.md` (워크스페이스 루트) — 모든 결정의 원천. 섹션 번호가 계속 바뀌므로 매번 Read해서 확인할 것.
- 진행 기록: `docs/P1~P3-source-verification.md` (CLI가 실측 기반으로 작성)

## 핵심 원칙 (절대 흔들리면 안 되는 것들)

- FC-1/FC-4: 1차 공식 출처만, 이념·해석·평가 라벨 금지. 랭킹도 순수 집계일 뿐 "잘했다/못했다" 판단 없음.
- FC-3: "publish unless contradicted" — Voteview와 불일치하는 표결만 `is_published=false`로 보류, 나머지는 기본 공개.
- NFR-5: 모든 사실에 source_url + retrieved_at. (단, 현재 votes/bills 테이블은 retrieved_at이 비어있고 source_url로 우회 중 — 아래 "알려진 갭" 참조)
- 측정 우선(measure before assuming): 매 단계마다 실측 후 문서화. 가정으로 진행하지 않음.
- 자연키 기반 멱등 upsert. 스키마 소유자는 dbmate 마이그레이션(`packages/db/migrations/`)뿐.

## 아키텍처

- Next.js(App Router, TS) + Tailwind + shadcn/ui → Vercel
- Python(uv) ETL → GitHub Actions 크론
- PostgreSQL+PostGIS on Neon (serverless) — pooled(앱 런타임)/unpooled(마이그레이션·대량쓰기) 구분 필수
- GitHub Actions: public repo라 무료. `migrate.yml`은 dry_run 기본값 true이므로 실제 적용 시 반드시 체크 해제.
- R2는 아직 미설정(프로비저닝만 됨, 사용 안 함)

## 진행 현황 (2026-08-20 기준 완료)

- P0: 스캐폴딩, IA 전체 라우트 뼈대
- P1: Congress.gov 수집(법안/의원/위원회/하원표결, 2017~)
- P1.5: Speaker 선거 등 비표준 표결 저장(`raw_position`) + GitHub Actions v5 업그레이드
- P2: Clerk XML 백필(1990~2016) + Voteview 대조, FC-3 정책 확정(migration 0004)
- P5-thin: 대시보드 + 의원 프로필 (실데이터)
- P3: GovInfo Congressional Record 발언 수집 — 49,171건 granule, 화자 매칭 57%, `/speeches` 전문검색 라이브
- **P5 확장 (최신, 2026-08-20 완료·배포됨)**: `/bills`, `/bills/[congress]/[type]/[number]`, `/votes`, `/votes/[id]`, `/rankings` 5개 라우트 전부 실데이터로 구현·라이브 배포 확인 완료. 커밋 `efd70c4`.

## ✅ 완료 — 작업 A 종료 (2026-08-21)

**vote.bill_id NULL 원인조사 → 근본 원인 확정 → 119대 bill 전량 백필 → 양원 링크 완료.**

- **근본 원인**: vote 링크 코드는 정상이었다. `bill` 테이블이 `--limit` 걸린 **150행 샘플**이라 링크할 대상 자체가 없었던 것. 그 150의 출처는 `collect-daily.yml`의 `BILL_LIMIT` 기본값이다.
- **카탈로그**: `bill` 150 → **18,396건(119대 전량)**, `bill_action` 486 → 74,391, `sponsorship` 1,458 → 189,661.
- **링크 최종**:

| chamber | 표결 | 링크됨 | NULL | 링크 가능분 기준 |
|---|---:|---:|---:|---:|
| house | 645 | 638 | 7 | **638/638 = 100%** |
| senate | 831 | 430 | 401 | **430/430 = 100%** |

  남은 NULL 408건은 전부 **법안이 존재하지 않는 표결**이다 — 하원은 정족수 호명·의장선출·산회동의 7건,
  상원은 지명·조약 401건. 수집 갭이 아니다.
- **FC-3 상태 정상**: 하원 645 공개, 상원 829 공개 / 2 미공개(open flag 보유 = 반증된 집계, 정당한 보류).

### 남은 후속 (작업 A와 무관, 별도 착수)

- **daily job `BILL_LIMIT=150`** — 그대로 두면 카탈로그가 다시 드리프트한다. resume skip 덕에 재fetch가
  값싸졌으므로 상향 또는 `--since` 배선 검토. **이것만 남았다.**

상세 수치·근거는 `docs/vote-bill_id-null-investigation.md`.

### 이 작업에서 드러난 코드 결함 6건 (전부 수정·푸시·CI 그린)

18,396건을 처음 전량 훑고 상원을 처음 재수집하면서 나온 것들이라, 150건짜리 daily 잡으로는 영원히 안 보였을 문제들이다.

| 커밋 | 문제 |
|---|---|
| `545a338` `248b9f7` | `sync_bills`가 전체 런을 단일 트랜잭션으로 커밋 → 10시간짜리 트랜잭션. bill당 커밋 + provenance 기반 resume skip |
| `eb0cb3c` | Congress.gov가 동일 액션 2회 반환 → `ON CONFLICT DO UPDATE` 거부. 삽입 전 dedupe |
| `3e1e038` `4204b2e` | 동일 의원이 cosponsor 2회 등장(철회 후 재발의). 최신 에피소드를 날짜 기준 선택 |
| `e1202c6` | **"votes 재실행하면 bill_id가 소급 채워진다"는 전제가 틀렸다.** `skip_existing=True`가 기본이라 upsert 자체가 안 돈다. `--refresh`를 votes에 배선 |
| `540ec6a` | **재수집이 하원 645건을 `is_published=false`로 만들어 사이트에서 숨겼다.** 파서가 0004 이전 규칙 유지 중. 세 파서 모두 이 컬럼 미기입으로 변경 + 데이터 복구 |
| `6eed6fb` | 상원 수정안 표결 161건이 모법안에 링크 안 됨. `<document>`는 수정안 자신을 기술하고 모법안은 `<amendment_to_document_number>`에 "S.Con.Res. 7" 형태 완전인용으로 존재(type 필드 없음) → 인용문 분해 후 기존 `_resolve_bill` 재사용 |

⚠️ `540ec6a`는 라이브 사이트가 실제로 깨졌던 건이다. **`votes --refresh` 후에는 `is_published` 분포를 확인할 것.**
(파서 수정 후 상원 재수집에서는 재발하지 않음을 실측 확인했다.)

### senate.gov 접근 (반복해서 걸리는 부분)

- 개발 네트워크에서 **403** — 샌드박스 해제해도, WebFetch로도 동일. UA 스푸핑은 하지 않는다(P1 Finding 7).
- GitHub Actions 러너는 정상. **원본 XML이 필요하면** `verify-senate-live`를 `roll_number` 지정해 디스패치하면
  `<document>`/`<amendment>`를 로그에 찍고 원본을 `senate-vote-xml` 아티팩트로 올린다(`7d254b0`).
- `gh` CLI는 이 머신에 설치돼 있고(`C:\Program Files\GitHub CLI`, `~/.local/bin/gh` 심링크),
  토큰은 `repo`+`workflow` 스코프면 충분하다. `gh auth login --with-token`은 `read:org`를 요구하므로
  **`GH_TOKEN` 환경변수로 넘기는 편이 낫다**(로그인 검증을 건너뛰고 실제 스코프만 사용).

## 알려진 갭 (백로그, 막히지 않고 진행 중)

1. `retrieved_at`이 speech 테이블 제외 전부 NULL — NFR-5 부분 미충족. 수집 시각은 `provenance` 테이블에 자연키로 존재하며, 상세 페이지는 거기서 읽어 우회한다(vote는 source_url 완전일치로 챔버 모호성 해소).
3. PRD §18 백로그: 로비 자금 데이터 (LDA.gov LD-2/LD-203 기반, OpenSecrets는 상업적 이용 불가라 배제) — 미착수.
4. PRD §19 백로그: 구독/수익화 아키텍처 (Neon Auth + Stripe Checkout, DB 역할 분리) — 설계만 문서화됨, 미착수.
5. (해소됨) `/districts/[geoid]` 상세 구현 완료 — 2d.
6. **Neon `member`/`term`에 118대 구멍** — 슬라이스 3개 주의 118대 하원 term이 로컬 68 대 Neon 60이고,
   118대에만 재직한 5명(Steel·Duarte·Nickel·Jackson·Manning)이 Neon `member`에 아예 없다.
   그 5명의 2022년 후보 레코드가 의원 프로필로 안 이어진다. 해결은 Neon에
   `civiclens-etl members --congress 118` 1회 — 공용 테이블이라 사용자 결정 대기.

## P4 슬라이스 0 진행 상황

| 단계 | 상태 |
|---|---|
| 1. 경계 WY/NC/CA → PostGIS(로컬+Neon) + TopoJSON → R2 | ✅ |
| 2a. 지오코더 API route + 대표 3인 | ✅ |
| 2b. `/districts` MapLibre 지도 | ✅ |
| **2c. FEC 후보·자금·당락 (로컬 + Neon)** | ✅ **2026-08-27** |
| **2d. `/districts/[geoid]` 상세 페이지** | ✅ **2026-08-27** |
| 3. 경계 전량(47개 주+DC/준주) | ⬜ (§8-E 준주 결정 선행) |
| 4. FEC 전량(50개 주) | ⬜ |

### 2c 요약 (상세: `docs/P4-candidates-verification.md`)

WY+NC+CA 후보 **1,404명**(CA 1,005 / NC 355 / WY 44), 자금·당락·`candidate_election`까지
**로컬과 Neon 양쪽 적재 완료**. 2022 당선 69명이 실제 의석수와 정확히 일치.

설계문서 전제 4개가 실측과 달랐고 그중 **§8-A(당락 소스) 결정이 뒤집혔다** —
OpenElections `fec_results`는 2014년까지만 발행하고, 하는 일이 FEC 자신의 워크북 파싱이라
**FEC 원본을 직접 읽는다**. FEC 발행 현황상 2022만 W/L/N이 완전하고, 2024는 본선 명부뿐(부재→N),
2026은 선거 전이다. → **NULL의 의미가 cycle마다 다르다. UI는 cycle 단위로 설명해야 한다(FR-C4).**

마이그레이션 2건 추가: **0006 `candidate_election`**(지역구는 후보가 아니라 선거에 붙는다 —
`/districts/[geoid]`는 반드시 이 테이블을 읽어야 한다) · **0007 `unaccent`**.

### 2d 요약

`/districts/[geoid]`가 스텁을 벗었다. 대표 3인 + 지역구별 최근 5년 후보(정당·자금·당락) +
주 단위 상원 후보 + cycle 단위 커버리지 카피.

- **후보는 `candidate_election` 조인**이다. 실증: Bera는 CA-06 페이지에 2022·2024로,
  CA-03 페이지에 2026으로 뜬다. `candidate.district`(=3)를 썼다면 CA-03에 세 번 다 뜨고
  CA-06에는 아예 안 떴다.
- **빈 당락의 의미를 cycle이 정한다**(`lib/election-outcome.ts`). 연도를 하드코딩하지 않고
  적재된 행에서 **도출**한다 — FEC가 2024 집계를 내면 코드 수정 없이 문구가 바뀐다.
- `?cycle=2022`로 특정 선거를 열 수 있다(서버가 결정 → JS 없이도 동작).
- 미적재 주(예: TX-37)는 404가 아니라 "실재하는 지역구인데 아직 안 실었다 + 적재된 주 목록".
- **미표시 결정 1건**: `candidate.incumbent_challenge`(현직/도전자)는 후보당 1값(최신)이라
  선거별 행 옆에 두면 틀린 진술이 된다. 표시하지 않는다 — `candidate.district`와 같은 오류 부류.

## 다음 단계 후보

- (A) `vote.bill_id` NULL 원인조사 — ✅ 종료.
- (B) P4 — 슬라이스 0의 2d까지 완료. **다음은 슬라이스 0 전체 end-to-end 검증(M4).**
- (C) 백로그 항목(로비 데이터, 구독 아키텍처) 미착수.

## 자격증명 프로토콜 (반드시 지킬 것)

- DB 비밀번호는 **이 채팅(Cowork)에 절대 붙여넣지 않음.**
- CLI(Claude Code)가 Neon 접속이 필요하면 별도 PowerShell 창에서:
  ```powershell
  $u = Read-Host "Neon URL"
  Set-Content -Encoding utf8 -Path "<CLI가 알려준 경로>" -Value "DATABASE_URL_UNPOOLED='$u'"
  ```
- CLI의 스크래치패드 경로(`...\Temp\claude\...\<세션ID>\scratchpad\`)는 **세션마다 바뀜** — 매번 다시 입력 필요.
- ⚠️ **`Set-Content -Encoding utf8`은 Windows PowerShell 5.1에서 BOM을 붙인다.** dbmate는 BOM이 붙은
  env 파일을 파싱하지 못하고 `unexpected character "»" in variable name` 에러를 내면서
  **파일 내용(=접속 URL 전체)을 에러 메시지에 그대로 출력한다.** 2026-08-27에 실제로 그렇게 노출됐다.
  → `Set-Content -Encoding utf8NoBOM`(PS7) 또는
  `[IO.File]::WriteAllText($path, "DATABASE_URL_UNPOOLED='$u'`n")`으로 쓸 것.
  psycopg는 BOM에 영향받지 않으므로 ETL만 쓸 때는 드러나지 않는다 — dbmate를 태울 때만 터진다.
- **제안했지만 아직 미실행**: `%USERPROFILE%\.civiclens-secrets\neon.env`에 pooled+unpooled URL을 영구 저장해두면 매번 재입력 안 해도 됨 (트레이드오프: 평문 파일이 디스크에 계속 남음). 원하면 이 방법으로 전환 가능.
- 로컬 `.env` / `pipelines/etl/.env`의 `DATABASE_URL`은 항상 `localhost:55432`(Docker)를 가리켜야 함 — 절대 Neon으로 바꾸지 말 것.

## 새 세션 시작 방법

새 Cowork 세션을 열고 다음과 같이 말하면 됨:

> "D:\William_Workspace\30_PRODUCTS\Politics\docs\SESSION-HANDOFF.md 읽고 이어서 진행하자"

이후 필요하면:
- 최신 상태 재확인이 필요하면 PRD와 `docs/P1~P3-source-verification.md`를 추가로 Read하라고 지시
- CLI(Claude Code) 작업은 별도 터미널에서 계속 진행 — Cowork(나)는 프롬프트 작성/검증/리뷰 역할 유지
- 작업 후 결과 스크린샷 붙여넣으면 "결과 검토, 검증, 분석하고 다음 스텝 추천해" 패턴으로 진행하면 됨(지금까지의 표준 워크플로우)
