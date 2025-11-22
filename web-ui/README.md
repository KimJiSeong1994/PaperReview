# Paper Review Agent - React UI

Connected Papers 스타일의 인터랙티브 논문 그래프 웹 인터페이스

## 개발 서버 실행

### 1. 백엔드 서버 실행 (FastAPI)

프로젝트 루트 디렉토리에서:

```bash
cd /Users/gimjiseong/git/PaperReviewAgent
source .venv/bin/activate
python api_server.py
```

백엔드는 `http://localhost:8000`에서 실행됩니다.

### 2. 프론트엔드 개발 서버 실행 (React + Vite)

`web-ui` 디렉토리에서:

```bash
cd web-ui
npm install  # 처음 한 번만 실행
npm run dev
```

프론트엔드는 `http://localhost:5173`에서 실행됩니다.

## 기능

- **논문 검색**: arXiv, Connected Papers, Google Scholar에서 논문 검색
- **인터랙티브 그래프**: 논문 간 관계를 시각화하는 그래프 뷰
- **논문 목록**: 검색된 논문을 좌측 패널에서 확인
- **상세 정보**: 선택한 논문의 상세 정보를 우측 패널에서 확인
- **Connected Papers 스타일**: Connected Papers와 유사한 UI/UX 디자인

## 기술 스택

- **Frontend**: React 19, TypeScript, Vite
- **Visualization**: Plotly.js
- **Backend**: FastAPI (Python)
- **Styling**: CSS3 (Connected Papers 스타일)

## 프로젝트 구조

```
web-ui/
├── src/
│   ├── components/
│   │   ├── SearchBar.tsx       # 검색 바 컴포넌트
│   │   ├── PaperList.tsx       # 논문 목록 컴포넌트
│   │   ├── GraphView.tsx       # 그래프 시각화 컴포넌트
│   │   └── DetailPanel.tsx     # 상세 정보 패널
│   ├── api/
│   │   └── client.ts           # API 클라이언트
│   ├── types.ts                # TypeScript 타입 정의
│   ├── App.tsx                 # 메인 앱 컴포넌트
│   └── index.css               # 글로벌 스타일
└── package.json
```
