# PRD — 미국 정치 트래킹 플랫폼 (US Build)

**문서 버전:** v1.0 (기획 완성본, 착수 전)
**제품 코드명:** (미정 — 예: OpenGov Tracker / CivicLens)
**벤치마크:** poliwiki.kr — 원자료 제공, 정치인·법률 평가하지 않음
**대상 국가:** 미국 연방 의회 (하원 435 + 상원 100). 영국은 후속.
**빌드 방식:** 본 PRD 확정 후 CLI(Claude Code)로 구현.

---

## 0. 문서 목적

CLI 기반 구현에 바로 투입 가능한 수준의 제품 요구사항 정의서. 기능·데이터·아키텍처·수용기준을 요구사항 ID로 명세한다. 미확정 항목은 §17에 격리.

---

## 1. 비전 & 목표

- **비전:** 미국 연방 의회의 활동을 누구나 중립적으로, 공식 자료에 근거해 탐색할 수 있는 오픈 데이터 대시보드.
- **핵심 가치:** 원자료(raw) 제공 · 성향/의도 평가 없음 · 모든 사실의 공식 소스 소급성 · 팩트 신뢰 최우선.
- **1차 성공 정의:** 사용자가 (a) 내 지역구 대표를 지도로 찾고, (b) 그들의 표결·발의·발언을 확인하고, (c) 최근 의회 현안을 대시보드에서 한눈에 보는 것.

### 1.1 목표 (Goals)
- G1. 현직 의원의 법안·표결·발언·위원회 활동을 공식 소스 기반으로 통합 제공.
- G2. 주소/지도로 "내 지역구" → 하원 1 + 상원 2 + 최근 5년 후보 매핑.
- G3. 출석률·표결참여율 등 객관적 카운트 지표를 중립 랭킹으로 제공.
- G4. 국가 확장 가능한 구조(프레젠테이션 통합, 데이터 파이프라인 분리)로 향후 UK 온보딩.

### 1.2 비목표 (Non-Goals) — 명시적 제외
- N1. 정치인 성향·이념 점수화, 정렬된 "좋은/나쁜 의원" 평가.
- N2. 사설·오피니언·팩트체크 판정 생성(우리가 진위 판정하지 않음. 공식자료 정리·링크만).
- N3. 주(State) 의회·지방선거 (MVP 제외, 향후 검토).
- N4. 사용자 계정·소셜 기능 (MVP 제외; 알림은 v2+).
- N5. 뉴스 기사 전문 저장·재현 (저작권. §12 준수).

---

## 2. 사용자 & 유스케이스

**주요 사용자**
- 일반 시민(지역구 대표 확인·현안 파악)
- 기자·연구자(표결·발의 이력 조회)
- 학생·교육(입법 과정 학습)

**대표 유저스토리**
- US-1. 시민으로서 내 주소를 넣으면 내 지역구 의원 3명을 보고 싶다.
- US-2. 특정 의원 이름으로 검색해 그 사람의 표결·발의·발언을 보고 싶다.
- US-3. 대시보드에서 최근 통과 법안과 최근 표결을 바로 보고 싶다.
- US-4. 의원들의 출석률·표결참여율 순위를 보고 싶다(재미/비교).
- US-5. 우리 지역구에서 최근 5년간 누가 출마했는지 보고 싶다.
- US-6. (v2) 특정 의원과 관련된 최신 뉴스/성명을 대시보드에서 바로 훑고 싶다.

---

## 3. 범위 (Scope) — 확정

### MVP (v1)
- 대시보드(최근 법안·표결·발언)
- 의원 검색 + 프로필
- 지도 "내 지역구" + 대표 3인 + 최근 5년 후보
- **공식 발언만** (Congressional Record / GovInfo) — 뉴스 없음
- 출석률·표결참여율 랭킹
- **하원 표결: 2017~(115대) 공식 API + Clerk XML 백필(1990~2016) 포함** ✅
  - ~~2023~ 공식 API + Clerk XML 백필(1990s~2022)~~ — 착수 전 기재값. P1 실측(2026-08-16) 결과 House Votes 베타는 115대(2017)부터 제공되어 백필 구간이 6년 축소. §5 각주 참조.
- 상원 표결: senate.gov XML

### v2
- **뉴스 계층(대시보드 내 카드형 소비)** — §12
- 알림(관심 의원/법안 업데이트)
- 발언·법안 고급 검색/필터

### v3
- 의원 비교 뷰
- UK 온보딩(국가 스위처)
- 데이터 다운로드/공개 API

### 백로그 (우선순위 미정 — §18, §19 참조)
- 로비 데이터(Lobbying Disclosure) — 정치인별 로비 활동·기부 내역
- 구독/수익화 아키텍처 — 계정·결제·요금제(§19)

---

## 4. 기능 요구사항 (Functional Requirements)

### 4.1 대시보드 (FR-D)
- FR-D1. 홈에 위젯 노출: 최근 통과 법안 / 최근 롤콜 표결 / 최근 본회의 발언 / 최근 주요 액션.
- FR-D2. 각 위젯은 최신순 N건, "전체 보기"로 목록 페이지 이동.
- FR-D3. 각 항목에 원자료 링크(source_url) 표시.
- FR-D4. 국가 스위처 자리 확보(MVP는 US 고정, 향후 UK 활성).
- FR-D5. (v2) 뉴스/성명 피드 위젯 — §12.
- 수용기준: 홈 최초 로드 시 실데이터 위젯 4종 렌더, 각 항목 원문 링크 유효.

### 4.2 의원 검색 & 프로필 (FR-M)
- FR-M1. 이름·주·정당·지역구로 검색(자동완성).
- FR-M2. 프로필 구성: 기본정보(정당·주·지역구·임기·사진), 대표발의/공동발의, 표결 이력, 발언, 위원회.
- FR-M3. status 구분: current / former / candidate_only.
- FR-M4. 표결 이력은 안건·날짜·본인 포지션 + 법안 링크.
  - 포지션 표기는 Yea/Nay/Present/NotVoting **+ 기타(원본 문자열 그대로)**. 의장 선출처럼 후보명으로 기록되는 표결이 실재하므로(§11 각주 1), 4개 값에 없는 포지션은 `vote_cast.raw_position`의 원문을 그대로 노출한다. 임의로 Yea/Nay에 편입하지 않는다(FC-4).
