# P4 설계문서 — 지도·지역구·후보 (2026-08-22)

작업 A(vote↔bill 링크) 완료 후 착수하는 P4의 전체 설계. 코드 작성 전 소스별 스키마 매핑·job 명세·인프라 결정·프론트 IA·시퀀싱·미결 사항을 확정한다. 스키마는 이미 `0001_init.sql`에 존재하고, `census_tiger.py`/`fec.py`는 시그니처 스텁 상태(구현만 남음).

## 1. 범위와 PRD 매핑

P4의 1차 성공 정의(PRD §2): 사용자가 **주소를 넣으면 내 지역구 대표 3인(하원 1 + 상원 2)을 지도로 찾고**, 최근 5년 후보를 본다.

| PRD | 요구 | P4 산출물 |
|---|---|---|
| FR-G1 | 주소 입력 → Census Geocoder → 지역구 판별 | 지오코더 연동(요청 시) |
| FR-G2 | 지도에서 지역구 클릭 선택 | MapLibre + 경계 폴리곤 |
| FR-G4 | 경계는 congress_no로 버전링(재구획 반영) | `district`에 119대 경계 적재 |
| FR-G5 | 상원(지역구 없음)은 주 단위 매핑 | 프론트에서 주→상원 2인 |
| FR-C1 | FEC로 최근 5년 하원·상원 후보 수집 | `candidates` job |
| FR-C2 | 지역구/주별 후보 + 정당 + 자금 요약 + 결과 | `/districts/[geoid]` |
| FR-C3 | fec_candidate_id ↔ bioguide_id 매핑 | 매칭 로직 + 수기 큐 |
| FR-C4 | 커버리지 한계 명시 | UI 카피 |

**수용 기준**: (M4) 임의 유효 미국 주소 → 정확 지역구 + 대표 3인. (FR-C2) 지역구 선택 시 최근 5년 후보 리스트.

## 2. 데이터 소스 & 스키마 매핑 (실측 기반)

### 2.1 FEC 후보·자금 → `candidate`, `campaign_finance`

- **API**: openFEC `https://api.open.fec.gov/v1`, 키 `FEC_API_KEY`(query param `api_key`).
- **레이트리밋**: 표준 api.data.gov 키 **1,000 req/hr**(429 초과). 필요 시 FEC에 상향 요청 가능. → job 사이징에 반영(아래 §3.1).
- **`/candidates/`**: 필터 `office`('H'/'S'), `state`, `district`, `election_year`(반복 가능), `cycle`, `candidate_status`, `incumbent_challenge`. 페이지네이션 `page`/`per_page`(기본 20, **최대 100**), 응답에 `pagination{count,pages,per_page}` + `results[]`.
  - → `candidate`: `fec_candidate_id`(PK), `name`, `office`, `state`, `district`, `party`, `incumbent_challenge`, `election_years[]`, `first_file_date`, `last_file_date`.
- **`/candidate/{id}/totals/`**: `receipts`, `disbursements`, `cash_on_hand_end_period`, `debts_owed_by_committee`, `coverage_end_date`, **cycle 단위** 키.
  - → `campaign_finance`: (`fec_candidate_id`,`cycle`) PK, 위 필드 매핑. `debts_owed_by_committee`→`debts_owed`.
- **`/candidate/{id}/history/`**: cycle별 `office`/`state`/`district` 변동. 사람은 챔버·지역구를 옮기므로 "이 지역구에 최근 5년 누가 출마"를 정확히 답하려면 history가 필요.
- **⚠️ 당선 결과(W/L) 부재**: openFEC은 **자금 공시 전용**이라 당락 정보가 없다. `campaign_finance.election_result`(W/L/N) 컬럼은 openFEC로 못 채운다.
  - **결정 확정(§8-A)**: **OpenElections `fec_results`를 처음부터 포함**해 W/L/N을 채운다. `candidates` job에 OpenElections 결과 조인 단계 추가(source_url·retrieved_at 별도 기록, NFR-5). 소스가 하나 더 늘므로 매칭 키(후보명·주·지역구·cycle) 정확도를 슬라이스 0에서 검증한다.

### 2.2 Census Geocoder(주소→지역구) → 요청 시, 저장 안 함

