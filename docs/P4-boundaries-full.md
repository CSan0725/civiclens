# P4 — 전량 경계 적재 (50개 주 + DC + 준주), 1단계: 마이그레이션 0008 + 로컬

측정일 2026-08-27. 슬라이스 0(WY+NC+CA, 67 지역구)에서 119대 전량 441 지역구로 확장한다.
이 문서는 **로컬 PostGIS까지의 실측**이다. Neon 적용과 R2 publish는 2단계.

## 0. 결정 — §8-E는 (a)로 닫혔다

P4 설계 §8-E가 열어둔 선택지는 "'98'을 허용해 비투표 대표를 싣는다"와 "50개 주만 싣는다"였다.
**(a)를 택했다.** 근거는 세 가지다.

- 여섯 관할구 전부 119대 `term`에 현직이 있다 (Norton·Radewagen·Moylan·King-Hinds·Hernández·Plaskett).
- 워싱턴 DC 주소는 사용자가 실제로 입력하는 주소다. 거기에 "지역구 없음"을 답하는 것은
  **비어 있는 답이 아니라 틀린 답**이다.
- Census 지오코더 자신이 그 주소에 `1198`을 답한다(§4에서 실측). 우리가 답하지 않으면
  1차 출처와 어긋난다.

## 1. 마이그레이션 0008

`district_cd_range`를 `BETWEEN 0 AND 60` → `BETWEEN 0 AND 60 OR = 98`로 바꾼다.

**상한을 98로 넓히지 않고 98을 명시한 이유**: '98'은 98번째 지역구가 아니라
"이 관할구는 번호가 붙은 지역구가 아니라 비투표 의석 하나를 가진다"는 Census의 센티널이다
(at-large 주에 대한 '00'과 같은 역할). 상한을 넓히면 61~97도 함께 통과하는데, 그것들은
지역구가 아니라 오타다. 센티널을 이름으로 적어두면 하류에서 다음 동치가 성립한다:

    cd_number = 98  <=>  Delegate 또는 Resident Commissioner 의석

`non_voting` 불리언 컬럼은 **두지 않았다.** 그 컬럼은 `cd_number`에서 파생될 뿐이고,
파생 컬럼은 원본과 어긋날 수 있다. `at_large`는 이미 여섯 행 모두 true다
(LSAD C1/C3/C4가 전부 "관할구 전체가 한 의석"을 뜻한다).

이 마이그레이션이 주장하지 **않는** 것: Delegate가 Representative라는 것.
차이는 본회의 표결권이고, 그것은 경계 테이블이 아니라 페이지의 카피에 속한다(3단계).

| 검증 | 결과 |
|---|---|
| `dbmate up` 로컬 | ✅ |
| `down` → `up` 왕복 (ci-db가 하는 그대로) | ✅ |
| 적용 후 제약 | `CHECK (((cd_number >= 0) AND (cd_number <= 60)) OR (cd_number = 98))` |
| `db:check` 스키마 드리프트 | ✅ 일치 |
| `db:pull` 재생성 diff | 1줄 (`generated/schema.ts`의 check 문자열) |

down은 `cd_number = 98` 행을 먼저 지운다. 좁아진 제약은 위반 행 위에 다시 붙지 않기 때문이다.
`district`를 참조하는 외래키는 하나도 없고, 여섯 행은 같은 국가 파일을 다시 돌리면
바이트 단위로 복원된다 — 버려지는 것은 공개 shapefile의 캐시 사본이다.

## 2. 코드 결함 1건 — 여섯 관할구는 링크되지 않았을 것이다

`_LINK_CURRENT_MEMBER`의 조인은 `d.cd_number = t.cd_number`였다. `term`은 at-large든
delegate든 `district`를 NULL로 저장하므로 `COALESCE(district, 0)` → 0이 되는데,
shapefile은 at-large 주만 '00'이고 여섯 관할구는 '98'이다. **0 = 98은 성립하지 않는다.**

마이그레이션만 하고 이 조인을 그대로 뒀다면, 여섯 행은 적재는 되지만 현직이 NULL인 채로
남는다 — `term`에 그 사람이 앉아 있는데도. `no_member` 카운터가 0이 아니게 되는 정도라
조용히 지나가지는 않았겠지만, 애초에 조인이 물어야 할 것은
"이 관할구가 가진 하나뿐인 의석"이다.