- FR-M5. 발언은 날짜·제목·전문(또는 발췌)·GovInfo 원문 링크.
- FR-M6. 프로필 상단에 개인 지표 요약(출석률·표결참여율·발의수) + 방법론 링크.
- 수용기준: 현직 전원(535) 프로필 생성, 표결/발의/발언 최소 1소스 연결.

### 4.3 지역구 지도 (FR-G)
- FR-G1. 주소 입력 → Census Geocoder → 지역구 판별.
- FR-G2. 지도에서 지역구 클릭 선택(MapLibre + 경계 폴리곤).
- FR-G3. 선택 결과: 하원의원 1 + 상원의원 2 카드 + "최근 5년 후보" 탭.
- FR-G4. 경계는 의회번호(예: 119대)로 버전 관리, 재구획 반영.
- FR-G5. 지역구 없음 항목(상원)은 주 단위로 매핑.
- 수용기준: 임의 유효 미국 주소 입력 시 정확 지역구 + 대표 3인 반환.

### 4.4 랭킹 (FR-R) — §11 방법론 준수
- FR-R1. 출석률·표결참여율·대표발의수·발언수 순위표.
- FR-R2. 챔버별 분리(하원끼리/상원끼리)만.
- FR-R3. 정렬·필터(정당·주). 가치판단 카피 금지.
- FR-R4. 각 값 클릭 → 산출 근거(포함 롤콜 목록) + 방법론.
- 수용기준: 순위값이 원표결 재계산과 일치, 방법론 링크 상시.

### 4.5 발언 (FR-S) — MVP: 공식만
- FR-S1. Congressional Record(GovInfo) 본회의/Extensions 발언 수집.
- FR-S2. 발언자↔member 매핑(bioguide 기준).
- FR-S3. 전문검색(Postgres FTS): 키워드로 발언 검색.
- FR-S4. 커버리지 한계 명시: "본회의 발언만, 의회 밖 발언은 v2 뉴스에서".
- 수용기준: 최근 회기 발언이 의원 프로필과 검색에 노출.

### 4.6 과거 후보자 (FR-C) — 최근 5년
- FR-C1. FEC API로 최근 5년 하원·상원 후보 수집(Form 2 기반).
- FR-C2. 지역구/주별로 후보 목록 + 정당 + 자금 요약 + 결과.
- FR-C3. fec_candidate_id ↔ bioguide_id 매핑(현직 연결).
- FR-C4. 커버리지 한계 명시(FEC 미등록 군소후보 누락 가능).
- 수용기준: 지역구 선택 시 최근 5년 후보 리스트 표시.

### 4.7 (v2) 뉴스 계층 (FR-N) — §12 상세
- FR-N1. 의원·법안 관련 뉴스를 대시보드/프로필 내 카드 피드로 노출(링크아웃 전용 아님).
- FR-N2. 카드 = 헤드라인 + 매체명 + 게재일 + 짧은 발췌 + (허용 시)썸네일 + 원문 링크.
- FR-N3. 공식 보도자료(.gov)/성명은 더 풍부히 임베드 가능.
- FR-N4. "In the News" 탭으로 공식 기록과 시각적 분리, 평가·성향 라벨 없음.

---

## 5. 데이터 소스 (요약; 상세는 도시에 v0.1)

| 계층 | 소스 | 항목 | 라이선스 |
|---|---|---|---|
| 1차 | Congress.gov API | 법안·의원·위원회·액션·하원표결(**2017~**, 각주 1) | 퍼블릭 도메인 |
| 1차 | senate.gov XML | 상원 개별표결(1989~) | 퍼블릭 도메인 |
| 1차 | Clerk XML | 하원 개별표결(**1990~2016**) **백필** | 퍼블릭 도메인 |
| 1차 | GovInfo API | Congressional Record 발언 | 퍼블릭 도메인 |
| 1차 | FEC / openFEC | 후보·정치자금 | 퍼블릭 도메인 |
| 1차 | Census Geocoder + TIGER/CB | 주소→지역구, 경계 | 퍼블릭 도메인 |
| 2차 | Voteview(다운로드) | 표결 교차검증·백필(이념점수 미사용) | 학술 공개 |
| 2차 | unitedstates/congress | 스크레이퍼/스키마 참조 | 오픈소스 |
| v2 | GDELT 등 | 뉴스 언급 탐지 | §12 준수 |
| 백로그 | LDA.gov (lda.gov / lda.congress.gov) | 로비 등록·활동·기부 내역 | 퍼블릭 도메인급(§18) |

제외: GovTrack **API**(2026 여름 종료) — 데이터 의존 금지, 웹은 UX 참고만.
제외(표시용): OpenSecrets API/벌크데이터 — 비영리 전용 라이선스, §18 참조. 사내 교차검증 참고에만 한정 가능, 서비스 노출 불가.

> **실측 정정 (P1, 2026-08-16)** — 아래 세 항목은 본 문서 작성 시점의 기재값과 실제 서비스 응답이 달라
> 실측 기준으로 정정한다. 근거·재현 방법은 `docs/P1-source-verification.md`.
>
> 1. **하원 표결 커버리지: 2023~ → 2017~(115대).** 회기별 실측 건수 115대 1,210 / 116대 954 /
>    117대 998 / 118대 1,241 / 119대 645 = 5,048건으로, 전체 컬렉션이 보고하는 총계와 정확히 일치.
>    따라서 Clerk XML 백필 구간은 1990~2022가 아니라 **1990~2016**.
> 2. **senate.gov 접근성.** 스키마는 실물 확인 완료. 다만 Akamai WAF가 일부 네트워크(개발 로컬)에서
>    본 프로젝트 User-Agent에 403을 반환한다. **GitHub Actions 러너에서는 동일 UA로 정상 200**
>    (231건 롤콜 파싱, 상원의원 100명 전원 매핑, 미해결 0) — 차단은 UA가 아니라 네트워크 기준.
>    → 정기 상원 수집은 GitHub Actions에서 실행한다. UA 스푸핑 불필요.
> 3. **Congress.gov 레이트리밋: 문서상 5,000 req/h, 실측 응답 헤더 `X-Ratelimit-Limit: 20000`.**
>    코드는 두 숫자 중 어느 쪽도 하드코딩하지 않고 응답 헤더(`X-Ratelimit-Remaining`)를 읽어 동작한다.
>
> 또한 상원 표결은 Congress.gov API에 **엔드포인트가 존재하지 않는다**(`/senate-vote` 404 확인).
> senate.gov XML이 유일한 공식 경로라는 본문 서술은 실측으로 재확인됨.

---

## 6. 데이터 모델 (핵심 엔티티)