- **엔드포인트**: `/geographies/onelineaddress`, `benchmark=Public_AR_Current`, `vintage=Current_Current`, `layers`로 Congressional Districts 요청(기본 반환 세트에 포함). **키 불필요**, 명시된 하드 리밋 없음.
- 응답의 CD GEOID → `district` 조회(→ `current_member_bioguide_id`로 하원 1인). 주(state) → 상원 2인.
- **⚠️ batch 지오코더 제약**: batch `geographies`는 state/county/tract/block만 반환하고 **CD 레이어를 안 준다**(단건 조회만 CD 반환). → PRD M4(주소 샘플 정확도 검증)는 batch로 CD를 못 받으므로, 단건 반복 호출 또는 경계 point-in-polygon 자체검증으로 대체.

### 2.3 Census TIGER/CB(경계) → `district`

- **119대 = GENZ2024 릴리스**. 디렉토리 `https://www2.census.gov/geo/tiger/GENZ2024/shp/`.
- 파일명(⚠️ CLI 실측 교정): cd119는 **전국 파일 1개만 존재** — `cb_2024_us_cd119_{500k,5m,20m}.zip`(7MB). **주별 `cb_2024_{fips}_cd119_*.zip`은 404**(다른 레이어는 주별 있지만 cd119는 아님). → 전국 1개 받아 파싱 때 주 필터. 500k가 렌더링 기본.
- **⚠️ vintage는 회기로 계산 불가**(CLI 실측): GENZ2022·GENZ2023 둘 다 cd118. 명시 매핑 테이블(118→2023, 119→2024) 사용, 미등록 회기는 URL 만들지 않고 `SourceError`(틀린 연도=엉뚱한 경계 조용히 적재=FR-G4가 막으려는 사고).
- **⚠️ 원본 좌표계 NAD83(EPSG:4269)**, WGS84 아님(.prj=GCS_North_American_1983). 적재 시 `ST_SetSRID(...,4269)`→`ST_Transform(...,4326)` 명시.
- **⚠️ 준주·DC CHECK 위반**: DC/AS/GU/MP/VI/PR은 CD119FP='98'인데 `district_cd_range`는 0-60. 슬라이스 0(WY/NC/CA) 무관하나 **전량 적재 시 마이그레이션(98 허용) 결정 필요**(§8-E).
- **term 조인 주의**(CLI 실측): at-large 12석은 `term.district`가 0이 아니라 NULL(→`COALESCE(district,0)`). 한 회기에 같은 지역구 term 2개일 수 있음(사임→보선, 예: CA-01 LaMalfa→Gallagher) → 현직은 `end_date IS NULL` 우선, 없으면 최신 `start_date`.
- → `district`: `geoid`(state_fips+cd, `district_geoid()` 이미 구현), `congress_no=119`, `state`, `state_fips`, `cd_number`, `at_large`, `boundary`(MultiPolygon 4326), `boundary_simplified`(ST_Simplify), `legal_area_sqm`/`water_area_sqm`(ALAND/AWATER), `topojson_r2_key`, `current_member_bioguide_id`.
- **버전링**: FR-G4대로 congress_no로 저장. AL·GA·LA·NY·NC 재구획 때문에 경계는 회기와 함께여야 의미.

## 3. ETL Job 명세

### 3.1 `candidates` (weekly, GitHub Actions 크론)

- 대상: 최근 5년(현재 기준 2022·2024·2026 election_year) 하원·상원 전 후보.
- 흐름: `/candidates`(office H, 그다음 S; election_year 필터; per_page=100 페이징) → 각 후보 upsert → `/candidate/{id}/totals`로 cycle별 자금 → `/candidate/{id}/history`로 지역구 변동 → `match_to_bioguide`.
- **사이징**: 하원+상원 5년 후보 대략 수천 명. 후보당 3엔드포인트면 수천~1만 요청. 1,000 req/hr면 수 시간 — **Actions 6h 캡 주의**. 작업 A의 교훈대로 **bill당 commit + provenance resume 패턴 재사용**(restartable/resumable), 필요 시 첫 실행만 로컬/detached.
- 멱등: 자연키 upsert(`fec_candidate_id`, (`fec_candidate_id`,`cycle`)). provenance에 retrieved_at 기록.

### 3.2 `boundaries` (manual, per-congress)

- 흐름: `cb_2024_us_cd119_500k.zip` 다운로드 → shapefile 파싱(GDAL/pyshp/geopandas) → PostGIS로 MultiPolygon(4326) 적재 → `ST_Simplify`로 simplified → `at_large`/area 계산 → TopoJSON 생성(§5) → `current_member_bioguide_id`는 `term`(119대, chamber=house, state+district)로 조인.
- 회기당 1회 수동(경계는 회기 단위 갱신). 작업 A의 clerk/govinfo backfill처럼 restartable.

