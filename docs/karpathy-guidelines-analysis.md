# forrestchang/andrej-karpathy-skills 분석 및 반영 기록

분석 대상: <https://github.com/forrestchang/andrej-karpathy-skills>  
확인 커밋: `2c60614` (`Sync Chinese README with English version (add Cursor section) (#95)`)  
로컬 분석 위치: `/tmp/andrej-karpathy-skills`

## 저장소 구조

- `CLAUDE.md`: 프로젝트에 붙여 넣을 수 있는 단일 행동 지침.
- `skills/karpathy-guidelines/SKILL.md`: 동일 지침을 Claude Code skill로 배포.
- `.claude-plugin/`: 플러그인 메타데이터.
- `.cursor/rules/karpathy-guidelines.mdc`, `CURSOR.md`: Cursor에도 같은 행동 규칙을 적용하는 표면.
- `README.md`, `EXAMPLES.md`: 문제 정의, 원칙 설명, 잘못된 예/좋은 예.

## 핵심 사상

저장소는 “에이전트에게 더 많은 일을 시키는 법”보다 “에이전트가 비싼 실수를 하지 않게 하는 법”에 집중한다. 특히 다음 네 가지 실패 모드를 제어한다.

1. **숨은 가정**: 모호한 요청에서 조용히 해석을 선택하고 질주하는 문제.
2. **과설계**: 아직 필요하지 않은 추상화, 설정, 확장성을 추가하는 문제.
3. **비외과적 diff**: 요청과 무관한 주석/포맷/주변 코드를 바꾸는 문제.
4. **검증 없는 완료**: 성공 기준 없이 구현하고 “작동한다”고 선언하는 문제.

## PaperReviewAgent에 맞춘 해석

PaperReviewAgent는 이미 OMX/OMC 오케스트레이션, 전문 에이전트, QA 검증 루프를 갖고 있다. 따라서 외부 저장소를 그대로 붙여 넣기보다, 기존 체계에 다음 방식으로 흡수했다.

- **AGENTS.md**: Codex/OMX 실행 계약에 “Karpathy-inspired execution guardrails”를 추가해 모든 로컬 작업의 기본 태도로 삼음.
- **.claude/CLAUDE.md**: Claude/OMC 표면에도 동일한 프로젝트 실행 가드레일과 skill 목록을 추가.
- **.claude/agents/*.md**: 각 전문 에이전트가 자기 분야 작업 전후에 같은 네 가지 체크를 수행하도록 공통 섹션 삽입.
- **.claude/skills/karpathy-guidelines/SKILL.md**: 별도 호출 가능한 skill로 만들고, 구현/수정/리뷰/리팩터링 작업에 적용하도록 정리.
- **paper-agent-orchestrator**: 팀 작업의 Phase 1/3/4에 성공 기준, 최소 변경 범위, 검증 게이트를 명시.
- **omc-reference**: skills registry와 실행 원칙에 해당 가드레일을 등록.

## 적용 기준

이 지침은 모든 작업을 느리게 만드는 의도가 아니다. 명백한 오탈자나 단일 라인 수정은 가볍게 적용한다. 반대로 다음 경우에는 강하게 적용한다.

- 사용자의 의도가 모호하거나 두 가지 이상 해석될 때
- 변경이 백엔드↔프론트엔드 계약, 리뷰/검색 품질, 데이터 스키마에 영향을 줄 때
- 리팩터링/cleanup/deslop처럼 동작 보존이 중요한 때
- 에이전트 팀이 병렬로 작업해 범위 확산 위험이 있을 때

## 완료 기준

향후 에이전트/스킬 출력이 다음을 보이면 반영이 성공한 것이다.

- 변경 라인이 사용자 요청 또는 검증에 직접 연결됨.
- “미래 확장성”보다 현재 요구 해결을 우선함.
- 모호한 요구는 질문 또는 명시적 가정으로 드러남.
- 테스트/빌드/정적 분석/교차 비교 등 검증 증거가 최종 보고에 포함됨.