```
Member(bioguide_id PK, name, party, state, chamber, status, photo_url)
Term(member_id FK, congress_no, chamber, district?, start, end)
District(geoid PK, state, cd_number, congress_no, boundary_geojson, current_member_id)
Bill(congress_no, bill_type, number  [자연키], title, policy_area, status, sponsor_id)
BillAction(bill_id FK, date, text, action_type, source_system)
Sponsorship(bill_id FK, member_id FK, role[sponsor|cosponsor], date, withdrawn bool)
Vote(congress_no, chamber, session, roll_number [자연키], date, question, result,
     reconciled_at?, is_published)                                         # 각주 4
VoteCast(vote_id FK, member_id FK, position[Yea|Nay|Present|NotVoting])
Speech(member_id FK, date, chamber, title, text, granule_url)
CommitteeMembership(member_id FK, committee_id, role, congress_no)
Candidate(fec_candidate_id PK, name, office[H|S], state, district?, election_years[])
CampaignFinance(candidate_id FK, cycle, receipts, disbursements, cash_on_hand)
NewsMention(member_id? FK, bill_id? FK, headline, outlet, url, published_at, snippet)   # v2, 전문 저장 X
Provenance(entity, entity_id, field, source_url, retrieved_at, checksum)
```

원칙: 자연키 우선(멱등 upsert), 지역구 없음=null, District는 congress_no로 버전링.

> **각주 4 — `Vote.reconciled_at` / `Vote.is_published`는 서로 다른 질문에 답한다 (P2, 2026-08-18).**
> `reconciled_at`은 "독립 소스가 **마지막으로 동의한** 시각"이고, NULL은 **아직 대조 안 됨**이지
> 분쟁 중이 아니다. `is_published`는 "**반증된 적 없음**"이며, open flag가 있는 동안에만 false다.
> 둘을 하나로 합치면 §9 각주 3의 세 상태 중 하나가 표현 불가능해진다.
> 웹 쿼리는 `vote`를 무필터로 읽지 않는다(`apps/web/src/db/queries.ts`의 `publishedVote`).

---

## 7. 시스템 아키텍처

```
[공식 API/XML] → [Python ETL (수집·정규화·멱등 upsert·스케줄)] → [PostgreSQL + PostGIS]
      │                        │                                          │
 [Clerk/senate XML 백필]  [정합성 대조 vs Voteview → 불일치 플래그 큐]   [Next.js/TS SSR]
                                                                          │
                                                          [MapLibre 지도 · Postgres FTS 검색]
[GDELT/뉴스(v2)] → [언급 인덱싱: 링크·발췌만] ─────────────────────────────┘
```

- 기술스택: **Next.js(TS) / Python ETL / PostgreSQL+PostGIS / MapLibre / Postgres FTS(→ 필요시 Typesense)**. 최소 의존성.
- 라이브 프록시 금지: 스케줄 수집→자체 DB.
- 스케줄: 표결·액션=일, 의원명부=주, 경계=회기, (v2)뉴스=시간.

---

## 8. 비기능 요구사항 (NFR)

- NFR-1 성능: 주요 페이지 P95 < 2s(SSR + 캐시).
- NFR-2 신선도: 표결/법안 24h 내 반영, 발언 수일 내.
- NFR-3 신뢰성: 소스 API 장애 시 마지막 성공 스냅샷 서빙(다운타임 격리).
- NFR-4 정합성: 표결 집계 다중소스 대조, 불일치 시 미노출·플래그.
- NFR-5 소급성: 모든 사실 필드에 source_url + retrieved_at.
- NFR-6 라이선스 준수: 퍼블릭 도메인 우선, 뉴스는 §12.
- NFR-7 접근성: WCAG AA 지향(지도 대체 UI 포함).
- NFR-8 확장성: 국가별 파이프라인 분리 + 통합 프레젠테이션(UK 대비).
- NFR-9 관측성: 수집 잡 로그·감사 로그·데이터 커버리지 대시(내부).

---

## 9. 팩트체크 / 데이터 무결성 요구사항

- FC-1. 공식 1차 소스가 항상 기준선. 뉴스는 사실 생성 금지(가리키기만).
- FC-2. 표결 집계 reconciliation: (Congress.gov/senate.gov/Clerk) ↔ Voteview 자동 대조.
- FC-3. 불일치 발생 시: 사용자엔 미확정값 미노출 + 내부 검토 큐 적재. **(각주 3)**
- FC-4. 해석/추론 라벨 금지(성향·의도·"반대 취지" 등).
- FC-5. 상세페이지 "원자료 보기" 링크 필수(POLIWIKI 방식).