## 4. fec_id ↔ bioguide 매칭 (FR-C3, 절대 추측 금지)

`match_to_bioguide` 3단계(스텁 주석대로):
1. **exact**: (name, state, district, cycle)를 `term`(119대 등)과 대조 → method='exact'
2. **fuzzy**: `member.direct_order_name` trigram 유사도(이미 `idx_candidate_name_trgm` GIN 존재) → 임계값 이상만 method='fuzzy', **미확정 상태 유지**
3. **manual**: 나머지는 수기 보정 큐(PRD §15). `bioguide_match_confirmed_at`이 NULL이면 UI에서 "미확정"으로 표시.

원칙: 잘못된 매칭은 **남의 표결을 엉뚱한 후보 프로필에 붙이는** 심각한 오류. 미매칭이 오매칭보다 낫다.

## 5. 지오메트리·렌더링 파이프라인 & R2 결정

- **PostGIS**: 정본 geometry(point-in-polygon "이 주소가 어느 지역구"). `idx_district_boundary` GIST 존재.
- **렌더링**: 지도는 사전 단순화 **TopoJSON**을 서빙(핫 쿼리 경로·DB 커넥션 예산에서 지도 타일 분리 — Deployment §2c). `geo/topojson.py` 존재.
- **R2 결정 확정(§8-B)**: **처음부터 R2 배선.** 슬라이스 0(WY+NC+CA) TopoJSON을 R2에 업로드하고 `district.topojson_r2_key`에 키 저장, 프론트는 R2에서 서빙. 초기 설정 비용은 있지만 나중 마이그레이션이 없고 아키텍처 의도(Deployment §2c)와 일치. R2 자격증명·버킷·CORS를 슬라이스 0에서 함께 셋업·검증.

## 6. 프론트엔드 IA

- **`/districts`** (내 지역구 찾기): 주소 입력창 → 지오코더 → CD 판별 → 지도 이동 + 대표 3인 카드. MapLibre **v6**(BSD, 무료)로 경계 폴리곤 렌더.
- **`/districts/[geoid]`** (지역구 상세): 대표 3인(하원1+상원2) + 최근 5년 후보 리스트(정당·자금요약·결과, 결과는 §8-A 결정 따름) + 커버리지 한계 카피(FR-C4).
- 상원: 지역구 없음이므로 주 단위(FR-G5) — 같은 주의 상원 2인.
- 대표 연결: `district.current_member_bioguide_id` → 기존 `/members/[bioguide]` 프로필(표결·발의·발언 — 작업 A로 링크 살아있음).

## 7. 시퀀싱 — 얇은 수직 슬라이스 먼저

작업 A의 "얇게 실측 먼저" 패턴 적용. 병렬 가능한 데이터 작업(FEC·경계)과 의존 체인(지오코더·프론트) 구분.

1. **슬라이스 0 (검증)**: 한 주(예: CA 또는 소규모 주)만 경계 적재 → 단건 지오코더 → MapLibre 지도에 그 주 지역구 렌더 → 주소→CD→대표 3인 end-to-end 관통. **가장 위험한 지오메트리·지오코더·지도 통합을 먼저 검증.**
2. **경계 전량**: 50개 주 + DC/준주 119대 경계 적재 + TopoJSON.
3. **FEC 후보**(병렬 가능): `candidates` job으로 5년 후보·자금·history + bioguide 매칭.
4. **프론트 완성**: `/districts` 2종 실데이터 + 커버리지 카피 + 수기 매칭 큐 노출.
5. **검증**: 유효 주소 샘플로 지역구 정확도(M4), 매칭 방법별 분포 실측.

## 8. 결정 (2026-08-22 확정)

