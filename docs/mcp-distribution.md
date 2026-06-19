# 집현전 MCP 서버 배포 가이드

집현전 MCP 서버(`jiphyeonjeon-agent`, 로컬 **stdio** / Python, `JIPHYEONJEON_TOKEN`으로 백엔드 프록시)를
Claude Desktop·Claude Code·Cursor 사용자가 발견·설치하게 만드는 절차.

> ⚠️ 산출물(`server.json`, README 토큰)은 **MCP 서버 레포(`jiphyeonjeon-agent`)** 에 들어갑니다(이 PaperReviewAgent 레포 아님).
> 게시(PyPI/Registry)는 **메인테이너의 PyPI·GitHub 계정**이 필요해 에이전트가 대신 실행할 수 없습니다 — 아래 명령을 직접 실행하세요.

## 핵심 판단
- **`.well-known/mcp.json` 은 만들지 않습니다.** 이는 아직 병합 안 된 초안(SEP-1649/2127)이며 **원격 HTTP MCP 서버 전용**입니다. 집현전 MCP는 로컬 stdio라 해당 없음(서빙할 HTTP 엔드포인트가 없고, 클라이언트도 stdio 서버엔 이걸 조회하지 않음).
- **진짜 채널 = PyPI 게시 → 공식 MCP Registry 등록 → 디렉터리/awesome 리스트.**
- 원격 HTTP(Streamable HTTP) 엔드포인트를 추가하면 그때 `.well-known` 논의가 의미 있음 — 단 무설치 SaaS가 목표일 때만. 현재는 stdio+Registry가 정답.

## 레버리지 순 체크리스트
| 순위 | 작업 | 필요 계정 |
|---|---|---|
| 1 | **PyPI 게시** (`jiphyeonjeon-agent`) — 나머지의 전제 | PyPI |
| 2 | **MCP Registry 등록** (`mcp-publisher`) | GitHub + PyPI |
| 3 | **awesome-mcp-servers PR** (punkpeye/awesome-mcp-servers 등) | GitHub |
| 4 | **Glama·Smithery·PulseMCP** 자동 인덱싱 + 소유권 claim | GitHub |
| 5 | **README 설치 안내** (`uvx` + `claude mcp add`) | — |

## 1) `server.json` (jiphyeonjeon-agent 레포 루트에 배치)
> 스키마: `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json`
> ‼️ 확인 필요: `name`의 GitHub 사용자명, PyPI 패키지명, 버전, repo URL.

```json
{
  "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
  "name": "io.github.KimJiSeong1994/jiphyeonjeon-agent",
  "title": "집현전 (Jiphyeonjeon)",
  "description": "AI 논문 검색·딥리뷰·북마크·커리큘럼·인용 그래프·figure 생성을 제공하는 연구 도구. jiphyeonjeon.kr 백엔드 API에 인증 연결.",
  "version": "0.1.3",
  "repository": { "url": "https://github.com/KimJiSeong1994/jiphyeonjeon-agent", "source": "github" },
  "packages": [
    {
      "registryType": "pypi",
      "identifier": "jiphyeonjeon-agent",
      "version": "0.1.3",
      "runtimeHint": "uvx",
      "transport": { "type": "stdio" },
      "environmentVariables": [
        { "name": "JIPHYEONJEON_TOKEN", "description": "jiphyeonjeon.kr에서 발급한 JWT", "isRequired": true, "isSecret": true }
      ]
    }
  ]
}
```

## 2) PyPI 소유권 검증 토큰 (README.md에 1줄)
Registry는 PyPI 패키지 설명(README)에서 아래 문자열로 소유권을 확인합니다(HTML 주석 가능):
```html
<!-- mcp-name: io.github.KimJiSeong1994/jiphyeonjeon-agent -->
```

## 3) 게시 명령 (메인테이너가 직접 실행)
```bash
# (0) jiphyeonjeon-agent 레포에서 pyproject.toml에 [project.scripts] 엔트리포인트 확인
# (1) PyPI 게시 (전제)
uv build && uv publish            # 또는 twine upload dist/*
# (2) publisher CLI
brew install mcp-publisher        # 또는 GitHub releases 바이너리
# (3) GitHub 인증 (device flow)
mcp-publisher login github
# (4) server.json 생성/편집 (위 내용)
mcp-publisher init
# (5) 게시
mcp-publisher publish
# (6) 확인
curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=jiphyeonjeon-agent"
```
> 네임스페이스 규칙: GitHub 인증 시 `name`은 반드시 `io.github.<본인-github-id>/...` 로 시작. 커스텀 도메인(`kr.jiphyeonjeon/...`)을 쓰려면 DNS/HTTP 검증 필요.

## 4) 등록 후 사용자 설치 (README에 안내)
```bash
claude mcp add --name jiphyeonjeon io.github.KimJiSeong1994/jiphyeonjeon-agent \
  --env JIPHYEONJEON_TOKEN=<발급받은_토큰>
# 또는 직접: uvx jiphyeonjeon-agent  (env JIPHYEONJEON_TOKEN 설정)
```

## 5) 디렉터리/리스트 (GitHub만 있으면 됨)
- awesome-mcp-servers PR: punkpeye/awesome-mcp-servers, modelcontextprotocol/servers
- Glama(glama.ai) / Smithery / PulseMCP / mcp.so — GitHub 공개 시 자동 인덱싱되며, 로그인해 소유권 claim 권장

## 참고 (현행 표준, 2026)
- MCP Registry Quickstart / Package Types: modelcontextprotocol.io/registry
- server.json 스키마: static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json
- `.well-known` 제안(미병합): MCP SEP-1649 / PR-2127 (HTTP 서버 한정)