> **각주 3 — FC-3 확정 해석 (P2, 2026-08-18): "반증되면 내린다"이지 "확인될 때까지 안 올린다"가 아니다.**
>
> 문제는 이 한 줄이 두 가지로 읽힌다는 것이었다. FC-3 본문은 **불일치가 났을 때** 미노출하라는
> 뜻이고, 도시에 §2.2의 "사용자에겐 확정값만 노출"은 **확인되기 전까지** 미노출하라는 뜻이다.
> 두 문장은 같은 정책이 아니다. P1은 대조 기능이 없던 상태에서 후자를 구현해
> `vote.is_published`를 전부 false로 썼고, P5(thin)가 만든 화면은 그 컬럼을 아예 보지 않고
> 전부 노출하면서 "Not yet cross-checked against Voteview" 캐치프레이즈만 달았다.
> 즉 **DB는 "아무것도 공개하지 마"라고 적혀 있었고, 사이트는 전부 공개하고 있었다.**
> P2에서 실제로 대조가 가능해졌으므로 여기서 확정한다.
>
> **확정: 반증되지 않는 한 공개한다.** 근거는 P2 실측(`docs/P2-source-verification.md` Finding 12):
>
> 1. **Voteview는 늦다.** 실측일(2026-08-17) 기준 최신 하원 롤콜이 2026-07-23 — 의회보다 3주 반
>    뒤처져 있다. Voteview 승인을 노출 전제조건으로 두면 사이트 전체가 공식 기록보다 3주 늦어지고,
>    NFR-2(표결 24h 내 반영)가 구조적으로 깨진다.
> 2. **Voteview는 전부를 덮지 않는다.** 정족수 호명(QUORUM)은 표결이 아니라서 애초에 수록하지 않는다.
>    "확인될 때까지 미노출"이면 Clerk가 공식 발표했고 아무도 이의를 제기하지 않은 롤콜이 **영구히**
>    안 보이게 된다.
> 3. **소스 위계가 뒤집힌다.** FC-1은 정부 기록을 기준선으로, Voteview를 "동의하거나 반대하는 쪽"으로
>    규정한다. **반대만 할 수 있는 소스가 침묵으로 거부권까지 쥐면 안 된다.** 3자가 아직 재출판하지
>    않았다는 이유로 정확히 기록된 공식 사실을 감추는 것은 그 자체로 기록의 왜곡이며,
>    이는 migration 0003이 `raw_position`을 도입하며 세운 논리와 같다.
>
> FC-3이 막으려는 위험은 **틀린 숫자를 보여주는 것**이다. Voteview의 침묵은 틀렸다는 증거가 아니고,
> 반증은 증거다. 따라서 상태는 셋이다 (§6 각주 4, migration 0004):
>
> | 상태 | DB | 사용자 화면 |
> |---|---|---|
> | 미대조 | `reconciled_at IS NULL`, `is_published` | 노출 + "Not yet cross-checked" 캐치프레이즈 |
> | 대조 일치 | `reconciled_at` 기록, `is_published` | 노출, 캐치프레이즈 없음 |
> | **불일치** | `NOT is_published` + open flag | **미노출** + 검토 큐 적재 |
>
> 세 번째 줄이 FC-3의 문자 그대로의 요구이고, P2가 그것이 실제로 발생할 수 있는 첫 릴리스다.
> 감춘 건수는 대시보드에 숫자로 고지한다 — 조용한 공백은 수집 실패와 구별되지 않기 때문이다.
>
> 대조 대상 필드는 `yea_count`/`nay_count` 두 개뿐이다. Voteview에는 present/not-voting의 공식
> 컬럼이 없고, cast code로 유도한 값은 하원이 "Not Voting"으로 기록하는 pair/announced 표시와
> 투표하지 않은 의원까지 포함해 체계적으로 어긋난다(P2 Finding 10). 그 값을 대조했다면 관행 차이가
> 대량의 "불일치"로 둔갑해 사이트 대부분을 감췄을 것이다.

---

## 10. 정보구조 (IA) / 페이지 맵

```
/                     대시보드(최근 법안·표결·발언, (v2)뉴스)          [구현]
/members              의원 검색·목록                                   [스텁]
/members/:bioguide    의원 프로필                                      [구현]
/bills                법안 목록·검색                                   [구현 P5]
/bills/:congress/:type/:number   법안 상세                             [구현 P5]
/votes                표결 목록                                        [구현 P5]
/votes/:id            표결 상세(의원별 포지션)                          [구현 P5]
/districts            지도(내 지역구 찾기)                              [스텁 — 경계 데이터 미수집]
/districts/:geoid     지역구 상세(대표 3인 + 최근 5년 후보)              [스텁 — 경계 데이터 미수집]
/rankings             출석률·표결참여율 등                              [구현 P5]
/speeches             발언 검색                                        [구현]
/methodology          지표 산출·데이터 출처·커버리지 한계               [스텁 — 각주 5]
```

> **각주 5 — `/methodology`가 아직 스텁인 이유 (P5, 2026-08-20).**
> §11이 요구하는 "방법론 각주 상시"는 `/rankings` **페이지 안에** 전문으로 넣었다.
> 별도 페이지로 링크만 걸면 §11 각주를 클릭해야 볼 수 있게 되는데, 랭킹은 각주를
> 읽지 않은 독자가 가장 오해하기 쉬운 화면이다. `/methodology`는 랭킹 방법론뿐 아니라
> 수집 범위·소스 목록·PIT 정책을 모두 담는 문서 페이지이므로 별도 작업으로 남긴다.
> **그때까지 신규 페이지는 "Coming soon" 스텁으로 링크하지 않는다** — 방법론을
> 약속하는 링크가 빈 페이지로 가는 것이 링크가 없는 것보다 나쁘기 때문이다.
> (`/members/:bioguide`의 기존 링크는 P5 이전부터 있던 것으로 그대로 둔다.)

---

## 11. 랭킹 방법론 스펙 (중립 가드레일)

계산(전부 원표결 파생):
- 표결참여율 = (Yea + Nay + Present + **기타 기록된 포지션**) / 기간 전체 롤콜 (member별) — 각주 1
- 결석표결 = NotVoting 카운트
- 대표발의/공동발의 = Sponsorship 집계
- 발언수 = Speech 집계

규칙:
- 동일 조건 비교(하원끼리/상원끼리), 중도합류·사망·의장(관례상 미투표) 보정.
- 가치판단 카피 금지("출석왕" X → "출석률 높은 순" O).
- 낮은 참여율 ≠ 불성실(질병·공무 등) — 방법론 각주 상시.
- 각 값에 산출 근거 롤콜 링크.

> **각주 1 — 4개 표준 포지션에 안 맞는 표결의 처리 (P1.5, 2026-08-16 결정)**
>
> **사실:** 모든 롤콜이 찬반 표결은 아니다. **의장 선출(Election of the Speaker)** 에서
> 의원은 Yea/Nay가 아니라 **후보 이름**을 부른다. 119대 1회기 roll 2 실측:
> `Johnson (LA) 218 · Jeffries 215 · Emmer 1`. 434명 전원이 실제로 투표했다.
>
> **분자에 포함한다.** 이유:
> 1. **사실 문제.** 후보명을 부른 의원은 출석해서 표를 행사했다. 이를 분모에만 넣고
>    분자에서 빼면 그 롤콜에 **참여한** 434명이 전원 불참한 것처럼 계산된다. 참여율이
>    측정하려는 것은 "표를 행사했는가"이지 "찬성했는가"가 아니다.
> 2. **중립 문제(FC-4).** 분자에서 제외하려면 "어떤 롤콜이 참여율에 카운트되는가"를
>    우리가 선별해야 한다. 의장 선출은 절차적/원구성 표결이라 뺀다는 판단은 편집적 개입이며,
>    §11이 명시한 "기간 전체 롤콜" 정의와도 충돌한다. 분모·분자 모두에 넣는 쪽이
>    판단을 덜 개입시킨다.
> 3. **NotVoting과 구분된다.** 이 케이스는 `position IS NULL AND raw_position IS NOT NULL`로
>    저장되며(마이그레이션 0003), `NotVoting`과 스키마 수준에서 별개다. 결석표결 카운트에는
>    포함되지 않는다.
>
> **표시 규칙.** 랭킹·프로필 UI는 포지션을 **Yea / Nay / Present / 기타(원본 표기)** 로
> 구분해 보여준다. "기타"는 `raw_position` 원문(예: `Johnson (LA)`)을 그대로 노출하고,
> 후보명을 찬반으로 환산하지 않는다. 참여율 수치 옆에는 해당 기간에 기타 포지션이 포함된
> 롤콜이 있으면 그 사실을 각주로 명시한다.
>
> **대안과 기각 사유.** (a) 후보명을 `vote_position` ENUM에 추가 — 후보명은 선거마다 달라
> 무한하고, 프로젝트가 고정된 "정치적 포지션 어휘"를 갖는다는 잘못된 함의를 준다.
> (b) 해당 롤콜을 통째로 폐기 — P1에서 실제로 이렇게 동작했고, 실재하는 고관심 표결을
> 통째로 잃었다. 0001의 스키마 주석("positions are recorded verbatim")과도 모순된다.

