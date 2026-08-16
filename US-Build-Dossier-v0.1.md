# 미국 정치 트래킹 플랫폼 — US 빌드 데이터소스 & 아키텍처 도시에 (v0.1)

> POLIWIKI 벤치마크 · 원자료 제공 · 중립(성향 평가 없음) · 팩트체크 최우선
> 대상: 연방 의회(하원 435 + 상원 100) · 현직 + 지역구 + 최근 5년 후보자

---

## 1. 데이터 소스 지도

소스를 3계층으로 분리한다. **1차(공식·팩트 기준선) → 2차(교차검증·백필) → 뉴스(보조·명시적 분리)**.
핵심 원칙: **표시하는 모든 사실은 1차 공식 소스로 소급 가능해야 한다.**

### 1차 — 공식 정부 소스 (퍼블릭 도메인, 팩트 기준선)

| 소스 | 커버 | 용도 | 갱신 | 비고 |
|---|---|---|---|---|
| **Congress.gov API** (`api.congress.gov/v3`) | 법안·의원·위원회·액션·요약·지명 | 핵심 1차. 법안 라이프사이클 전반 | 상시 | 5,000 req/h, API키, JSON/XML, 활발히 유지 |
| **Congress.gov House Votes (베타)** | 하원 개별 표결 (2023~, 118대+) | 하원 의원별 찬반 | 상시 | member-votes 레벨 신규 제공 |
| **senate.gov XML** | 상원 개별 표결 (1989~) | 상원 의원별 찬반 | 상시 | roll_call_lists / 개별 vote XML |
| **clerk.house.gov XML** | 하원 표결 (1990~2022) | 2023년 이전 하원 표결 백필 | 정적 | Congress.gov 베타가 못 덮는 구간 |
| **GovInfo API** (`api.govinfo.gov`) | Congressional Record(발언) 등 | 본회의/Extensions 발언 전문 | 상시 | 발언자·날짜·전문 granule |
| **FEC API / openFEC** (`api.open.fec.gov`) | 연방 후보·정치자금 | 최근 5년 후보자, 자금 | 상시 | Form 2(출마 신고)로 후보 명단 확보 |
| **Census Geocoder + TIGER/CB** | 주소→지역구, 경계 폴리곤 | 지도·"내 지역구" | 연 1회+ | 재구획 반영, 의회별 버전 관리 필요 |

### 2차 — 교차검증 / 백필 (팩트 신뢰도 강화용)

