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

제외: GovTrack **API**(2026 여름 종료) — 데이터 의존 금지, 웹은 UX 참고만.

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
Vote(congress_no, chamber, session, roll_number [자연키], date, question, result)
VoteCast(vote_id FK, member_id FK, position[Yea|Nay|Present|NotVoting])
Speech(member_id FK, date, chamber, title, text, granule_url)
CommitteeMembership(member_id FK, committee_id, role, congress_no)
Candidate(fec_candidate_id PK, name, office[H|S], state, district?, election_years[])
CampaignFinance(candidate_id FK, cycle, receipts, disbursements, cash_on_hand)
NewsMention(member_id? FK, bill_id? FK, headline, outlet, url, published_at, snippet)   # v2, 전문 저장 X
Provenance(entity, entity_id, field, source_url, retrieved_at, checksum)
```

원칙: 자연키 우선(멱등 upsert), 지역구 없음=null, District는 congress_no로 버전링.

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
- FC-3. 불일치 발생 시: 사용자엔 미확정값 미노출 + 내부 검토 큐 적재.
- FC-4. 해석/추론 라벨 금지(성향·의도·"반대 취지" 등).
- FC-5. 상세페이지 "원자료 보기" 링크 필수(POLIWIKI 방식).

---

## 10. 정보구조 (IA) / 페이지 맵

```
/                     대시보드(최근 법안·표결·발언, (v2)뉴스)
/members              의원 검색·목록
/members/:bioguide    의원 프로필
/bills                법안 목록·검색
/bills/:congress/:type/:number   법안 상세
/votes                표결 목록
/votes/:id            표결 상세(의원별 포지션)
/districts            지도(내 지역구 찾기)
/districts/:geoid     지역구 상세(대표 3인 + 최근 5년 후보)
/rankings             출석률·표결참여율 등
/speeches             발언 검색
/methodology          지표 산출·데이터 출처·커버리지 한계
```

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
- [ ] Clerk XML(하원, ~2022) 접근·스키마 확인
- [ ] GovInfo API 키 + Congressional Record granule 파싱 확인
- [ ] FEC API 키 + 후보 5년 필터 확인
- [ ] Census Geocoder 주소→지역구 응답 확인 + 119대 경계 파일 확보
- [ ] Voteview 다운로드 필드(Members' Votes) 매핑 확인

---

## 17. 열린 결정 (미확정)

- OQ-1. 제품명·도메인.
- OQ-2. 하원 백필 시작연도: 1990(Clerk 최댓값) vs 최근 N대 의회로 한정.
- OQ-3. 뉴스 표시용 소스(v2): GDELT만 vs 유료 표시 API 병행 시점.
- OQ-4. 배포 환경(Vercel + 관리형 Postgres vs 자체 호스팅) — CLI 착수 시 결정.
- OQ-5. 데이터 갱신 오케스트레이션(cron vs Prefect/Airflow).

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