---

## 12. 뉴스 계층 스펙 (v2) — 대시보드 내 소비 + 저작권 안전

목표: 링크아웃만이 아니라 대시보드/프로필에서 **바로 훑을 수 있게**. 단, 기사 전문 저장·재현 금지.

3단 신뢰 구조:
1. 공식 발언(1차) — Congressional Record(이미 MVP).
2. 공식 성명/보도자료(준1차) — .gov 도메인/의원 공식 채널·C-SPAN. 퍼블릭 도메인/공개자료는 **풍부히 임베드 가능**.
3. 언론 보도(보조) — **카드형**: 헤드라인 + 매체명 + 게재일 + 1~2문장 발췌 + (허용 시)썸네일 + 원문 링크. **전문 미저장**.

수집·표시 규칙:
- 소스: GDELT(무료, 언급 탐지) 우선. 표시용 확장은 트래픽 후 재검토(NewsData.io 등).
- 발췌는 짧게(fair use 범위), 매체·링크 필수.
- "In the News" 탭으로 공식 기록과 분리, 평가/성향 라벨 없음.
- NewsMention은 링크·메타·발췌만 저장(전문 X).

---

## 13. 성공지표 (Metrics)

- M1. 커버리지: 현직 535명 100% 프로필 + 표결·발의·발언 연결률.
- M2. 데이터 정합성: reconciliation 불일치율 < 목표치, 미해결 플래그 0 지향.
- M3. 신선도: 표결 반영 지연 중앙값 < 24h.
- M4. 지역구 조회 정확도: 유효 주소 → 정확 지역구 매칭률.
- M5. 사용성: 지역구 찾기 완료율, 프로필 도달률(정성).

---

## 14. 로드맵 / 마일스톤

- **P0 셋업:** 레포·CI·DB 스키마·Congress.gov/FEC 키·기본 ETL 골격.
- **P1 코어 데이터:** 의원·법안·액션·표결(하원 2017~ + 상원) 수집·정규화.
- **P2 백필:** Clerk XML(1990~2016) + Voteview 대조 파이프라인.
- **P3 발언:** GovInfo Congressional Record 수집 + FTS.
- **P4 지도/지역구:** Census Geocoder + 경계 + MapLibre + 후보(FEC 5년).
- **P5 프런트:** 대시보드·프로필·검색·랭킹.
  - 2026-08-20: `/bills`, `/bills/:congress/:type/:number`, `/votes`, `/votes/:id`,
    `/rankings` 구현 — 신규 ETL 없이 P1~P3 적재분 위의 쿼리·화면 작업. §10 IA 표 참조.
    남은 스텁은 `/members`(목록), `/methodology`(§10 각주 5), `/districts` 2종(P4 의존).
- **P6 하드닝:** 정합성·신선도·관측성·접근성.
- **(v2)** 뉴스 계층 · 알림 · 고급검색.
- **(v3)** 비교뷰 · UK 온보딩 · 공개 데이터.

---

## 15. 리스크 & 완화

| 리스크 | 완화 |
|---|---|
| 하원 표결 API 베타 + 2017~ 한정(실측; 당초 2023~로 가정) | Clerk XML 백필 이중경로(P2), 구간 1990~2016 |
| 재구획 경계·매핑 복잡 | District에 congress_no 버전링 |
| FEC 후보 누락(군소) | 커버리지 한계 명시 |
| fec_id ↔ bioguide 매핑 난이도 | 매핑 테이블 + 수기 보정 큐 |
| 뉴스 저작권·중립(v2) | 카드형·발췌·링크, 전문 미저장(§12) |
| 소스 API 스펙 변경 | 착수 전 OpenAPI 재확인, 어댑터 계층 격리 |

---

## 16. 착수 전 검증 체크리스트 (CLI 작업 직전)

