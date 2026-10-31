# 블로그 콘텐츠 저장소 동기화 운영 가이드

콘텐츠 정본은 `KimJiSeong1994/jiphyeonjeon-content`(비공개)에 있고, 앱은 그 체크아웃을 `BLOG_CONTENT_DIR` 로 읽는다. 발행은 콘텐츠 저장소 PR 로만 한다. 코드 저장소의 `data/blog` 는 개발 기본값이자 전환기 폴백이다.

## 흐름

1. 콘텐츠 저장소 `main` 에 `posts/`·`figures/` 변경이 푸시된다.
2. 콘텐츠 저장소의 `notify-app` 워크플로가 PaperReview 에 `repository_dispatch`(`content-updated`)를 보낸다.
3. PaperReview 의 `content-sync` 워크플로가 서버에 SSH 로 들어가 `scripts/sync_blog_content.py` 를 실행한다: `git pull --ff-only` → `scripts/build_posts_index.py --out posts.json` → 검증 → `/api/blog/posts` 확인.
4. 앱은 요청마다 `posts.json` 을 읽으므로 재시작 없이 새 콘텐츠가 서빙된다.

## 서버 1회 설정

```bash
# 1) 비공개 콘텐츠 저장소용 deploy key (읽기 전용)
ssh-keygen -t ed25519 -f ~/.ssh/jiphyeonjeon-content -N "" -C "ec2 content sync"
#    → 공개키를 콘텐츠 저장소 Settings > Deploy keys 에 등록
cat >> ~/.ssh/config <<'CFG'
Host github-content
  HostName github.com
  IdentityFile ~/.ssh/jiphyeonjeon-content
  IdentitiesOnly yes
CFG

# 2) 체크아웃 + 첫 인덱스
git clone git@github-content:KimJiSeong1994/jiphyeonjeon-content.git ~/jiphyeonjeon-content
~/PaperReviewAgent/venv/bin/python ~/PaperReviewAgent/scripts/sync_blog_content.py --content-dir ~/jiphyeonjeon-content

# 3) 서비스가 그 경로를 읽도록 ($APP_ROOT/.env 는 시작 시 load_dotenv 로 읽힌다)
echo "BLOG_CONTENT_DIR=$HOME/jiphyeonjeon-content" >> ~/PaperReviewAgent/.env
sudo systemctl restart paperreview
curl -fsS "http://127.0.0.1:8000/api/blog/posts?limit=1"
```

## GitHub 설정

- 콘텐츠 저장소 secret `CONTENT_DISPATCH_TOKEN`: PaperReview 에 "Contents: read & write" 권한이 있는 fine-grained PAT (repository_dispatch 에 필요).
- PaperReview 의 `content-sync` 워크플로는 기존 배포 secret(`EC2_SSH_KEY`, `EC2_HOST`, `EC2_USER`)과 `production` environment 를 그대로 쓴다.

## 전환기 규칙

- 관리자 발행 API(`POST /api/blog/posts`)는 `BLOG_CONTENT_DIR` 의 `posts.json` 에 쓰지만, 그 파일은 다음 동기화에서 다시 생성되므로 **운영에서는 쓰지 않는다.** 발행은 콘텐츠 저장소에서.
- 롤백: `BLOG_CONTENT_DIR` 를 비우고 재시작하면 `data/blog` 로 돌아간다.
- `data/blog` 삭제와 CI `content` 경로 필터는 서버 전환이 안정된 뒤 별도 PR 로 한다(`.omc/plans/content-separation-plan.md` Phase 0·1).