수정: 지역구 쪽도 정규화한다 — `CASE WHEN d.cd_number = 98 THEN 0 ELSE d.cd_number END`.

**반사실 실측** (적재 후 옛 조인 형태를 그대로 재현해 측정):

| 옛 조인에서 링크 실패 | 그중 비투표 의석 |
|---:|---:|
| 6 | 6 |

정확히 여섯 개, 전부 마이그레이션이 방금 실을 수 있게 만든 그 행들이다.

## 3. 로컬 적재 실측

`civiclens-etl boundaries --congress 119 --include-non-voting --no-publish`,
`cb_2024_us_cd119_500k.zip` (국가 파일 1개, 7 MB), NAD83(4269)→WGS84(4326).
**소요 10초** (다운로드 1.2초 포함). 슬라이스 0과 같은 주별 커밋·멱등 upsert 경로.

| 항목 | 값 |
|---|---:|
| 지역구 | **441** |
| 관할구 | 56 |
| 투표 의석 (`cd_number <> 98`) | **435** — 하원 정원과 일치 |
| 비투표 의석 (`cd_number = 98`) | 6 |
| at-large 주 (`cd_number = 0`) | 6 (AK·DE·ND·SD·VT·WY) |
| `at_large` 플래그 | 12 (= 위 6 + 비투표 6) |
| `ST_IsValid` 실패 | **0** |
| `boundary` NULL | 0 |
| `boundary_simplified` NULL | 0 |
| `source_url`/`retrieved_at` 결측 | 0 |
| 현직 미링크 | **0** |
| 링크된 행 / 서로 다른 의원 | 441 / **441** (한 사람이 두 의석을 갖지 않는다) |
| `term` 쪽 고아 (지역구 없는 하원 term) | 0 |
| GEOID 왕복 불일치 | **0** |
| SRID / 타입 | 4326 / MultiPolygon (441행 전부) |
| 지역구 간 내부 겹침 | **0 쌍** |

여섯 비투표 의석과 현직:

| GEOID | 관할구 | 현직 |
|---|---|---|
| 1198 | DC | Eleanor Holmes Norton |
| 6098 | AS | Aumua Amata Coleman Radewagen |
| 6698 | GU | James C. Moylan |
| 6998 | MP | Kimberlyn King-Hinds |
| 7298 | PR | Pablo José Hernández |
| 7898 | VI | Stacey E. Plaskett |

## 4. 정확도 — 전국으로 넓힌 M4

M4와 같은 방법이다. 우리 데이터가 아닌 **다른 Census 산출물**을 정답으로 쓴다:
Census 지오코더의 `/geographies/coordinates`(119th Congressional Districts 레이어).

각 지역구 폴리곤 내부에서 결정적 시드로 점 1개를 뽑아 지오코더에 물었다.

| 표본 | 일치 | 불일치 | 무응답 | 정확도 |
|---:|---:|---:|---:|---:|
| 439 | 438 | 1 | 0 | **99.8%** |

**불일치 1건은 우리 결함이 아니다.** 우리 SC-04, 지오코더 NC-11, 위치
(-82.75907, 35.06726). 그 점은 두 지역구가 공유하는 NC/SC 주 경계선에서 **87.7 m** 떨어져 있다
(공유 경계 길이 65.4 km). M4가 분류한 "경계 일반화" 부류와 같다 — 우리는 일반화된
`cb_500k`을 싣고, 지오코더는 TIGERweb 원해상도로 답한다. 우리 판정에 자기모순은 없다.

**표본이 441이 아니라 439인 이유**: `ST_GeneratePoints`가 CA-42와 MP에서 점을 내지 못했다.
둘 다 바운딩박스 대부분이 폴리곤 바깥(바다)이라 기각 표집이 포기한 것이고, 지오메트리는 멀쩡하다
— 시드를 바꾸면 점이 나온다. 두 곳은 육지 지점으로 따로 확인했다.

육지 지점 대조 — 여섯 비투표 관할구 전부 + DC:

| 지점 | 우리 | 지오코더 |
|---|---|---|
| Saipan Intl Airport, MP | 6998 | 6998 |
| Capitol Hill, Saipan MP | 6998 | 6998 |
| Pago Pago, AS | 6098 | 6098 |
| Tamuning, GU | 6698 | 6698 |
| Christiansted, VI | 7898 | 7898 |
| Ponce, PR | 7298 | 7298 |
| White House, DC | 1198 | 1198 |
| Long Beach, CA-42 | 0642 | 0642 |

