"""인스타그램 게시 (Instagram API, 비즈니스·크리에이터 계정).

인스타그램 API는 파일을 직접 받지 않고 "공개 URL"에서 이미지를 가져간다.
그래서 카드 이미지를 이 저장소의 별도 브랜치(insta-media)에 올리고 raw URL을 넘긴다.

필요한 값 (GitHub Secrets):
- INSTAGRAM_ACCESS_TOKEN: 인스타 토큰. "Instagram 로그인" 토큰은 graph.instagram.com,
  비즈니스 포트폴리오(통합 로그인·시스템 사용자)나 "Facebook 로그인" 토큰은 graph.facebook.com에서 받는다.
  INSTAGRAM_GRAPH_HOST를 비우면 두 곳을 차례로 시험해 맞는 곳을 쓴다.
- INSTAGRAM_USER_ID: 인스타 계정 ID (graph.instagram.com이면 비워도 토큰으로 조회)
"""

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request


GRAPH_HOSTS = ("graph.instagram.com", "graph.facebook.com")
GRAPH_VERSION = os.environ.get("INSTAGRAM_GRAPH_VERSION") or "v24.0"
MEDIA_BRANCH = os.environ.get("INSTA_MEDIA_BRANCH") or "insta-media"

# 카드뉴스(캐러셀)는 최대 10장
MAX_CAROUSEL = 10


class InstagramError(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code

    @property
    def token_expired(self):
        # 190: 토큰 만료·무효
        return self.code == 190


def _request(method, url, params=None, headers=None, body=None, timeout=60):
    if params:
        encoded = urllib.parse.urlencode(params)

        if method == "GET":
            url = f"{url}?{encoded}"
        else:
            body = encoded.encode()
            headers = {**(headers or {}), "Content-Type": "application/x-www-form-urlencoded"}

    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8", errors="ignore")

        try:
            detail = json.loads(text).get("error") or {}
        except json.JSONDecodeError:
            detail = {"message": text}

        raise InstagramError(
            f"{error.code} {detail.get('message') or text}"[:500],
            code=detail.get("code") if isinstance(detail, dict) else None,
        ) from None


# ---------------------------------------------------------------------------
# 이미지 올려두기: 저장소의 insta-media 브랜치 → raw URL
# ---------------------------------------------------------------------------

def _github(method, path, payload=None):
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")

    if not token or not repo:
        raise RuntimeError("GITHUB_TOKEN·GITHUB_REPOSITORY가 없습니다 (GitHub Actions에서 실행하세요).")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "insta-gony-bot",
    }
    body = None

    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/{path}", data=body, method=method, headers=headers
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def _ensure_media_branch():
    try:
        _github("GET", f"git/ref/heads/{MEDIA_BRANCH}")
        return
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise

    main = _github("GET", "git/ref/heads/main")
    _github("POST", "git/refs", {"ref": f"refs/heads/{MEDIA_BRANCH}", "sha": main["object"]["sha"]})


def host_images(paths, folder):
    """이미지를 insta-media 브랜치의 folder/ 아래에 올리고 공개 URL 목록을 돌려준다."""
    _ensure_media_branch()
    repo = os.environ["GITHUB_REPOSITORY"]
    urls = []

    for path in paths:
        name = f"{folder}/{os.path.basename(path)}"

        with open(path, "rb") as file:
            content = base64.b64encode(file.read()).decode()

        payload = {"message": f"insta media: {name}", "content": content, "branch": MEDIA_BRANCH}

        try:
            existing = _github("GET", f"contents/{urllib.parse.quote(name)}?ref={MEDIA_BRANCH}")
            payload["sha"] = existing["sha"]
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise

        result = _github("PUT", f"contents/{urllib.parse.quote(name)}", payload)
        # 브랜치 이름 대신 커밋 해시로 가리키면 raw 캐시가 옛 파일을 주는 일이 없다.
        sha = result["commit"]["sha"]
        urls.append(f"https://raw.githubusercontent.com/{repo}/{sha}/{urllib.parse.quote(name)}")

    for url in urls:
        _wait_public(url)

    return urls