| 소스 | 용도 |
|---|---|
| **Voteview** (voteview.com, UCLA) | 표결 데이터 학술 표준. 다운로드 CSV(Members' Votes 등)로 **1차 데이터 대조·역사 백필**. NOMINATE 이념점수는 **사용 안 함**(중립 원칙) |
| **unitedstates/congress** (GitHub) | 표결 스크레이퍼·벌크 스키마 참조. 백업 파이프라인 |
| **GovTrack.us (웹)** | UX·기능 벤치마크 + 표시값 스팟체크. **API 의존 금지**(2026 여름 종료) |
| **OpenSecrets** | 자금 집계 보조(선택) |

### 뉴스 — 최근 발언 보조 계층 (반드시 분리·출처표시)

공식 Record에는 "본회의 발언"만 담긴다. 인터뷰·성명·SNS 등 **의회 밖 최신 발언**을 덮으려면 뉴스가 필요하지만, 여기가 팩트체크·중립성이 가장 취약하다. → **별도 "In the News" 계층**으로, 평가 없이 출처 링크로만 제시. (§5 참조)

---

## 2. 팩트체크 / 데이터 정합성 전략

"원자료 + 팩트 확실"을 보장하는 4원칙:

1. **공식 1차 우선**: 표결·법안·발언·후보는 항상 정부 소스가 기준. 뉴스는 사실을 "생성"하지 않고 "가리키기"만.
2. **다중소스 대조(reconciliation)**: 표결 집계는 (Congress.gov/senate.gov) ↔ (Voteview) 자동 대조. 불일치 시 플래그 → 관리자 검토 큐. 사용자에겐 확정값만 노출.
3. **원본 소급성(provenance)**: 모든 필드에 `source_url` + `retrieved_at` 저장. 상세페이지에 "원자료 보기" 링크 노출(POLIWIKI 방식).
4. **추론 금지**: 성향·의도·"이 표결은 X에 반대" 같은 해석 라벨을 붙이지 않는다. 카운트·상태·원문·링크만.

---

## 3. 데이터 모델 (US 특화)

```
Member            # bioguide_id(PK), name, party, state, chamber, status, photo, terms[]
  status: current | former | candidate_only
Term              # member_id, congress_no, chamber, district(nullable=Senate), start, end
District          # geoid, state, cd_number, congress_no, boundary(geojson), current_member_id
Bill              # congress_no, type, number → 자연키. title, policy_area, status, sponsor_id
BillAction        # bill_id, date, text, action_type(Floor/BecameLaw/...), source_system
Sponsorship       # bill_id, member_id, role(sponsor|cosponsor), date, withdrawn(bool)
Vote              # congress_no, chamber, session, roll_number → 자연키. date, question, result
VoteCast          # vote_id, member_id, position(Yea|Nay|Present|NotVoting)
Speech            # member_id, date, chamber, title, text, granule_url  (GovInfo)
CommitteeMembership
Candidate         # fec_candidate_id, name, office(H/S/P), state, district, election_years[]
CampaignFinance   # candidate_id, cycle, receipts, disbursements, cash_on_hand
NewsMention       # member_id, headline, source_name, url, published_at, (원문 저장 X, 링크만)
Provenance        # entity, field, source_url, retrieved_at, checksum
```

설계 포인트
- **자연키 우선**: Congress는 (congress_no, type, number) 등 안정적 자연키 사용 → 소스 재수집 시 멱등(idempotent).
- **지역구 없음 처리**: 상원의원·(향후)비지역 항목은 `district=null`. 지도 매핑에서 안전.
- **재구획 버전링**: District에 `congress_no` 포함 → 경계가 바뀌어도 과거/현재 분리.

---

## 4. 랭킹 설계 (출석률·표결참여율) — 재미 요소이되 중립 유지

**핵심 구분**: 이건 "성향 평가"가 아니라 **객관적 카운트 지표**다. 그래서 중립 원칙과 충돌 안 함. 단, 아래 가드레일 필수.

계산(전부 원표결에서 파생, 외부 통계 불필요):
- `표결 참여율 = 참여(Yea+Nay+Present) / 해당 기간 전체 롤콜` (member별)
- `결석 표결수 = NotVoting 카운트`
- `대표발의 수 / 공동발의 수` (Sponsorship에서)
- `본회의 발언 수` (Speech에서)

가드레일
- **동일 조건 비교만**: 하원끼리, 상원끼리. 임기 중도 합류/사망/의장(관례상 미투표) 보정.
- **"좋다/나쁘다" 라벨 금지**: 순위표는 숫자·정렬만. "출석왕" 같은 가치판단 카피 회피, "출석률 높은 순" 같은 중립 표현.
- **맥락 각주**: 낮은 참여율이 곧 불성실이 아님(질병·공무 출장 등) — 짧은 방법론 링크 상시 노출.
- **원자료 링크**: 각 순위 값 클릭 시 산출 근거(포함된 롤콜 목록)로 이동.

---

## 5. 뉴스 / 최신 발언 계층 — 팩트체크와의 긴장 해소안

문제: 사용자는 "완전 최근 발언까지" 원하지만, 뉴스는 프레이밍·편향·오보 위험. 중립·팩트 원칙과 정면 충돌 가능.

권장 3단 구성 (신뢰도 순):
1. **공식 발언 (1차)** — Congressional Record(GovInfo) 본회의 발언 전문. 가장 신뢰. 단, 의회 밖 발언은 없음.
2. **공식 성명 (준1차)** — 의원 공식 사이트/보도자료(house.gov·senate.gov 도메인), C-SPAN 영상. "본인이 낸 것"이라 출처 신뢰도 높음. 스크랩/피드 수집.
3. **언론 보도 (보조)** — 아래 옵션. **원문 저장·재현 안 함**, 헤드라인+출처명+링크+게재일만. "In the News" 탭으로 시각적 분리. 평가/성향 표시 없음.

뉴스 소스 옵션(경제성 비교)
- **GDELT** — 무료, 1979~, 구조화 이벤트/엔티티/톤. **"어떤 기사가 이 의원을 언급했나" 탐지·집계에 최적**. 단, 전문·완결 피드는 아님(표시용보다 신호용).
- **NewsData.io** — 무료 티어 상업이용 허용, 큰 아카이브. 표시용 후보.
- **NewsAPI.org** — 무료는 로컬 전용, 프로덕션은 $449/mo 절벽 → **부적합**.
- **The Guardian / NYT** — 단일 매체, 깔끔하나 비상업/커버리지 제약.

→ **1차 추천**: GDELT(무료)로 언급 탐지 + 링크아웃, 표시는 헤드라인/출처/날짜만. 유료 확장은 트래픽 붙은 뒤 재검토.

주의: 뉴스 계층은 "발언 아카이브"가 아니라 "관련 보도 인덱스"로 포지셔닝해야 중립·저작권·팩트 리스크를 동시에 관리.

---

## 6. 과거 후보자 (최근 5년)

- 소스: **FEC API**. `/candidates`에서 office=H/S 필터, election_year로 최근 5년 범위. Form 2(Statement of Candidacy)가 후보 기본정보.
- 커버 한계: FEC는 **연방 등록·자금활동 있는 후보** 중심. 소액·미등록 군소후보는 누락 가능 → 문서에 명시.
- 낙선/현직 연결: 같은 인물이 여러 사이클·직을 오갈 수 있어 fec_candidate_id ↔ bioguide_id 매핑 테이블 필요(수기 보정 일부 불가피).
- MVP 범위: "이 지역구에서 최근 5년간 출마했던 사람" 목록 + 자금 요약 + 결과. 심층 자금분석은 v2.

---

## 7. 지도 / 지역구 선택

- **주소→지역구**: Census Geocoder(공식·무료). 단건 + CSV 배치(1만건). REST 제공.
- **경계 폴리곤**: TIGER/Line(정밀) 또는 **Cartographic Boundary Files(단순화, 웹지도 적합)**. TopoJSON 변환으로 경량화.
- **재구획 주의**: 최근 AL·GA·LA·NY·NC 등 경계 변경. 119대(2025–27) 기준 적용, 의회번호로 버전 관리.
- **렌더링**: MapLibre(오픈소스) + PostGIS 공간쿼리.
- UX: 지도 클릭/주소 입력 → 하원의원 1 + 상원의원 2 카드 + "최근 5년 후보" 탭.

---

## 8. 아키텍처 & 파이프라인

```
[공식 API/XML] → [Python ETL: 수집·정규화·멱등 upsert] → [PostgreSQL + PostGIS]
                         │                                        │
                    [정합성 대조: vs Voteview]                [Next.js/TS 프런트]
                         │                                        │
                    [불일치 플래그 큐]                     [지도 MapLibre · 검색]
[GDELT/뉴스] → [링크만 인덱싱] ───────────────────────────────────┘
```

- **라이브 프록시 금지**: 소스 API를 요청마다 치지 않고 스케줄 수집→자체 DB. 속도·율제한·안정성.
- **스케줄**: 표결/액션=자주(일 단위), 의원명부=주 단위, 경계=회기 단위, 뉴스=시간 단위.
- **검색**: MVP는 Postgres FTS(발언·법안 전문). 규모 커지면 Typesense.
- **provenance/감사로그** 필수 — 팩트체크 신뢰의 근간.

---

## 9. 커버리지 & 신선도 매트릭스

| 항목 | 소스 | 시작연도 | 신선도 | 팩트신뢰 |
|---|---|---|---|---|
| 법안·액션 | Congress.gov | 1973~ | 상시 | ★★★ 공식 |
| 하원 개별표결 | Congress.gov 베타 | 2023~ | 상시 | ★★★ 공식 |
| 하원 개별표결(과거) | Clerk XML | 1990~2022 | 정적 | ★★★ 공식 |
| 상원 개별표결 | senate.gov XML | 1989~ | 상시 | ★★★ 공식 |
| 본회의 발언 | GovInfo(CR) | 1990s~ | 수일 지연 | ★★★ 공식 |
| 의회 밖 발언 | 공식 성명/뉴스 | 실시간~ | 시간 | ★~★★ 링크 |
| 후보·자금 | FEC | 수십년 | 상시 | ★★★ 공식 |
| 지역구 경계 | Census | 회기별 | 회기 | ★★★ 공식 |

---

## 10. MVP 범위 · 리스크 · 결정사항

**MVP (US, 현직 중심)**
- 대시보드: 최근 통과 법안 / 최근 롤콜 / 최근 발언
- 의원 검색 + 프로필(발의·표결·발언·위원회)
- 지도 "내 지역구" → 대표 3인 + 최근 5년 후보
- 랭킹: 출석률·표결참여율(중립 가드레일 적용)

**주요 리스크**
- 하원 표결 API가 **베타 + 2023~만** → 과거는 Clerk XML 백필 이중경로 필요.
- 뉴스 계층의 중립·저작권 관리 → 링크·헤드라인만, 전문 재현 금지.
- 재구획으로 인한 경계·의원 매핑 버전 관리 복잡도.
- FEC 후보 누락(군소후보) → 커버리지 한계 명시.
- fec_candidate_id ↔ bioguide_id 매핑 수기 보정.

**열린 결정 (다음 턴에 정할 것)**
1. 뉴스 계층: GDELT 링크형으로 시작 vs MVP에서는 공식 발언(Record)만 하고 뉴스는 v2
2. 하원 과거 표결: MVP에서 2023~만 vs Clerk XML 백필까지 포함
3. 첫 착수 산출물: (a) 상세 DB 스키마+API 매핑표, (b) 화면 정보구조/와이어프레임, (c) 수집 파이프라인 프로토타입(Python)
```