랜드마크 12곳(IL·TX·WA·MA·MO·PA·HI·AK 포함) 대조도 **12/12 일치**.

> 측정 중 얻은 교훈 하나: 사이판 Garapan의 좌표로 처음 쓴 점은 우리 폴리곤 밖 308 m,
> 즉 서쪽 석호(물) 위였다. 지오코더는 그래도 6998을 답했다. **정답 기준을 우리 기억이 아니라
> 1차 출처에 두지 않았다면 이것을 "우리 결함"으로 기록했을 것이다.** 랜드마크 12곳 중
> 3곳도 우리가 적은 기대값이 틀렸고 적재 데이터가 맞았다.

## 5. TopoJSON (로컬 생성만, 미발행)

`--no-publish`는 빌드 자체를 건너뛰므로 용량 확인을 위해 별도로 생성했다.
`geo/topojson.py` 기본값(quantization 1e6, toposimplify 0.001).

| 항목 | 슬라이스 0 (67) | 전량 (441) |
|---|---:|---:|
| feature | 67 | **441** |
| arc | — | 2,926 |
| raw | — | **1,696,962 B** |
| gzip | — | **519,079 B** |

`geo/topojson.py` 헤더에 적힌 2026-08-22 예측치(1,683,896 B / 521 KB gzip)와 일치한다.
441개 전량 지도 레이어가 **gzip 507 KB** — 한 번 받아 1년 immutable 캐시되는 객체로서 무리 없다.

## 6. 남은 상태 — 2단계가 정리할 것

- **로컬 `topojson_r2_key`가 갈라져 있다**: 67행은 슬라이스 0 객체
  (`districts/congress-119.0257c273c137.topojson`)를 가리키고 374행은 NULL이다.
  `--no-publish`로 돌렸으니 예상된 상태다. 2단계의 publish가
  `_SET_TOPOJSON_KEY`로 441행 전부를 새 키로 덮는다(`all_states=true`).
  `getDistrictTopojsonKeys`는 NULL을 걸러내므로 지금 로컬 지도는 3개 주만 그린다 —
  깨지지는 않는다. **Neon(정본)은 이 단계에서 건드리지 않았다.**
- Neon 적용 + 전량 적재 + R2 publish → 2단계.
- `/districts` 커버리지 카피("CA/NC/WY만") → 3단계.
- 3단계에서 함께 정할 것: **Delegate를 어떻게 부를 것인가.** DC 페이지가 Norton을
  다른 435석과 같은 말로 "대표"라 부르면 표결권 유무를 지운다. 상원 2인은 자연히
  비게 된다(DC·준주에 senate term이 없다) — 그 빈자리도 설명이 필요하다.

## 7. 권고 (사용자 결정 필요, 1단계 범위 밖이라 실행하지 않음)

`--include-non-voting`은 여전히 opt-in이다. 그 플래그가 존재했던 이유는
"마이그레이션 전에는 INSERT가 깨진다"였는데 0008로 해소됐다. 지금 상태에서 120대 경계를
플래그 없이 적재하면 DC가 조용히 빠진다 — FR-G4가 막으려는 부류의 사고다.
기본값을 켜는 쪽으로 뒤집을지는 CLI 계약 변경이라 별도 판단으로 남긴다.

---

# 2단계 — Neon(정본) 적용·적재·발행

측정일 2026-08-27.

## 1. 프리플라이트 (읽기전용)

| 항목 | 값 |
|---|---|
| 적용된 마이그레이션 | 0001–0007, **0008 pending** |
| 적용 전 제약 | `CHECK ((cd_number >= 0) AND (cd_number <= 60))` |
| `district` (119대) | 67행 / 3개 주 / 전부 `aaad7416d0af` 키 |
| 119대 하원 term | 449 (district 있음 437) — 로컬과 동일 |
| 여섯 관할구 term | 전부 존재 |
| Neon 스택 | PostGIS 3.6.0 · GEOS 3.12.1 · **PROJ 9.4.0** |

## 2. 마이그레이션 0008

