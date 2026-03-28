import os
import sys
from datetime import datetime
from collections import defaultdict

import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

JIRA_URL    = os.getenv("JIRA_URL", "https://jiralive.nexon.com").rstrip("/")
JIRA_USER   = os.getenv("JIRA_USER", "")
JIRA_PASS   = os.getenv("JIRA_PASS", "")
JIRA_PROJECT = os.getenv("JIRA_PROJECT", "MA")

if not JIRA_USER or not JIRA_PASS:
    print("[ERROR] .env 파일에 JIRA_USER / JIRA_PASS 를 설정해 주세요.")
    sys.exit(1)

AUTH    = HTTPBasicAuth(JIRA_USER, JIRA_PASS)
HEADERS = {"Accept": "application/json"}


def jira_get(path, params=None):
    url = f"{JIRA_URL}{path}"
    resp = requests.get(url, auth=AUTH, headers=HEADERS, params=params, verify=True, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_all_issues(path, key="issues", params=None):
    """페이지네이션 처리 후 전체 이슈 반환."""
    items, start = [], 0
    base_params = dict(params or {})
    while True:
        base_params.update({"startAt": start, "maxResults": 100})
        data = jira_get(path, params=base_params)
        items.extend(data[key])
        total = data.get("total", len(items))
        start += len(data[key])
        if start >= total or not data[key]:
            break
    return items


def get_active_sprint():
    boards = jira_get("/rest/agile/1.0/board", params={"projectKeyOrId": JIRA_PROJECT, "maxResults": 50})
    if not boards.get("values"):
        return None, None

    board = boards["values"][0]
    sprints = jira_get(f"/rest/agile/1.0/board/{board['id']}/sprint", params={"state": "active"})
    sprint = sprints["values"][0] if sprints.get("values") else None
    return board, sprint


def get_sprint_issues(sprint_id):
    return fetch_all_issues(
        f"/rest/agile/1.0/sprint/{sprint_id}/issue",
        params={"fields": "summary,status,assignee,priority,issuetype"},
    )


def get_open_project_issues():
    return fetch_all_issues(
        "/rest/api/2/search",
        params={
            "jql": f'project={JIRA_PROJECT} AND statusCategory != "Done" ORDER BY created DESC',
            "fields": "summary,status,assignee,issuetype",
        },
    )


# ─── 출력 헬퍼 ────────────────────────────────────────────────

SEP = "─" * 62

def header(title):
    print(f"\n{'═' * 62}")
    print(f"  {title}")
    print(f"{'═' * 62}")


def bar_chart(count_dict, sort_by_count=True):
    if not count_dict:
        print("  (없음)")
        return
    items = sorted(count_dict.items(), key=lambda x: -x[1] if sort_by_count else x[0])
    max_val = max(v for _, v in items) or 1
    for label, cnt in items:
        filled = int(cnt / max_val * 20)
        bar = "█" * filled + "░" * (20 - filled)
        print(f"  {label:<22} {cnt:>4}  {bar}")


# ─── 메인 ────────────────────────────────────────────────────

def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'#' * 62}")
    print(f"  Jira Daily Report  |  {now}")
    print(f"  Project : {JIRA_PROJECT}   ({JIRA_URL})")
    print(f"{'#' * 62}")

    # ── 1. Active Sprint ──────────────────────────────────────
    header("1. Active Sprint 현황")
    board, sprint = get_active_sprint()

    if sprint:
        start_date = sprint.get("startDate", "")[:10]
        end_date   = sprint.get("endDate",   "")[:10]
        print(f"  보드    : {board['name']}")
        print(f"  스프린트: {sprint['name']}")
        print(f"  기간    : {start_date}  ~  {end_date}")

        sprint_issues = get_sprint_issues(sprint["id"])
        total = len(sprint_issues)

        status_cnt   = defaultdict(int)
        assignee_map = defaultdict(list)

        DONE_CATEGORIES = {"완료", "Done", "Closed", "Resolved"}

        for issue in sprint_issues:
            fields = issue["fields"]
            status = fields["status"]["name"]
            a      = fields.get("assignee")
            name   = a["displayName"] if a else "Unassigned"
            status_cnt[status] += 1
            assignee_map[name].append(status)

        done  = sum(v for k, v in status_cnt.items() if k in DONE_CATEGORIES)
        pct   = done / total * 100 if total else 0

        print(f"\n  전체 {total}건  |  완료 {done}건  |  진행률 {pct:.1f}%")
        print(f"\n  [상태별]")
        bar_chart(status_cnt)

        print(f"\n  [담당자별]")
        for name, statuses in sorted(assignee_map.items(), key=lambda x: -len(x[1])):
            cnt_map = defaultdict(int)
            for s in statuses:
                cnt_map[s] += 1
            detail = "  ".join(f"{k} {v}" for k, v in cnt_map.items())
            print(f"  {name:<25} {len(statuses):>3}건   {detail}")
    else:
        print("  현재 활성 스프린트가 없습니다.")

    # ── 2. Team Overview ──────────────────────────────────────
    header("2. 팀 전체 현황 (미완료 이슈)")
    open_issues = get_open_project_issues()
    total_open  = len(open_issues)

    status_cnt   = defaultdict(int)
    type_cnt     = defaultdict(int)
    assignee_cnt = defaultdict(int)

    for issue in open_issues:
        f    = issue["fields"]
        status_cnt[f["status"]["name"]] += 1
        type_cnt[f["issuetype"]["name"]] += 1
        a    = f.get("assignee")
        name = a["displayName"] if a else "Unassigned"
        assignee_cnt[name] += 1

    print(f"  미완료 이슈 합계: {total_open}건")

    print(f"\n  [상태별]")
    bar_chart(status_cnt)

    print(f"\n  [유형별]")
    bar_chart(type_cnt)

    print(f"\n  [담당자별 Top 15]")
    top15 = dict(sorted(assignee_cnt.items(), key=lambda x: -x[1])[:15])
    bar_chart(top15)

    print(f"\n{'#' * 62}\n")


if __name__ == "__main__":
    main()
