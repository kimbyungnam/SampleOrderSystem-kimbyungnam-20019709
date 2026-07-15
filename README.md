# S-Semi 반도체 시료 생산주문관리 시스템

시료(Sample) 등록, 주문 접수/승인/거절, 생산 진행, 출고까지를 관리하는 콘솔 기반 단일 프로세스 애플리케이션입니다. 도메인 규칙과 설계는 `PRD.md`, `DESIGN.md`를 참고하세요.

## 요구 사항

- Python 3.14+

## 설치

```bash
pip install -e ".[dev,test]"
```

- `dev` extra: `ruff`, `commitizen`, `basedpyright`, 그리고 테스트용 `dummydatagen`(더미 데이터 생성기)/`datamonitor`(DB 조회 도구)
- `test` extra: `pytest`, `pytest-mock`

## 실행

```bash
python -m semi.cli.app
```

실행 시 `semi.db`(SQLite, WAL 모드)를 초기화하고, 메뉴 루프(메인 스레드)와 생산 진행을 1초마다 갱신하는 백그라운드 워커(데몬 스레드)를 함께 시작합니다. 콘솔 메뉴를 통해 시료 등록, 주문 접수/승인/거절, 생산 현황 조회, 출고를 진행할 수 있습니다.

## 개발

```bash
ruff check --fix .            # lint
ruff check --select I --fix . # import 정렬
ruff format .                  # format
pytest                        # 전체 테스트 실행
pytest tests/path/to/test_file.py::test_name  # 단일 테스트 실행
```

커밋 메시지는 Conventional Commits 형식을 따릅니다 (`cz commit`으로 대화식 작성 가능).

## 참고 문서

- `PRD.md` — 요구사항 정의
- `DESIGN.md` — 시스템 설계, 패키지 구조, DB 스키마, 핵심 흐름
- `CLAUDE.md` — Claude Code용 저장소 가이드