`dbmate up` 842 ms. 적용 후 제약
`CHECK (((cd_number >= 0) AND (cd_number <= 60)) OR (cd_number = 98))`,
컬럼 코멘트 반영, `Applied: 8 / Pending: 0`.

## 3. 전량 적재

`boundaries --congress 119 --include-non-voting`. 441행 upsert 약 35초.

| 항목 | 값 |
|---|---:|
| 지역구 / 관할구 | **441 / 56** |
| 투표 435 · 비투표 6 · at-large 주 6 · `at_large` 12 | ✓ |
| `ST_IsValid` 실패 · geom NULL · simplified NULL · provenance 결측 | **0 · 0 · 0 · 0** |
| 멤버 링크 / 서로 다른 의원 | **441 / 441** |
| SRID · 비-MultiPolygon · GEOID 불일치 · 내부 겹침 | 4326 · 0 · 0 · **0쌍** |
| PIP 자체검증 (DC·PR·GU·AS·VI·MP·IL·TX·AK) | **9/9** |

### PROJ 발산이 다시, 예고대로

Neon이 만든 TopoJSON은 **1,697,013 B**로 로컬(1,696,962 B)보다 **51 B 크다**.
설계 §12 발견 4가 슬라이스 0에서 1 B 차이로 잡아낸 것과 같은 원인이다
(로컬 PROJ 7.2.1 vs Neon 9.4.0의 NAD83→WGS84 파이프라인 선택). 지문도 다르다:
로컬 `e4659a7dd140`, **Neon `8f1627032c94`**. 정본은 Neon이고, 앱은 Neon에서 키를 읽으므로 정합적이다.

## 4. R2 발행

| 항목 | 값 |
|---|---|
| 키 | `districts/congress-119.8f1627032c94.topojson` |
| 크기 / 타입 / 캐시 | 1,697,013 B · `application/json` · `public, max-age=31536000, immutable` |
| `topojson_r2_key` 갱신 | **441행** (이전: 67 slice-0 + 374 NULL → 전부 새 키) |

### ⚠️ CORS 규칙은 적용하지 못했다 — 그런데 필요가 없었다

`ensure_public_cors()`가 `PutBucketCors`에서 **AccessDenied**로 실패했다.
이 세션의 R2 토큰이 **오브젝트 스코프**라 버킷 설정을 못 만진다(`GetBucketCors`도 동일).
코드는 이 경우를 이미 알고 경고만 남기고 계속한다(`r2.cors_not_applied`).

**결과적으로 무해했다**: CORS는 버킷 단위 설정이고 슬라이스 0에서 이미 걸어 뒀다.
새 오브젝트는 그 규칙을 그대로 상속한다 — §5에서 브라우저로 실측 확인했다.
다만 **버킷을 새로 만드는 상황이었다면 이 토큰으로는 지도가 뜨지 않는다.**
버킷 설정을 바꿔야 할 때는 Admin Read & Write 토큰이 필요하다.

## 5. 공개 URL 검증 — 그리고 검증 도구가 틀렸던 이야기

`https://pub-7f369302fb534a638b9dd927635079d8.r2.dev/districts/congress-119.8f1627032c94.topojson`

**첫 시도는 403이었다.** Python `urllib`로 프리플라이트·GET 둘 다 403.
자격증명이나 공개설정 문제로 결론 내리기 전에 **알려진 정상 대조군**을 찍었다 —
2026-08-25에 204/200/지문일치로 검증됐고 그 뒤 손대지 않은 슬라이스 0 오브젝트
`aaad7416d0af`. **그것도 똑같이 403이었다.** 그러면 원인은 이번 업로드가 아니다.

응답 본문이 `error code: 1010`, `Server: cloudflare` — Cloudflare가 **클라이언트의 브라우저
시그니처**를 보고 막은 것이다. senate.gov 403(P1 발견 7)과 같은 부류이고, 오브젝트 권한과 무관하다.
UA 스푸핑은 하지 않는다.

두 갈래로 다시 측정했다.

**(a) S3 API로 저장된 바이트 자체** (CDN을 경로에서 뺀다):

| 키 | 크기 | sha256[:12] | 지문 일치 | feature | 관할구 |
|---|---:|---|---|---:|---:|
| `aaad7416d0af` | 206,596 B | `aaad7416d0af` | ✅ | 67 | 3 |
| `8f1627032c94` | 1,697,013 B | `8f1627032c94` | ✅ | **441** | **56** |

