# vote.bill_id NULL 원인조사 (2026-08-20, Cowork 코드 실측)

작업 A. `vote.bill_id`가 18,544건 전부 NULL인 원인을 코드 레벨에서 조사한 결과와, CLI가 DB에서 실행할 검증 프롬프트.

## TL;DR

**연결 코드 자체는 정상이다.** House/Senate/backfill 세 경로 모두 `find_bill_id`로 자연키(congress_no, bill_type, number) 매칭을 시도한다. NULL의 원인은 버그가 아니라 **데이터 커버리지 불일치**로 거의 확정:

- `bill` 테이블은 **2017~(115대 이후)만** 수집됨 (`bills` job = Congress.gov, 2017~).
- `vote` 테이블은 **1990~2016 백필 17,433건**(clerk.house.gov)을 포함(`backfill` job).
- 따라서 pre-2017 표결 ~17,433건은 **매칭될 bill 자체가 DB에 없어** 구조적으로 NULL일 수밖에 없음 → 전체 18,544건의 **약 94%**가 여기서 설명됨.

남은 쟁점은 2017+ 표결(약 1,111건 = 18,544 − 17,433, House Congress.gov + Senate XML)이다. 이들은 bill이 DB에 존재하므로 **링크되어야 정상**. 만약 이것들도 전부 NULL이면 별도의 타이밍/실행 문제가 있는 것이고, 그게 진짜 고칠 대상이다.

## 코드 실측 근거 (모두 확인 완료)

1. **House 경로** — `congress_gov_sync.py:387-398`: `houseRollCallVote.legislationType/legislationNumber`를 꺼내 `normalize_bill_type` → `find_bill_id` 호출. 픽스처 `house_vote_detail_119_1_240.json` 확인 결과 API가 `legislationType='HR'`, `legislationNumber='3424'`, `legislationUrl`까지 실제로 제공함. **API 미제공 가설 기각.**
2. **Senate 경로** — `senate_xml_sync.py:120,146`: 동일하게 `_resolve_bill` → `find_bill_id`. 단 Senate 표결은 지명(PN)·조약(TREATYDOC)도 포함하며 `normalize_bill_type`이 이들을 의도적으로 None 반환 → 이 표결들은 **정당하게 NULL**(버그 아님).
3. **Backfill 경로** — `clerk_xml_sync.py:199,225`: 동일 로직. 하지만 대상이 1990-2016이라 bill 부재로 항상 None.
4. **정규화** — `base.py:183`: `BILL_TYPES = {hr, s, hjres, sjres, hconres, sconres, hres, sres}`. 'HR'→'hr' 정상 매핑.
5. **조회 쿼리** — `repository.py:205 find_bill_id`: `bill.congress_no == congress_no AND bill.bill_type == lower AND bill.number == number`. 스키마 컬럼명 일치 확인(`0001_init.sql` bill/vote 모두 `congress_no`, vote에 `bill_id BIGINT REFERENCES bill(id) ON DELETE SET NULL`, `idx_vote_bill` 존재).
6. **Upsert** — `upsert.py:101`: `ON CONFLICT DO UPDATE`가 conflict key 제외 전 컬럼(=`bill_id` 포함)을 excluded로 갱신. 따라서 **votes를 bill 적재 후 재실행하면 bill_id가 채워진다** — 재실행만 하면 소급 복구 가능.

## 유력 원인 (우선순위)

1. **[구조적·예상됨, ~94%] pre-2017 백필 표결에 대응 bill 부재.** 고치려면 (a) 과거 bill 수집(대규모, 비권장) 또는 (b) pre-2017 NULL을 정상 상태로 수용하고 UI에서 "법안 링크는 2017년 이후 표결만 제공" 명시.
2. **[진짜 버그 후보] 2017+ 표결도 전부 NULL이라면** — 최초 적재 시 votes가 bills보다 먼저 실행됐고(순서 의존) 이후 재실행이 없어 NULL 고착. `upsert`는 재실행 시 갱신하므로 **votes job 재실행(2017+ 범위)이면 해결**될 가능성 높음.
3. **[정당한 NULL] Senate 지명·조약 표결**은 bill이 아니므로 영구 NULL(집계에서 제외 대상).

## CLI 실행용 진단 프롬프트 (그대로 복붙)