- [x] Congress.gov API 키 발급 + House Votes 베타 엔드포인트 응답 확인 — **2017~(115대)** 확인(2026-08-16)
- [x] senate.gov XML 최신 회기 스키마 확인 — 119대 2세션 실물 확인. 단 senate.gov는 WAF로 일부 네트워크에서 403; GitHub Actions 러너에서는 정상(각주 2)
- [x] Clerk XML(하원, **~2016**) 접근·스키마 확인 — 1990~2016 전 연도 실측(2026-08-17). **백필 실행 완료(2026-08-19): 17,433개 롤콜 전량 적재**(인덱스 실측치와 정확히 일치), `vote_cast` 7,849,148행, DB 1.31 GiB(예측 1.5~2GB), 실패·재시도 0. 1989는 404이므로 하한이 1990으로 확정. **2003년에 `<legislator name-id>`(bioguide)가 생기는 스키마 단절**이 있어 1990~2002는 Congress.gov 로스터로 이름 해석(실측 해석률 99.65%). 상세: `docs/P2-source-verification.md`
- [x] GovInfo API 키 + Congressional Record granule 파싱 확인 — 실측(2026-08-19). 패키지(일자별 CR) → 그래뉼(개별 발언) 구조 확인, `granuleClass`가 House/Senate/Extensions of Remarks/Daily Digest를 구분한다. **P0 스텁의 가정이 틀렸다: CREC의 `<congMember>`는 1994년 시작 시점까지 전부 `bioGuideId`를 갖고 있다**(1995·2005·2015·2026 확인, 이름만 있는 항목 0건) → 이름 매칭 경로 자체가 불필요. **그래뉼의 7.2%는 화자가 둘 이상**(콜로퀴)이라 `speech.bioguide_id` 한 칼럼으로는 담을 수 없어 마이그레이션 0005로 `speech_speaker`를 추가. 화자 미상 47%는 매칭 실패가 아니라 기도·선서·의사일지·Constitutional Authority Statement 등 **누구의 발언도 아닌 기록**이며 NULL로 저장한다. 레이트리밋 실측 36,000 req/h(문서상 api.data.gov 1,000). 볼륨 실측: 119대 = **351개 패키지 / 26,985면 / 52,265 그래뉼 / 텍스트 약 329MB / 수집 약 3.5시간**. CREC 시작은 1990년대가 아니라 **1994년**이고 그 이전은 CRECB(권·부 단위, 구조가 다름). 상세: `docs/P3-source-verification.md`
- [ ] FEC API 키 + 후보 5년 필터 확인
- [ ] Census Geocoder 주소→지역구 응답 확인 + 119대 경계 파일 확보
- [x] **P5 랭킹 수용기준 — "순위값이 원표결 재계산과 일치" 실측 확인(2026-08-20).** 라이브 DB(Neon)에 빌드본을 붙여 렌더한 값을, 앱 쿼리와 **다른 방식으로 작성한 SQL**(CTE 체인 대신 상관 서브쿼리)로 독립 재계산해 대조 — 7명 전원 일치. 근거: `B001314` 645/645 = 100.0%, `G000551`(임기 중 사망) **2/71 = 2.8%** — 분모가 645가 아니라 재임 기간 롤콜로 보정됨, `P000610` 42/645, `R000600` 15/645, `J000294` 643/645. 119대 하원 raw_position 434건 = 의장 선출 1건(roll 2: `Johnson (LA)` 218 · `Jeffries` 215 · `Emmer` 1 — §11 각주 1 실측치와 정확히 일치). FR-R4 근거 화면도 확인: `?basis=G000551`이 분모 71개 롤콜을 전건 나열하고 각 건이 `/votes/:id`로 연결된다.
  - **실측으로 드러난 데이터 공백 2건(둘 다 P5 스코프 밖 — ETL 수정 필요).**
    1. **`vote.bill_id`가 18,544건 전부 NULL.** 그래서 법안 상세의 "Roll-call votes" 섹션은 **모든 법안에서** 비어 있다. 화면은 이 사실을 그대로 말하도록 했고(연결 건수 0이면 문구가 바뀌는 조건부 empty state), 링크가 채워지면 문구도 자동으로 바뀐다.
       **정정(2026-08-20, 원인 확정 후):** P5 최초 보고에서 이를 "표결 수집 경로가 법안을 해석하지 않는다"고 적었으나 **틀렸다.** 세 수집 경로 모두 `find_bill_id`로 정상 해석하며, 하원은 Congress.gov가 `legislationType`/`legislationNumber`를 표본 14/14 전건 반환한다. **실제 갭은 `bill` 수집 커버리지다** — `bills` job이 `--limit`으로 실행돼 `bill` 테이블에 119대 **150행(전체 18,396건의 0.8%)** 만 있고, 그나마 `sort=updateDate desc` 표본이라 롤콜이 붙은 법안과 겹치지 않는다(상원이 지목한 75개 법안 중 보유 **0**개). 따라서 votes job 재실행으로는 복구되지 않으며, 필요한 것은 119대 법안 **전체 수집**이다. 상세: `docs/vote-bill_id-null-investigation.md` §검증 결과.
    2. **`retrieved_at`이 `speech`를 제외한 전 테이블에서 NULL** (bill 0/150, vote 0/18,544, member 0/1,694, term 0/11,412). 수집 시각은 `provenance` 테이블(72,544행)에 **자연키**로 들어 있다 — bill은 `119/s/93`, vote는 `<congress>/<session>/<roll>`. NFR-5를 실제로 충족시키려고 상세 페이지는 여기서 시각을 읽는다. vote는 `entity_id`에 챔버가 없어 하원·상원이 충돌하므로(`119/2/1`이 양쪽 모두) `source_url` 완전일치로 구분 — 공개 표결 18,297건 전건 해석 확인.