- **A. 당선 결과 소스**: ✅ **OpenElections `fec_results` 처음부터 포함**. `candidates` job에 결과 조인 단계 추가(source_url·retrieved_at 별도 기록).
- **B. R2 배선 시점**: ✅ **처음부터 R2 배선**. 슬라이스 0에서 R2 버킷·자격증명·CORS 셋업·검증.
- **C. 슬라이스 0 대상**: ✅ **WY + NC + CA 3개 주**. WY=at-large(cd 00), NC=재구획 다지역구(버전링 검증), CA=52지역구(볼륨·성능·TopoJSON 용량). 3개로 전 구조적 엣지케이스 커버.
- **D. 지오코더 호출 위치**: ✅ **Next.js API route(서버 경유)**. 주소=PII이므로 클라이언트 직접 호출 대신 서버에서 처리·캐싱.
- **E. 준주·DC 전량 적재(미결)**: cd119 전국 파일에 DC/AS/GU/MP/VI/PR(CD119FP='98')이 포함되나 `district_cd_range` 0-60 CHECK 위반. 전량 적재 단계에서 결정 — (a) 마이그레이션으로 98 허용해 비투표 대표(delegate) 포함 / (b) 50개 주만 적재하고 준주 제외. boundaries job에 `--include-non-voting` 플래그 이미 존재. → 전량 적재 착수 시 사용자 결정.

## 9. 리스크

| 리스크 | 완화 |
|---|---|
| 재구획 경계·매핑 복잡 | `district`에 congress_no 버전링(이미 반영) |
| FEC 후보 누락(군소) | 커버리지 한계 UI 명시(FR-C4) |
| fec_id↔bioguide 매핑 오류 | 3단계 매칭 + 수기 큐 + 미확정 표시 |
| batch 지오코더 CD 미반환 | M4 검증은 단건 호출/PIP 자체검증 |
| openFEC 1,000/hr + 6h 캡 | restartable/resumable job, 첫 실행 로컬 |
| TopoJSON 용량·DB 예산 | PostGIS는 PIP만, 렌더는 사전단순화 TopoJSON 분리 |

## 10. 착수 순서 요약

결정 A~D 확정됨(§8) → **슬라이스 0(WY+NC+CA: 경계 적재+R2 TopoJSON+지오코더+MapLibre 지도+대표3인+FEC 후보+OpenElections 결과 end-to-end 관통)** → 경계 전량(47개 주+DC/준주) → FEC 전량(병렬) → 프론트 완성 → M4 검증. 각 단계 작업 A와 동일하게 CLI 실행 / Cowork 리뷰·검증.

**다음 CLI 착수 작업 = 슬라이스 0.** 먼저 `census_tiger.py`의 `fetch_district_boundaries`(GENZ2024 URL 매핑)와 boundaries job으로 WY·NC·CA 경계를 PostGIS에 적재하고 TopoJSON→R2까지 관통하는 것부터 시작. R2 자격증명은 자격증명 프로토콜대로 별도 처리.

## 11. 슬라이스 0 · 1단계 실측 (2026-08-24)

WY+NC+CA 경계 적재 → TopoJSON → R2 공개버킷 → 공개 URL fetch → CORS까지 관통 완료. **1단계 종료.** 측정값만 기록한다.

### 적재 결과

| state | districts | boundary | 현직 링크 | at-large |
|---|---:|---:|---:|---:|
| CA | 52 | 52 | 52 | 0 |
| NC | 14 | 14 | 14 | 0 |
| WY | 1 | 1 | 1 | 1 |
| **계** | **67** | **67** | **67** | **1** |

`ST_IsValid` 위반 0, GEOID 67건 전부 `district_geoid()` 왕복 일치, 현직 미링크 0.

### R2

- 원본 zip 스냅샷 → `civiclens-snapshots/census/district_boundaries/congress-119-500k/<ts>.raw` (7,045,981 B).
- TopoJSON → `civiclens-public/districts/congress-119.0257c273c137.topojson` (206,595 B, 67 geometries, arcs 225).
- 공개 URL 200 OK, `Content-Type: application/json`, `Cache-Control: public, max-age=31536000, immutable`.
- 내려받은 바이트의 sha256 앞 12자 = 키의 지문 `0257c273c137` — 빌드 산출물과 공개 서빙 오브젝트가 바이트 동일함을 확인.
- 빌드는 결정적 — **단, 같은 DB 안에서만**. 재실행해도 같은 206,595 B·같은 지문 → 키가 안 바뀌고 `topojson_r2_key` UPDATE도 no-op. PostGIS 버전이 다르면 산출 바이트가 달라진다(§12 발견 4에서 교정).
- 2회 실행 후 오브젝트 수: 공개 버킷 **1개**(지문 고정 → 멱등), 스냅샷 버킷 **2개**(키가 타임스탬프 —
  fetch 1회당 1개가 남는 게 감사추적의 의도된 동작이다).

### 실측 발견 1 — 고정 키 + `immutable`은 캐시 독성