> docs/vote-bill_id-null-investigation.md 를 읽었다. Neon 접속해서 아래 SQL을 순서대로 실행하고, 각 결과를 표로 보여줘. 절대 데이터 수정은 하지 말 것(SELECT only). 결과를 바탕으로 원인 2(2017+ 표결도 NULL인지)를 확정/기각해줘.

```sql
-- 1) 전체 vote 건수와 bill_id NULL 비율, 시대 구분
SELECT
  CASE WHEN congress_no >= 115 THEN '2017+ (>=115)' ELSE 'pre-2017 (<115)' END AS era,
  chamber,
  count(*)                                        AS votes,
  count(bill_id)                                  AS linked,
  count(*) - count(bill_id)                       AS null_bill
FROM vote
GROUP BY 1, 2
ORDER BY 1, 2;

-- 2) bill 테이블의 congress 범위 (2017+ 만 있는지 확인)
SELECT min(congress_no) AS min_c, max(congress_no) AS max_c, count(*) AS bills
FROM bill;

-- 3) 2017+ House 표결 중, "실제로 매칭 가능한 bill이 DB에 있는데도" NULL인 건이 있나?
--    (있으면 = 원인 2 = 재실행으로 복구 가능한 진짜 버그)
SELECT count(*) AS resolvable_but_null
FROM vote v
JOIN bill b
  ON b.congress_no = v.congress_no
 -- NOTE: vote에는 bill_type/number 원본이 없으므로 이 조인은 근사치가 아님.
 -- 대신 아래 4)로 대체 검증한다.
WHERE FALSE;

-- 4) 원인 2 확정용: 2017+ 표결 중 bill_id NULL 건수만 우선 확인.
--    이 값이 0에 가까우면 링크 정상, 크면 재실행 필요.
SELECT congress_no, chamber, count(*) AS votes, count(*) FILTER (WHERE bill_id IS NULL) AS null_bill
FROM vote
WHERE congress_no >= 115
GROUP BY congress_no, chamber
ORDER BY congress_no, chamber;
```

> 만약 4)에서 2017+ 표결도 NULL이 많으면: `votes` job을 2017+ 범위로 재실행(bills job이 먼저 성공한 상태에서)했을 때 bill_id가 채워지는지, 표결 1건을 골라 재fetch→upsert 후 SELECT로 확인해줘. upsert는 ON CONFLICT DO UPDATE라 재실행만으로 소급 갱신돼야 한다(upsert.py:101 근거).

## 권장 결론/다음 액션

- **먼저 위 SQL 1·2·4만 돌려서** "2017+ 표결이 링크되고 있는가"를 확정. 이게 갈림길.
  - **2017+가 잘 링크됨** → pre-2017 NULL은 정상. 코드 수정 불필요. UI/카피만 "법안 연결은 2017년 이후 표결 제공"으로 조정하고 백로그 종료. (P4로 진행)
  - **2017+도 NULL** → `votes` job 2017+ 재실행으로 소급 복구(스키마·코드 변경 불필요). 복구 후 재검증.
- pre-2017 bill 소급 수집은 대규모 작업이라 비권장. 수익화/P4 우선순위와 무관하므로 백로그 유지.

## 열린 질문 (사용자/CLI 확인 필요)

- 18,544라는 수치의 출처·측정 시점? (백필 17,433 + 2017+ ≈ 1,100 → 합이 대략 맞음. 재확인 권장.)
- `is_published=false` 표결은 UI 노출 안 되므로, 실제 사용자에게 보이는 표결 중 bill_id NULL 비율이 더 중요. SQL에 `WHERE is_published` 필터 버전도 함께 확인 권장.

---

## 검증 결과 (CLI, DB 실측 — 2026-08-20)

Neon 라이브 DB에 `BEGIN; SET TRANSACTION READ ONLY;`로 접속해 실행(`transaction_read_only = on` 확인, 전부 ROLLBACK). 쓰기 없음.

### 실측 표

**1) 시대·chamber별 링크 현황**

| era | chamber | votes | linked | null_bill |
|---|---|---:|---:|---:|
| 2017+ (≥115) | house | 645 | **0** | 645 |
| 2017+ (≥115) | senate | 466 | **0** | 466 |
| pre-2017 (<115) | house | 17,433 | **0** | 17,433 |

**2) `bill` 테이블 범위** — `min_c = max_c = 119`, **150행**.

**3) 2017+ 표결** — 115~118대 표결은 **존재하지 않는다**. "2017+"는 전부 119대(house 645 + senate 466)이고 전건 NULL.