새 문서의 비투표 feature: `AS, DC, GU, MP, PR, VI`.

**(b) 실제 브라우저로 교차출처 fetch** — 로컬 http 오리진(`127.0.0.1:8731`)에서
커스텀 헤더를 붙여 **프리플라이트를 강제**한 뒤 r2.dev를 fetch:

```
preflighted GET status 200
bytes 1697013
sha256[:12] 8f1627032c94        <- 키 지문과 일치
features 441
jurisdictions 56
nonvoting AS,DC,GU,MP,PR,VI
```

프리플라이트가 실패했다면 fetch 자체가 예외로 끝났을 것이므로, **CORS 규칙은 살아 있다.**
공개 읽기·CORS·지문 전부 확인 — 403은 우리 파이썬 클라이언트만의 문제였다.

> 교훈은 1단계와 같은 것의 반복이다. **정상 대조군을 먼저 찍지 않았다면
> "R2 공개설정이 깨졌다"고 보고했을 것이다.** 바뀐 것과 안 바뀐 것을 같이 측정해야
> 원인이 어디 있는지가 나온다.

## 6. 라이브 사이트 — 전량 반영 확인

배포 없이 반영됐다(`/districts`는 `force-dynamic`이고 키를 DB에서 읽는다).

- 페이지가 내려주는 오브젝트 URL = **`8f1627032c94`** (441 지역구 문서) ✓
- `coveredStates` = **56개 관할구** — `AS DC GU MP PR VI` 포함 ✓
- 지도 상태줄: **"441 districts drawn."** — 브라우저가 R2에서 받아 파싱한 결과다 ✓
- `/districts/1198`(DC) 정상 렌더, 현직 Eleanor Holmes Norton 표시 ✓

## 7. 3단계로 넘기는 것 — 라이브가 지금 하는 잘못된 진술 6가지

전량 적재가 끝나자 카피가 틀린 자리가 드러났다. `/districts/1198`에서 실제로 보이는 문장들이다.

1. **`/districts` 커버리지**: "Boundaries are loaded for AK, … WY. **Other states are being added.**"
   — 더 추가될 주가 없다. 56곳 전부 실렸다.
2. **제목 `DC-AL` · 부제 "at-large district"** — DC는 at-large 지역구가 아니라 **Delegate 지역구**다.
   `at_large` 플래그가 true인 것은 맞지만(LSAD C4), 표기는 그 둘을 구분해야 한다.
3. **"One House member for the district, and both of the state's Senators"**
   — DC에는 상원의원이 없고, Norton은 본회의 표결권이 없다.
4. **"No sitting Senators recorded for this state / Every state elects two. An empty list here means
   the roster has not been collected, not that the seats are vacant."**
   — **명백히 틀린 진술이다.** DC는 주가 아니고 상원의원을 뽑지 않는다. 명부가 덜 수집된 게 아니라
   존재하지 않는 것이다. "빈 셀의 세 가지 의미"(2d)에서 **셋 중 틀린 하나**를 고르고 있다.
5. **"Candidates for DC Senate seats"** 섹션 — 없는 의석에 대한 후보 섹션.
6. **표결권에 대한 언급이 없다** — 여섯 관할구의 대표는 위원회에서는 표결하지만
   본회의 최종 통과 표결에는 참여하지 못한다. 마이그레이션 0008이 "이건 경계 테이블이 아니라
   페이지 카피의 몫"이라고 미뤄 둔 바로 그 사실이다.

(3)(4)(5)는 사실관계가 틀린 진술이라 FC-1 위반에 가깝고, (1)은 낡은 진술이다.
3단계에서 함께 고친다.

---

# 3단계 — 관할구 유형에 따라 정직하게 렌더

측정일 2026-08-28.

2단계가 남긴 **틀린 진술 6건**을 고쳤다. 전부 "빠진 사실"이 아니라 **"틀린 사실"**이고,
FC-1이 금지하는 건 후자다.

## 1. 원인은 카피가 아니라 전제였다

여섯 문장은 각자 잘못 쓰인 게 아니다. 네 곳이 **각자** "지역구란 이런 것"을 가정하고 있었고,
슬라이스 0이 CA·NC·WY뿐이라 셋 다 주였기 때문에 그 가정이 한 번도 틀리지 않았을 뿐이다.
441개가 들어오자 여섯 개가 그 가정을 깨뜨렸다.