def _wait_public(url, attempts=10):
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30) as response:
                if response.status == 200:
                    return
        except urllib.error.HTTPError:
            pass

        time.sleep(3)

    raise RuntimeError(f"이미지 URL이 열리지 않습니다: {url}")


# ---------------------------------------------------------------------------
# 게시
# ---------------------------------------------------------------------------

def _token():
    token = (os.environ.get("INSTAGRAM_ACCESS_TOKEN") or "").strip()

    if not token:
        raise RuntimeError("INSTAGRAM_ACCESS_TOKEN이 없습니다.")

    return token


_account = None


def _call(host, method, path, params=None):
    return _request(
        method,
        f"https://{host}/{GRAPH_VERSION}/{path}",
        params={**(params or {}), "access_token": _token()},
    )


def _lookup(host, user_id):
    if user_id:
        info = _call(host, "GET", user_id, {"fields": "username"})
        return {"id": user_id, "username": info.get("username"), "host": host}

    if host != "graph.instagram.com":
        raise RuntimeError(f"{host} 토큰은 INSTAGRAM_USER_ID(인스타 비즈니스 계정 ID)를 넣어 주세요.")

    info = _call(host, "GET", "me", {"fields": "user_id,username"})
    return {"id": info.get("user_id") or info["id"], "username": info.get("username"), "host": host}


def account():
    """토큰이 가리키는 인스타 계정: {"id", "username", "host"}. 맞는 API 주소도 여기서 정한다."""
    global _account

    if _account:
        return _account

    user_id = (os.environ.get("INSTAGRAM_USER_ID") or "").strip()
    configured = (os.environ.get("INSTAGRAM_GRAPH_HOST") or "").strip()
    errors = []

    for host in [configured] if configured else GRAPH_HOSTS:
        try:
            _account = _lookup(host, user_id)
            return _account
        except (InstagramError, RuntimeError) as error:
            errors.append((host, error))

    if len(errors) == 1:
        raise errors[0][1]

    # 토큰이 어느 쪽에서도 안 되면, 만료 여부는 마지막 오류 코드로 알린다.
    detail = " / ".join(f"{host}: {error}" for host, error in errors)
    raise InstagramError(f"토큰으로 인스타 계정을 찾지 못했습니다 ({detail})", code=getattr(errors[-1][1], "code", None))


def _api(method, path, params=None):
    return _call(account()["host"], method, path, params)


def _wait_ready(container_id, attempts=30):
    for _ in range(attempts):
        status = _api("GET", container_id, {"fields": "status_code"}).get("status_code")

        if status == "FINISHED":
            return

        if status in ("ERROR", "EXPIRED"):
            raise InstagramError(f"미디어 처리 실패: {container_id} {status}")

        time.sleep(3)

    raise InstagramError(f"미디어 처리가 끝나지 않습니다: {container_id}")


def publish_images(image_urls, caption):
    """이미지 1장이면 단일 게시물, 2~10장이면 캐러셀로 올린다. 돌려주는 값: {"id", "permalink"}."""
    if not 1 <= len(image_urls) <= MAX_CAROUSEL:
        raise ValueError(f"이미지는 1~{MAX_CAROUSEL}장이어야 합니다: {len(image_urls)}")

    user_id = account()["id"]

    if len(image_urls) == 1:
        container = _api("POST", f"{user_id}/media", {"image_url": image_urls[0], "caption": caption})["id"]
    else:
        children = []

        for url in image_urls:
            child = _api("POST", f"{user_id}/media", {"image_url": url, "is_carousel_item": "true"})["id"]
            children.append(child)

        for child in children:
            _wait_ready(child)

        container = _api(
            "POST",
            f"{user_id}/media",
            {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption},
        )["id"]

    _wait_ready(container)
    media_id = _api("POST", f"{user_id}/media_publish", {"creation_id": container})["id"]

    try:
        permalink = _api("GET", media_id, {"fields": "permalink"}).get("permalink")
    except InstagramError:
        permalink = None

    return {"id": media_id, "permalink": permalink}


def publishing_limit():
    """최근 24시간 게시 수와 한도 (읽기만 함). 못 읽으면 None."""
    try:
        data = _api("GET", f"{account()['id']}/content_publishing_limit", {"fields": "quota_usage,config"}).get("data")
    except InstagramError:
        return None

    return data[0] if data else None