**4) 공개(is_published) 표결만** — 2017+ 1,111건 전건 NULL / pre-2017 17,186건 전건 NULL.

### 이 문서의 '타이밍/순서' 가설은 **기각**

이 문서 §"유력 원인" 2번(votes가 bills보다 먼저 실행돼 NULL 고착 → votes job 재실행으로 소급 복구)은 **성립하지 않는다.**
판정 기준이었던 "2017+도 NULL이 많은가"는 문자 그대로는 참이지만, 그 기준이 전제한
"`bill` 테이블은 2017~를 덮는다"가 **틀렸다.** 실제 `bill`은 119대 150행뿐이다.
그래서 "0 linked"만으로는 버그인지 연결할 대상이 없는 것인지 구분되지 않아, 아래 두 검증을 추가했다.

**상원 (vote_type 텍스트에 법안 참조가 남아 DB만으로 판정 가능)**

| Senate 119 votes | 법안을 지목 | 지명·조약(정당한 NULL) | 지목된 distinct 법안 | 그중 `bill`에 보유 |
|---:|---:|---:|---:|---:|
| 466 | 179 | 229 | 75 | **0** |

**하원 (`vote`에 법안 참조를 저장하지 않으므로 Congress.gov API에 직접 질의)**
통과·suspension 계열 롤콜 14건 표본:

| API가 법안을 반환 | 그 법안을 `bill`에 보유 | 보유했는데 NULL인 건 |
|---:|---:|---:|
| **14 / 14** | **0** | **0** |

API는 `legislationType`/`legislationNumber`를 항상 반환한다(HR 29, HR 23, HR 504, HR 192 …).
`find_bill_id`는 정상 입력을 받아 정상적으로 `None`을 반환하고 있다 — 그 법안들이 테이블에 없기 때문이다.
**votes job을 재실행해도 NULL 1,111건이 NULL 1,111건으로 다시 쓰일 뿐이다.**

### 확정된 근본 원인 — `bill` 수집이 `--limit` 걸린 150행 샘플

`fetch_bills`(`congress_gov.py:127`)는 `/bill/119`를 **`sort=updateDate desc`**로 페이징한다.
따라서 150행은 **"가장 최근에 갱신된 순" 표본**이지 표결이 붙은 법안이 아니다.
수집된 범위는 `hr` 2550–9750, `s` 83–4939로 흩어져 있고, 2025년 1월 롤콜의 대상인
HR 23·28·29·131·152 …는 그 창에 들어온 적이 없다. 150건 중 롤콜을 시사하는 액션
(`yeas and nays` / `passed house` 등)을 가진 것은 **6건**뿐이다.

즉 이 문서의 원인 1(pre-2017 커버리지)도 절반만 맞다. pre-2017 17,433건은 그 설명이 맞지만,
119대 1,111건까지 NULL인 진짜 이유는 **119대 법안 카탈로그 자체가 0.8%(150/18,396)만 적재된 것**이다.

### 정당한 영구 NULL

상원 지명(PN)·조약 표결 **229건**(119대 상원 466건 중)은 대응 법안이 없다.
향후 "링크율" 지표를 만들 때 분모에서 제외해야 한다.

---

## 백필 완료 결과 (2026-08-21)

### 실행 요약

| | |
|---|---|
| 실행 | `bills --congress 119` (`--limit` 없음), 로컬 detached |
| 기간 | 2026-08-20 21:16:54Z → 2026-08-21 11:45:07Z (**14h 28m**) |
| 런 횟수 | 3회 (업스트림 데이터 결함으로 2회 크래시 → 픽스 후 재개) |
| 최종 정산 | discovered 18,396 = collected 9,426 + skipped 8,970 ✅ |
| 처리율 | 약 1,300 bills/hr (API 한도 20,000/hr 대비 5,400 req/hr, 한도 무관) |

### 카탈로그 (before → after)

| 테이블 | 이전 | 이후 |
|---|---:|---:|
| `bill` (119대) | 150 (0.8%) | **18,396 (100%)** |
| `bill_action` | 486 | **74,391** |
| `sponsorship` | 1,458 | **189,661** |
| 법률로 성립(`became_law`) | 14 | **104** |

### 링크율 (하원 로컬 `--refresh` + 상원 Actions `--refresh` 이후)