`districts/congress-119.topojson` 고정 키에 1년 `immutable`로 올리면, 전량 적재(441개)가 같은 키를 덮어써도
CDN·브라우저는 최대 1년간 3개 주짜리 문서를 계속 낸다. 무효화 수단이 없다. 슬라이스 0 다음 단계에서 바로 터지는 문제라
**키에 내용 지문을 넣어** 해결했다(`districts/congress-{no}.{sha256[:12]}.topojson`). 새 문서 = 새 URL이므로
DB 포인터만 옮기면 되고 캐시를 건드릴 필요가 없다. 이전 오브젝트는 남겨 둔다(롤백 1 UPDATE, 수백 KB).

### 실측 발견 2 — r2.dev 공개 URL은 CORS를 주지 않는다 ✅ 해결

R2에서 **public-read와 CORS는 별개 스위치**다. curl로는 200이지만 `Origin` 헤더를 붙여도 응답에
`Access-Control-Allow-Origin`이 없고, `OPTIONS` 프리플라이트는 **403**이다. 즉 바이트는 누구나 읽을 수 있는데
**브라우저 `fetch()`만 차단**된다 — 지도가 못 읽는다.

버킷 CORS 규칙(`PUBLIC_CORS_RULES`, GET/HEAD, `*`)은 `common/r2.py`에 코드로 넣고 publish 경로에서 적용을
시도하도록 배선했다(실패는 비치명적). 다만 **현재 R2 토큰이 "Object Read & Write" 범위라 `PutBucketCors`가
AccessDenied**다 — 버킷 설정 호출은 **"Admin Read & Write" 토큰**이 필요하다. 2단계(지도) 착수 전에
Admin 토큰 재발급 또는 대시보드에서 CORS 규칙 적용이 선행돼야 한다.

`*` 오리진을 고른 이유: 오브젝트는 이미 curl로 공개이므로 브라우저에 추가 권한을 주는 게 아니고,
프로덕션 도메인으로 고정하면 Vercel 프리뷰 배포(배포마다 호스트명이 다름)가 전부 깨진다.

**해결(2026-08-24)**: 사용자가 Cloudflare 대시보드에서 civiclens-public에 규칙(GET/HEAD, origin `*`)을 적용.
재검증 실측:

```
OPTIONS + Origin + Access-Control-Request-Method: GET
  -> 204, Access-Control-Allow-Origin: *, Access-Control-Allow-Methods: GET, HEAD
     Access-Control-Max-Age: 3600, Vary: Origin
GET + Origin
  -> 200, Access-Control-Allow-Origin: *, 206,595 B
```

브라우저 `fetch()` 경로가 열렸다. 슬라이스 0 1단계 종료.

⚠️ **선언값과 라이브 값이 다르다.** 코드의 `PUBLIC_CORS_RULES`는 `MaxAgeSeconds` 86400 +
`ExposeHeaders`(ETag, Content-Length)인데, 대시보드로 넣은 라이브 규칙은 max-age 3600 + expose-headers 없음이다.
지도 fetch에는 기능적으로 동일하지만(프리플라이트 캐시 수명 차이뿐, JS가 ETag를 읽지 않음), 나중에 Admin 범위
토큰으로 `ensure_public_cors()`가 실제로 성공하면 **코드 쪽 값으로 덮인다**. 그때 값이 바뀌는 건 의도된 것이지
회귀가 아니다.

### 실측 발견 3 — Windows 콘솔 cp949

`configure_logging`이 stdlib 기본 핸들러를 쓰면 로그 한 줄의 비ASCII 문자에서 `UnicodeEncodeError`가 나
잡 전체가 죽는다. 핸들러 스트림의 에러 정책만 `backslashreplace`로 바꿨다(인코딩은 터미널 선언값 유지 → CI UTF-8 무영향).

## 12. 슬라이스 0 · 2단계 착수 — Neon 적재 (2026-08-24)

앱 런타임(Neon)에 WY+NC+CA를 적재. 로컬 `.env`는 `localhost:55432` 그대로 두고, 그 한 번의 호출에만
`DATABASE_URL`을 Neon **direct(unpooled)** 로 줬다.

### Preflight (읽기전용)

