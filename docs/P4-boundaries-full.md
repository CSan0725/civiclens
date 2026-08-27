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