| chamber | 표결 | 링크됨 | NULL | 링크율(지명·조약 제외 분모) |
|---|---:|---:|---:|---:|
| house | 645 | **638** | 7 | **98.9%** (638/645) — 링크 가능분 기준 **638/638 = 100%** |
| senate | 831 | **430** | 401 | **100.0%** (430/430, 지명·조약 401건 분모 제외) |

**양원 모두 링크 가능한 표결은 전건 링크됐다.** 남은 NULL 408건(하원 7 + 상원 401)은 전부
법안이 존재하지 않는 표결이다 — 하원은 정족수 호명·의장선출·산회동의, 상원은 지명·조약.

`is_published` 실측: 하원 645건 전부 공개, 상원 **829건 공개 / 2건 미공개**.
그 2건은 open reconciliation flag가 걸려 있어 **FC-3대로 정당하게 보류된 것**이다(반증된 집계는 노출하지 않는다).
119대 전체 open flag는 6건(상원)이며, 공개를 막는 것은 `yea_count`/`nay_count` 불일치뿐이므로 플래그 수와 미공개 수는 일치하지 않는다.

**이 재수집에서 `is_published` 사고는 재발하지 않았다.** `540ec6a` 이전이었다면 상원 831건이 전부
`is_published=false`로 뒤집혀 사이트에서 사라졌을 것이다(하원 645건에 실제로 일어났던 일). 파서가
이 컬럼을 더 이상 쓰지 않으므로 재수집이 reconciliation 판정을 덮지 않는다 — 실측으로 확인됨.

상원 수치는 GitHub Actions `collect-daily` #10(`chamber=senate, vote_limit=600, refresh_votes=true`,
2026-08-21 18:20Z, green) 실행 후 측정. 이 런은 재링크뿐 아니라 상원 표결 315건을 추가 수집했다(516 → 831).

**하원 미링크 7건은 전부 구조적으로 법안이 없는 표결**이며 수집 누락이 아니다:

| roll | question | vote_type |
|---|---|---|
| 119/1/1 | Call by States | Quorum |
| 119/1/2 | Election of the Speaker | Yea-and-Nay |
| 119/1/138, 169, 178 · 119/2/106 | On Motion to Adjourn | — |
| 119/2/1 | Call of the House | Quorum |

즉 **하원은 링크 가능한 표결 638건 중 638건, 실질 100%**다.

### 상원 수정안 표결 161건 — 원인 규명 후 전건 복구 (2026-08-21)

1차 측정에서 상원은 269/430(62.6%)이었고, 미링크 161건이 **전부 수정안(amendment) 표결**이었다.
`amendment_number`가 NOT NULL이면 100% 미링크, NULL이면 100% 링크로 정확히 갈렸다.

**원인은 추측하지 않고 실측했다.** senate.gov가 개발 네트워크에서 403이라(샌드박스 해제·WebFetch 모두 동일)
`verify-senate-live` 워크플로에 `roll_number` 입력과 원본 XML 아티팩트 업로드를 추가해(`7d254b0`)
실제 페이로드 2건을 러너에서 받아왔다. 결과, **가설 2개가 모두 절반씩 틀렸다**:

```xml
<!-- 119/1/64 "On the Amendment S.Amdt. 473 to S.Con.Res. 7" -->
<document>
  <document_type>S.Amdt.</document_type>   <!-- 채워져 있다. 단 수정안 자신을 가리킨다 -->
  <document_number/>                        <!-- 비어 있다 -->
</document>
<amendment>
  <amendment_number>S.Amdt. 473</amendment_number>
  <amendment_to_document_number>S.Con.Res. 7</amendment_to_document_number>
</amendment>
```

- `<document>`는 **비어 있지 않다.** 수정안 표결에서 그것은 모법안이 아니라 **수정안 자체**를 기술한다.
  `normalize_bill_type("S.Amdt.")`가 None을 반환하는 것은 정상 동작이고, number는 비어 있어 링크 실패.
- 모법안은 `<amendment_to_document_number>`에 **"S.Con.Res. 7" 형태의 완전한 인용**으로 들어 있다.
  **type 필드는 요소 어디에도 없다** — 그래서 픽스는 태그를 하나 더 읽는 게 아니라 인용문을 분해하는 방식이다.
  분해한 type은 기존 `normalize_bill_type`이 그대로 처리하므로 `_resolve_bill`은 무수정 재사용.