그래서 카피를 여섯 번 고치는 대신 **답을 한 곳에 모았다** — `lib/jurisdiction.ts`.
지역구 상세 페이지·지도 패널·주소 조회 API·지역구 API 넷이 같은 모듈에 묻는다.
각자 판단하게 두는 것이 애초에 넷이 어긋난 방식이다.

**`cd_number`가 아니라 관할구 코드로 판정한다.** DB는 같은 사실을 Census 센티널
`cd_number = 98`(마이그레이션 0008)로 말하고 둘은 구성상 일치하지만, 코드는 어디서나 쓸 수 있다 —
주소 조회는 DB를 만지기 전에 이미 주를 알고, 지역구 행이 없는 관할구도 정확히 설명돼야 한다.

## 2. 고친 6건 (+ 실측 중 발견한 1건)

| # | 있던 문장 | 지금 |
|---|---|---|
| 1 | `/districts` "Other states are being added." | 적재 현황에서 **도출**: 전량이면 "all 50 states, the District of Columbia, and the five territories … every district in the Congress", 부분이면 "Still to load: …" |
| 2 | 제목 `DC-AL` · 부제 "at-large district" | 제목 `DC` · 부제 "**Delegate district · non-voting**" (PR은 "Resident Commissioner district") |
| 3 | "One House member … and both of **the state's** Senators" | "District of Columbia elects one **Delegate** to the House and **no Senators**." |
| 4 | "**Every state elects two.** An empty list here means the roster has not been collected" | "**District of Columbia elects no Senators** / Senators represent states. District of Columbia is not a state, so there is no Senate seat to show — **this is not missing data**." |
| 5 | "Candidates for **DC Senate seats**" 섹션 | 상원 의석이 있는 주에만 렌더. **쿼리 자체를 안 던진다** |
| 6 | 표결권 언급 없음 | 카드에 "**Does not vote on final passage of legislation on the House floor.**" + 커버리지 문단에 설명 |
| **7** | **주소 조회가 "CivicLens does not carry these seats yet"** | **제거. DC 주소가 Norton을 반환한다** |

### 7번은 사용자가 준 목록에 없다 — `/districts/1198`에서는 안 보이기 때문이다

`/api/districts/lookup`이 **DB를 묻기도 전에** `cd_number === 98`에서 끊고
`non_voting_delegate` + "CivicLens does not carry these seats yet"를 돌려주고 있었다.
스키마 cd 범위가 0-60이던 시절에는 참이었다 — 그런 행이 존재할 수 없었으니까.
0008과 전량 적재가 그걸 **자신 있는 오답**으로 바꿨고, 그건 이 라우트가 존재하는 이유 그 자체다.

**주소 조회는 이 사이트의 1차 경로다.** 상세 페이지만 봤다면 놓쳤을 것이다.

### 왜 "-AL"을 빌려주지 않는가

Census LSAD는 이 여섯을 at-large로 표시하고 로더도 `at_large = true`로 싣는다. 그래서 페이지가
"at-large district"에 손을 뻗은 것이다. 하지만 **at-large 주**는 주 전체를 덮는 지역구 하나에
표결권 있는 의원이 있는 것이고, Delegate 지역구는 그 둘 다 아니다. 쓸 지역구 번호도 없다 —
CD 98은 번호가 아니라 센티널이다. 그래서 라벨은 `DC`, `PR`이다.

### 상원 쿼리를 조건부로 만든 이유

의석이 없는 곳에 `getSittingSenators`를 던져 빈 배열을 받으면, **명부가 안 실린 주와 구별되지 않는다.**
2d의 "빈 셀의 세 가지 의미"와 같은 문제다. 그래서 묻지 않는다.

## 3. 실측 — 실제 페이지

`next start`를 **Neon(정본)**에 붙여 렌더한 결과다.

| 페이지 | 제목/부제 | 하원측 카드 | 상원 | 상원 후보 섹션 |
|---|---|---|---|---|
| `/districts/0611` CA-11 | `CA-11` · California | `HOUSE · CA-11` Pelosi | 2인 | 있음 |
| `/districts/5600` WY-AL | `WY-AL` · **at-large district** | `HOUSE · WY-AL` Hageman | 2인 | 있음 |
| `/districts/1198` DC | `DC` · **Delegate district · non-voting** | `DELEGATE · DC` Norton + 비표결 문구 | **"elects no Senators"** | **없음** |
| `/districts/7298` PR | `PR` · **Resident Commissioner district · non-voting** | `RESIDENT COMMISSIONER · PR` Hernández + 비표결 문구 | **"elects no Senators"** | **없음** |