- [x] Voteview 다운로드 필드(Members' Votes) 매핑 확인 — 실측(2026-08-18), **전 구간 대조 완료(2026-08-19): 18,348건 중 17,909 일치 / 247 불일치(1.36%) / 177 상대 없음 / 15 비교 불가**. **주의: Voteview의 `rollnumber`는 우리 roll_number가 아니다**(회기 통산 번호이고 정족수 호명을 건너뜀). 매칭 키는 `clerk_rollnumber` + `session`. 집계 대조는 `yea_count`/`nay_count` 컬럼만 — cast code에서 유도한 값은 관행 차이로 체계적으로 어긋난다(§9 각주 3). 상세: `docs/P2-source-verification.md`

---

## 17. 열린 결정 (미확정)

- OQ-1. 제품명·도메인.
- ~~OQ-2. 하원 백필 시작연도: 1990(Clerk 최댓값) vs 최근 N대 의회로 한정.~~ → **1990으로 확정(P2, 2026-08-18).** Clerk의 실제 최댓값이 1990이다(1989는 404). 상한은 2016 — 2017부터는 Congress.gov 베타가 덮으므로 두 소스가 겹치지 않는다. **2026-08-19 실행 완료** — 1990~2016 27개 연도 전량 적재(누락 연도 없음), 17,433건. 범위를 좁힐 이유였던 용량·시간 우려는 실측으로 해소됐다(1.31 GiB, 수집 약 5시간).
- **OQ-8. 발언 과거분 백필(1994~2024) 여부.** P3는 119대만 수집하기로 결정했다(근거: `docs/P3-source-verification.md`). 남은 판단은 **용량·시간 문제이지 타당성 문제가 아니다** — 1995·2005·2015 패키지를 확인한 결과 그래뉼 구조와 `bioGuideId` 커버리지가 2026년과 동일하므로, 파서는 그대로 쓰면 된다. `civiclens-etl backfill-speeches --congress N`이 이미 1994년까지 받는다. 규모 추정: CREC 연평균 약 170개 패키지 × 1994~2026 ≈ **5,500개 패키지 / 80만 그래뉼 / 텍스트 약 5GB**(119대의 약 15배). 1994년 이전은 CRECB(권·부 단위 패키징)라 별도 검증이 필요하다.
- OQ-3. 뉴스 표시용 소스(v2): GDELT만 vs 유료 표시 API 병행 시점.
- OQ-4. 배포 환경(Vercel + 관리형 Postgres vs 자체 호스팅) — CLI 착수 시 결정.
- OQ-5. 데이터 갱신 오케스트레이션(cron vs Prefect/Airflow).
- OQ-6. 로비 데이터(§18) 착수 시점(v2 vs v3)과 "회전문(revolving door)" 매칭 포함 여부.
- OQ-7. 수익화(§19) 대상 범위 — 어떤 기능을 유료화할지(광고 제거/알림/API 접근 등), 착수 시점, Vercel Pro 전환 타이밍.

---

## 18. 백로그 — 로비 데이터 (Lobbying Disclosure)

**제안 배경:** 정치인별로 "누구에게 얼마나 로비를 받았는지"를 보여달라는 요청(2026-08-17). 착수 전
라이선스·소스 분석을 먼저 확정해둔다 — 실제 구현 시점(v2 이후로 추정, OQ-6)에 이 절을 그대로 스펙으로 쓴다.

### 18.1 핵심 결론

**OpenSecrets API/벌크데이터는 서비스에 못 쓴다.** 라이선스가 CC BY-NC-SA(비영리)이고, API 약관이
"교육·연구·비영리 목적"으로 명시 제한하며 재배포·상업적 이용에 서면 허가(유료)를 요구한다. 이 프로젝트가
장기적으로 결제·광고 수익화를 목표로 한다고 이미 밝힌 이상(2026-08-17 논의), OpenSecrets 데이터를 화면에
노출하는 건 라이선스 위반이다. 게다가 OpenSecrets은 정부 1차 소스가 아니라 "산업군 분류"라는 자체 편집
판단이 들어간 3자 가공 데이터라, PRD FC-1/FC-4(공식 1차 소스 기준, 해석·가공 라벨 금지) 원칙과도 결이
다르다. → **사내 리서치·수치 대조용으로만 잠깐 참고 가능, 화면에 표시하거나 재배포 불가.**

**대신 LDA(Lobbying Disclosure Act) 원자료를 직접 수집·가공한다.** 공식 소스이고, 약관
(lda.senate.gov/api/tos, 2019-08-22 최종 수정)에 "Data accessed through LDA.gov do not, and should not,
include controls over its end use" — **최종 용도(상업적 이용 포함)에 제한이 없다고 명시**돼 있다. 요구되는
건 (a) 조회일자 인용, (b) "Senate Office of Public Records cannot vouch for the data or analyses derived
from these data after the data have been retrieved from LDA.gov" 문구 고지, (c) 원문 왜곡·수정 금지,
(d) 미 상원 문장(Seal) 사용 금지 — 전부 지금 다른 소스(Congress.gov 등)에도 이미 적용 중인 provenance/
methodology 관행과 그대로 겹친다. 무료, API 키 불필요(익명 15req/분, 등록 시 120req/분).

**전환 주의:** 구 시스템 `lda.senate.gov`는 2026-06-30 종료 공지(별도 조회 결과는 07-31로도 나옴 — 착수
시점에 재확인). 새 `lda.gov` / `lda.congress.gov`로 이미 이전된 상태에서 시작해야 한다 — 다른 소스들과
마찬가지로 착수 전 실제 엔드포인트를 먼저 찔러 확인하는 절차(§16 방식)를 그대로 적용한다.

### 18.2 데이터 종류 — "로비를 얼마나 받았는지"는 두 갈래로 나뉜다

| 보고서 | 내용 | 개별 의원 단위인가 |
|---|---|---|
| LD-1 (등록) | 어떤 로비회사가 어떤 고객을 대리하는지 | 아니오 |
| LD-2 (분기 활동보고서) | 고객·등록로비스트·이슈·**상대 기관**(하원/상원/특정 부처)·지출액 | **아니오** — 챔버/기관 단위지 특정 의원실 단위가 아님 |
| **LD-203 (반기 정치기부 보고서)** | 등록로비스트가 연방 후보·현직자·리더십PAC·정당위원회에 한 기부($200 초과분 의무 공시) | **예** — 이게 사용자가 원하는 "의원 Y가 로비스트 X에게 얼마 받았다"에 해당 |

→ "로비 받은 금액"을 의원 단위로 보여주려면 **LD-203이 핵심**이고, LD-2는 "이 이슈에 어떤 로비회사들이
얼마나 썼는지"라는 별도 화면(법안/이슈 상세에 붙이면 자연스러움)이 된다. 이 둘을 하나의 숫자로 섞으면
안 된다 — 서로 다른 걸 측정한다.

### 18.3 OpenSecrets 수준에 도달하려면 추가로 필요한 것

OpenSecrets의 로비 관련 강점은 (a) LD-2+LD-203+FEC를 합쳐 의원별/산업별 요약 숫자를 만들어주는 것,
(b) 로비스트 신원의 표기 변형(동일인이 여러 철자로 등장)을 정규화하는 것, (c) "회전문"(전직 의원·보좌진이
로비스트로 전직한 이력) 추적이다. 우리가 원자료 기반으로 이 수준에 가려면:

1. LD-203 기부자(로비스트)를 FEC 수령측 기록과 대조 — 같은 기부가 양쪽에 잡히므로 서로 검증 가능
   (Voteview 대조와 같은 패턴을 그대로 재사용 가능).
2. 로비스트 신원 정규화 — LDA가 부여하는 등록 ID를 1차 키로 쓰고, 이름 매칭은 보조로만.
3. bioguide_id ↔ LD-203 수령자 매칭 — Candidate/Member 매핑과 같은 방식(§6 fec_candidate_id 매핑 큐
   재사용 가능).
4. "회전문" 추적은 난이도가 다른 항목들과 다르다(전직 이력 데이터가 흩어져 있고 자동 매칭 신뢰도가 낮음)
   — **1차 스코프에서 제외**하고, 넣더라도 수기 검토 큐를 거치게 한다(OQ-6에서 결정).

### 18.4 제안 데이터 모델 확장 (§6에 추가할 후보, 확정 아님)

```
LobbyingRegistration(lda_registration_id PK, registrant_name, client_name, filing_year, source_url, retrieved_at)
LobbyingActivity(registration_id FK, period, issue_area_code, government_entities[], amount_reported?, source_url, retrieved_at)
LobbyingContribution(lda_filing_id PK, lobbyist_name, contributor_type, recipient_name, bioguide_id? FK,
                      amount, contribution_date, filing_period, source_url, retrieved_at)
```

`bioguide_id`는 자동 매칭 신뢰도가 낮을 수 있어 nullable + 매칭 방법/신뢰도 컬럼(§6 Candidate의
`bioguide_match_method` 패턴 재사용)을 둔다.

### 18.5 배치 제안

뉴스 계층(§12)과 유사하게 "3차 보조 계층"으로 v2 이후 배치. 표시 원칙은 §9 FC-1~5, §11 중립 가드레일을
그대로 적용 — "이 의원은 로비의 영향을 받았다" 류의 해석 문구 금지, 금액·날짜·출처만 제시.

---

## 19. 백로그 — 구독/수익화 아키텍처

**제안 배경:** 결제·광고로 수익화한다는 목표는 이미 밝혀져 있다(2026-08-17 논의, §1 비전과 별개로
운영 목표). 2026-08-19 비용 검토(Neon/Vercel) 직후, "지금 백엔드 구조가 구독 모델에도 최선인가"를
검토한 결과를 남긴다. 실제 착수 시점은 OQ-7에서 정한다.

### 19.1 핵심 결론

**현재 백엔드(Neon Postgres + Vercel + GitHub Actions ETL)는 안 바꿔도 된다.** 구독 모델이 요구하는
건 기존 구조 위에 새 컴포넌트를 얹는 것이지 재설계가 아니다. 이 결론의 근거:

- 이 규모(구독자 수백~수천 명)에서 사용자/결제 데이터를 공공데이터와 **같은 Postgres**에 두는 것이
  운영 복잡도를 줄인다. 별도 DB로 쪼갤 이유가 없다.
- 지금 페이지가 캐싱 없이(`force-dynamic`) 매 요청마다 DB를 직접 조회하는 설계(§ NFR-1 대응으로
  도입)는, 로그인 상태에 따라 다른 화면을 보여줘야 하는 개인화 콘텐츠와 오히려 잘 맞는다. 원래
  비용 리스크로 지적됐던 특성이 구독 기능에선 이점이 된다.

### 19.2 새로 필요한 컴포넌트

1. **인증(Auth).** PRD N4가 MVP에서 제외한 항목이므로 이제 되살려야 한다. **Neon Auth**(Neon 프로젝트
   생성 시 존재하는 옵션 — MVP 착수 때는 꺼 두었다)가 유력 후보: 이미 Neon을 쓰고 있어 인증 전용
   서드파티 서비스를 추가 의존성으로 늘리지 않는다. Auth.js/Clerk도 대안이나 "최소 의존성" 원칙상
   Neon Auth를 먼저 검토.
2. **결제(Payments).** Stripe. 구독 라이프사이클(체험판/활성/해지/연체)·웹훅·Customer Portal이 내장돼
   있어 직접 구현할 범위가 작다. **카드 정보는 우리 서버가 직접 다루지 않는다** — Stripe Checkout/
   Elements 같은 호스팅 결제 UI만 사용해 PCI 규제 범위를 최소화한다(신규 NFR 후보).
3. **DB 역할 분리.** 지금 웹앱은 ETL과 동일한 `neondb_owner`로 접속한다. 구독 도입 시 웹앱이
   사용자/결제 테이블에 쓰기 권한도 필요해지므로, "ETL 전용 role(공공데이터 쓰기)"과 "웹앱 role
   (공공데이터 읽기 + 사용자/결제 데이터 읽기·쓰기)"을 분리한다. 원래도 권장되던 하드닝 항목(P6)이며,
   구독 도입이 이걸 더 미루기 어렵게 만든다.
4. **레이트리밋(유료 API 접근을 유료화할 경우에만).** 지금 스택엔 없다. Vercel Edge Config나 Upstash
   Redis 같은 가벼운 컴포넌트가 필요하나, 실제로 API 접근을 유료 기능으로 넣을지(OQ-7)에 달려있어
   지금 결정하지 않는다.

### 19.3 유료화 대상과 PRD 원칙의 관계

이 프로젝트의 핵심 가치(원자료는 누구나 무료 열람, poliwiki 벤치마크)와 충돌하지 않는 유료화만
검토한다:

| 유료화 후보 | PRD 원칙 충돌 | 비고 |
|---|---|---|
| 광고 제거 | 없음 | Auth+결제만 필요 |
| 관심 의원/법안 알림 | 없음 (§12 뉴스 계층 로드맵의 "알림" 항목과 동일 계열) | Auth+결제+이메일 발송(예: Resend) |
| 대량 데이터 다운로드/API 접근 | 없음 — 화면상 원자료 열람 자체는 여전히 무료 | Auth+결제+레이트리밋 |
| **원자료 열람 자체의 유료화** | **핵심 원칙과 정면 충돌 — 채택 안 함** | — |

### 19.4 제안 데이터 모델 확장 (§6에 추가할 후보, 확정 아님)

```
User(id PK, email, created_at, ...)                       # Neon Auth가 관리하는 스키마를 따를 가능성 높음
Subscription(id PK, user_id FK, stripe_customer_id, stripe_subscription_id,
              plan, status[trialing|active|past_due|canceled], current_period_end)
```

자연키 우선 원칙 유지 — `stripe_customer_id`/`stripe_subscription_id`를 그대로 자연키로 쓴다
(fec_candidate_id, bioguide_id 등 기존 패턴과 동일).

### 19.5 열려 있는 질문

OQ-7(§17) — 유료화 대상 범위, 착수 시점, Vercel Pro($20/월) 전환 시점. Vercel Hobby는 약관상
비영리 전용이라, 실제로 결제 기능을 붙이는 시점엔 Pro 전환이 사실상 필수(2026-08-19 비용 검토 참고).

---

## 부록 A. 소스 → 필드 매핑 (요약)

- 의원: Congress.gov `/member` → Member/Term
- 법안: Congress.gov `/bill/{congress}/{type}/{number}` (+ actions, summaries, cosponsors) → Bill/BillAction/Sponsorship
- 하원표결(2017~): Congress.gov House Votes 베타 → Vote/VoteCast
- 하원표결(~2016): Clerk XML → Vote/VoteCast
- 상원표결: senate.gov XML → Vote/VoteCast
- 발언: GovInfo Congressional Record granule → Speech
- 후보/자금: FEC `/candidates`, `/candidate/{id}/totals` → Candidate/CampaignFinance
- 지역구: Census Geocoder(주소→CD) + TIGER/CB(경계) → District
- 교차검증: Voteview Members' Votes CSV → reconciliation

## 부록 B. 용어
- bioguide_id: 의회 의원 고유 식별자.
- 롤콜(roll-call): 기명 표결. 음성표결(voice)은 개인 포지션 없음.
- CD: Congressional District(하원 지역구).