**픽스(`6eed6fb`) 후 재백필 결과 — 161건 전건 복구:**

| | 링크됨 | 미링크 |
|---|---:|---:|
| 수정안 표결(`amendment_number` NOT NULL) | **161** | **0** |
| 그 외(지명·조약 401 포함) | 269 | 401 |

상원 미링크 401건은 **전부 지명·조약**임을 재확인했다(`is_nomination` 기준 401/401).

> **정정.** 이 문서는 앞서 "예산 point of order·302/313 waiver 약 50건은 모법안이 없어 구조적 NULL"이라고
> 적었는데 **틀렸다.** 실측한 119/1/185가 바로 그 부류인데
> `amendment_to_document_number = H.Con.Res. 14`를 갖고 있다. S.Amdt. 1690 → S.Amdt. 1717 → H.Con.Res. 14의
> 2차 수정안이고, 최종 모법안으로 해석되는 것이 옳다(그 롤콜은 H.Con.Res. 14 페이지에 속한다).
> `vote_question_text`에 모법안이 안 보인다는 이유로 구조적이라고 판단한 것이 오류였고,
> 그래서 예상 복구치를 111건으로 낮게 잡았다. 실제는 161건 전부다.

**FC-3 회귀 없음.** 재수집 후에도 하원 645건 공개, 상원 829건 공개 / 2건 미공개(open flag 보유)로 유지됐다.

### 실행 중 발견·수정한 코드 결함 4건

이 백필은 "데이터만 채우는 작업"이 아니었다. 전부 18,396건을 처음으로 훑으면서 드러난 것들:

1. **`eb0cb3c`** — Congress.gov가 동일 액션을 2번 반환(119/hres/1377). `ON CONFLICT DO UPDATE`가 한 문장에서 같은 키를 두 번 받으면 거부 → bill 단위 실패. `bulk_upsert`의 중복 가드는 `conflict_columns` 경로에만 걸려 있어 표현식 인덱스를 쓰는 `bill_action`은 통과했다.
2. **`3e1e038` + `4204b2e`** — 동일 의원이 한 법안에 cosponsor로 2번 등장(철회 후 재공동발의). 실측: 119/s/1383 Warnock — 2025-07-10 발의/2025-07-14 철회, 2025-09-18 발의/2026-02-25 철회. 최신 에피소드를 **날짜 기준**으로 선택(페이로드 순서 아님).
3. **`e1202c6`** — **"bills 먼저, votes 재실행하면 upsert가 bill_id를 소급 채운다"는 전제가 틀렸다.** `sync_house_votes`/`sync_senate_votes`는 `skip_existing=True`가 기본이라 이미 저장된 표결을 **fetch 전에 제외**한다. upsert 자체가 실행되지 않으므로 몇 번 재실행해도 NULL 그대로. `--refresh`가 이미 존재했지만 backfill 잡에만 배선돼 있었다 → votes에도 배선.
4. **`540ec6a`** — **재수집이 119대 하원 645건 전부를 `is_published=false`로 만들어 사이트에서 숨겼다.** 반증 플래그는 0건. 원인: `parse_house_vote_detail`/senate 파서가 아직 0004 이전 규칙(`is_published: False`)을 쓰고 있었다. 0004는 데이터와 DEFAULT는 고쳤지만 파서는 안 고쳤고, 수집기가 컬럼을 명시하니 DEFAULT가 적용되지 않고 매 재수집마다 reconciliation 판정을 덮어썼다. clerk 파서의 `True`도 같은 버그의 반대 방향(반증된 표결을 재공개). **세 파서 모두 이 컬럼을 쓰지 않도록** 변경 — insert는 DEFAULT true, update는 미변경. 645건은 open flag 없는 행만 골라 재공개 완료.

4번은 `test_house_vote_starts_unpublished`가 0004 이전 정책을 테스트로 고정해두고 몇 달간 통과하고 있었다는 뜻이기도 하다.

### 남은 후속

- ~~상원 `--refresh` 디스패치~~ → ✅ 완료(Actions #10). 링크율 62.6% 측정.
- ~~상원 수정안 표결 161건 링크~~ → ✅ 완료(`6eed6fb`). 161/161 복구, 상원 링크율 100%.
- **daily job `BILL_LIMIT=150`** — 그대로 두면 카탈로그가 다시 드리프트한다. skip 덕에 재fetch가 값싸졌으므로 상향 또는 `--since` 배선 검토.