| 항목 | 값 |
|---|---|
| 엔드포인트 | direct (`-pooler` 아님) — 대량 geometry 쓰기라 PgBouncer 우회 필수 |
| postgis | 3.6.0 |
| 최신 마이그레이션 | 0005 |
| `district` 테이블 | 존재, **0행** (클린 적재) |
| `term` 119대 하원 | 449행 / 슬라이스 0: CA 53(현직 51), NC 14(14), WY 1(1) |

`term` 확인이 핵심이었다 — 비어 있었으면 경계는 들어가고 `current_member_bioguide_id`만 전부 NULL로
조용히 남았을 것이다. CA가 53 term / 현직 51인 건 정상이다: 52지역구 중 1곳이 승계(LaMalfa→Gallagher),
1곳이 공석이라 `end_date IS NULL` 우선 + 최신 `start_date` 폴백 규칙이 그대로 필요한 사례다.

### 적재 결과 (Neon 실측)

```
CA: districts=52 geom=52 valid=52 member=52 keys=1
NC: districts=14 geom=14 valid=14 member=14 keys=1
WY: districts=1  geom=1  valid=1  member=1  at_large=1 keys=1
합계 67 / invalid=0 / no_member=0 / wrong_srid=0 / wrong_type=0 / no_simplified=0
GEOID 왕복 불일치 0/67
topojson_r2_key = districts/congress-119.aaad7416d0af.topojson  x67
provenance: 67행, 스냅샷 1개
```

멤버 링크 스팟체크 — `0601 CA-01 → James Gallagher`(승계 후임이 잡힘), `5600 WY-00 at_large → Harriet M. Hageman`,
`3701 NC-01 → Donald G. Davis`.

PIP 자체검증(FR-G1 폴백, NFR-3): Cheyenne → `5600`, Raleigh → `3702`, San Francisco → `0611`. 전부 일치.

공개 URL 재검증: `aaad7416d0af` 오브젝트도 프리플라이트 204 + `Access-Control-Allow-Origin: *`,
GET 200, 내려받은 바이트 sha256 앞 12자 = 키 지문 일치.

### 실측 발견 4 — 같은 입력·같은 코드인데 PostGIS 버전이 다르면 geometry가 달라진다

Neon이 만든 TopoJSON은 **206,596 B**로 로컬(206,595 B)과 1바이트 다르고 지문도 다르다. 추적한 결과:

- 67개 중 **5개**(`0601 0602 3705 3711 3714`)의 **저장된 geometry(WKB)가 다르다**. 정점 수는 동일.
- 단계 격리 결과 갈리는 지점은 **`ST_Transform(4269→4326)`** 하나다. parse까지는 동일,
  transform부터 다르다. `ST_MakeValid`는 원본이 이미 valid라(양쪽 `ST_IsValid=true`) 무영향.
- 원인은 **PROJ 버전**: 로컬 PostGIS 3.4.3 / GEOS 3.9.0 / **PROJ 7.2.1** vs Neon 3.6.0 / GEOS 3.12.1 / **PROJ 9.4.0**.
  PROJ 9가 NAD83→WGS84 변환 파이프라인을 다르게 고른다.
- 크기: 좌표 차이 약 **1e-6도(≈10 cm)**. 지도 산출물에서는 225개 arc 중 6개가 양자화 1스텝(≈4 m) 다르다.
  원본이 1:500,000 일반화 도면이라 이 정도는 소스 자체 정확도보다 **훨씬** 아래다. 렌더링·PIP 모두 무의미한 차이.

**중요한 건 결과가 아니라 이게 드러낸 것이다.** 고정 키였다면 Neon 실행이 로컬 오브젝트를
1년 `immutable` 캐시 아래에서 조용히 덮어썼을 것이고, 바이트가 1개 다른 걸 아무도 눈치채지 못했고
무효화도 못 했다. 지문 키가 정확히 이 사고를 잡아낸 것이다(§11 발견 1).

**정본은 Neon이다.** 앱은 `district.topojson_r2_key`를 Neon에서 읽으므로 `aaad7416d0af`를 받는다 — 정합적이다.
로컬이 만든 `0257c273c137`는 버킷에 남겨 둔다(로컬 DB를 보는 개발 실행이 참조).

**미결(사용자 결정)**: 로컬 Docker PostGIS를 프로덕션과 맞출지. `postgis/postgis:16-3.4` →
Neon의 3.6/PROJ 9 계열로 올리면 dev·prod 산출물이 일치해 로컬에서 계산한 지문으로 프로덕션을 검증할 수 있다.
급하지는 않다 — 기능 차이가 아니라 재현성 문제다.