HTML 단위 대조 — "Senate seats" 섹션은 0611·5600에만, "Every state elects two"는 **어디에도 없고**,
"at-large district"는 5600에만, "Delegate district"는 1198에만, "Resident Commissioner district"는
7298에만, 비표결 문구는 1198·7298에만.

`/districts` 커버리지: "Boundaries are loaded for **all 50 states, the District of Columbia, and the
five territories** that send a Delegate or Resident Commissioner — every district in the Congress."
지도 상태줄 "441 districts drawn."

### 주소 조회 (CDP로 실제 브라우저 구동)

| 입력 | 패널 |
|---|---|
| 1600 Pennsylvania Ave NW, DC | `DELEGATE · DC` / Eleanor Holmes Norton / 비표결 문구 / "District of Columbia is not a state and elects no Senators." |
| 250 Calle San Francisco, PR | `RESIDENT COMMISSIONER · PR` / Pablo José Hernández / 비표결 문구 / "Puerto Rico is not a state…" |
| 1 Marine Corps Dr, GU | `DELEGATE · GU` / James C. Moylan / 비표결 문구 |
| 1 Dr Carlton B Goodlett Pl, CA | `HOUSE · CA-11` / Pelosi + 상원 2인, 비표결 문구 **없음** |

### 실측이 드러낸 상류 한계 1건 (우리 결함 아님)

Census **주소** 지오코더는 여섯 관할구를 고르게 다루지 않는다. 실측:

| 관할구 | 주소 매칭 |
|---|---|
| DC · PR | 1/1 |
| GU | 2건 중 1건 |
| VI · AS · MP | 0/4 |

**좌표 조회는 여섯 곳 전부 정상**이고(2단계 §5), 지도 클릭 경로는 GEOID로 가므로 전부 동작한다.
막히는 것은 VI·AS·MP의 **주소 입력** 경로뿐이고, 그때 나오는 답은 M4에서 고친
`not_found` 문구다 — 정직한 답이다. 이건 상류 커버리지이지 우리 버그가 아니다.

## 4. 테스트

`lib/jurisdiction.test.ts` **15건 신규** — 여섯 문장 하나하나를 회귀로 고정했다.
"Delegate 지역구를 at-large라 부르지 않는다", "DC-AL을 만들지 않는다", "PR은 Delegate가 아니다",
"전량 적재는 complete로, 슬라이스 0은 incomplete로 계산된다", "`cd_number = 98` 센티널과 일치한다".

`route.test.ts`: DC 케이스 1건 → **3건**. 예전 테스트는
"CD 98이면 DB를 묻지 않는다"를 **보증**하고 있었다 — 그때는 맞았고 지금은 그게 결함이다.
지금은 (a) DC 주소가 Norton으로 답하고 `getDistrictByGeoid('1198', 119)`를 실제로 호출하는지,
(b) 상원 의석이 없으면 `getSittingSenators`를 **아예 호출하지 않는지**,
(c) 주에서는 여전히 호출하는지를 고정한다.

`formatDistrictLabel`은 `format.ts`에서 **제거**하고 `jurisdiction.districtLabel`로 옮겼다.
라벨만 따로 가져다 쓰면 그에 딸린 구분을 놓치게 되고, 그게 `DC-AL`이 나온 경위다.

| | |
|---|---|
| lint · typecheck · build | ✅ |
| 테스트 | **71 passed** (5 파일) |

## 5. 그대로 둔 것

- `/districts/[geoid]` 커버리지의 "**FEC candidates are loaded for CA, NC and WY. Other states are
  being added.**" — 이건 아직 **참이다**. FEC 전량(4단계)이 남아 있다. 1번 항목은 경계 카피이고
  이건 후보 카피다.
- `NotLoaded`가 존재하지 않는 GEOID(예: `1197`)를 "실재하는 지역구"라 부르는 문제 —
  전량 적재로 실질적으로 도달 불가능해졌지만 논리는 남아 있다. 이번 6건과 다른 부류라 손대지 않았다.
