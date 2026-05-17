from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CASES_PATH = BASE_DIR / "data" / "regression" / "demo_test_cases.csv"
DEFAULT_OUTPUT_DIR = BASE_DIR / "data" / "regression" / "results"

CHAT_STUDENT_START = 101
STREAM_STUDENT_START = 201
TEST_CASE_COUNT = 100
TEST_STUDENT_MIN = 101
TEST_STUDENT_MAX = 300
CHAT_NOTE = "답변테스트용/chat"
STREAM_NOTE = "답변테스트용/stream"

COMPLETION_ACK_RE = re.compile(r"기록(?:했|해뒀|됐|되었|완료)|저장(?:했|해뒀|됐|되었)|바꿨|바꿨어|바꿔뒀|변경(?:했|됐|되었)|취소(?:했|됐|되었)|완료(?:했|됐|되었)")


SUPPORTED_FUNCTIONS = {
    "submit_mission_result",
    "get_mission_info",
    "request_mission_adjustment",
    "check_mission_equivalency",
    "get_user_history",
    "cancel_mission_action",
    "none",
}

NON_DB_FUNCTIONS = {"none", "get_mission_info", "check_mission_equivalency", "get_user_history"}
DB_MARKER_TABLES = [
    "checkin_log",
    "mission_changes",
    "mission_change_logs",
    "mission_reviews",
    "mission_ui_actions",
    "pending_actions",
    "pending_mission_suggestions",
]

ARG_KEY_ALIASES = {
    "result_type": {"result_type", "mission_result", "result", "status"},
    "query_type": {"query_type", "query", "info_type", "history_type"},
    "adjustment_type": {"adjustment_type", "type", "change_type"},
    "equivalency_type": {"equivalency_type", "type", "equiv_type"},
    "cancel_type": {"cancel_type", "type"},
}


def normalize_function_name(value: Any) -> str | None:
    """응답 payload/debug에서 함수명을 최대한 안정적으로 정규화한다."""
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("name", "function_name", "function", "fn", "tool_name", "detected_function"):
            found = normalize_function_name(value.get(key))
            if found:
                return found
        return None
    if isinstance(value, (list, tuple)) and value:
        return normalize_function_name(value[0])
    raw = str(value).strip()
    if not raw:
        return None
    if raw in SUPPORTED_FUNCTIONS:
        return raw
    for fn in SUPPORTED_FUNCTIONS:
        if fn != "none" and fn in raw:
            return fn
    return None


def iter_dicts(obj: Any):
    """중첩 dict/list에서 모든 dict를 순회한다."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from iter_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_dicts(item)
    elif isinstance(obj, tuple):
        for item in obj:
            yield from iter_dicts(item)


def collect_function_calls(obj: Any) -> list[tuple[str, dict[str, Any]]]:
    """fn_calls/function_calls/tool_calls 등 다양한 형태에서 (function_name, args)를 추출한다."""
    calls: list[tuple[str, dict[str, Any]]] = []
    for d in iter_dicts(obj):
        for key in ("fn_calls", "function_calls", "tool_calls", "calls"):
            value = d.get(key)
            if not isinstance(value, list):
                continue
            for item in value:
                fn = None
                args: dict[str, Any] = {}
                if isinstance(item, dict):
                    fn = normalize_function_name(item)
                    raw_args = item.get("args") or item.get("arguments") or item.get("parameters") or item.get("fn_args") or {}
                    if isinstance(raw_args, str):
                        try:
                            raw_args = json.loads(raw_args)
                        except json.JSONDecodeError:
                            raw_args = {}
                    if isinstance(raw_args, dict):
                        args = raw_args
                elif isinstance(item, (list, tuple)) and item:
                    fn = normalize_function_name(item[0])
                    if len(item) > 1 and isinstance(item[1], dict):
                        args = item[1]
                if fn:
                    calls.append((fn, args))
    return calls


def function_from_args(args: dict[str, Any]) -> str | None:
    """함수명이 없고 args만 있는 debug payload에서 가능한 함수명을 추정한다."""
    if not isinstance(args, dict):
        return None
    keys = set(args.keys())
    if "result_type" in keys or "mission_result" in keys:
        return "submit_mission_result"
    if "adjustment_type" in keys:
        return "request_mission_adjustment"
    if "equivalency_type" in keys:
        return "check_mission_equivalency"
    if "cancel_type" in keys:
        return "cancel_mission_action"
    if "query_type" in keys:
        query_type = str(args.get("query_type") or "")
        if query_type in {"weekly_summary", "monthly_summary", "daily_summary"}:
            return "get_user_history"
        return "get_mission_info"
    return None


def extract_possible_args(payload: dict[str, Any], debug: dict[str, Any], expected_function: str) -> dict[str, Any]:
    """payload/debug에서 expected_function에 대응되는 args를 최대한 찾아낸다."""
    # 1) 명시적 function call 배열에서 우선 추출
    for fn, args in collect_function_calls({"payload": payload, "debug": debug}):
        if fn == expected_function and isinstance(args, dict):
            return args

    # 2) 자주 쓰는 args 필드 직접 확인
    for d in iter_dicts({"payload": payload, "debug": debug}):
        for key in ("fn_args", "function_args", "arguments", "args", "parameters"):
            raw_args = d.get(key)
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    raw_args = {}
            if not isinstance(raw_args, dict):
                continue
            inferred = function_from_args(raw_args)
            if inferred == expected_function or expected_function == "none":
                return raw_args

    # 3) submit stream done payload 보조
    if expected_function == "submit_mission_result":
        for key in ("mission_result_type", "result_type"):
            if payload.get(key):
                return {"result_type": payload.get(key)}
    return {}


def canonicalize_args(args: dict[str, Any], expected_keys: set[str] | None = None) -> dict[str, Any]:
    """비교하기 좋도록 args key/value를 표준화한다."""
    if not isinstance(args, dict):
        return {}
    expected_keys = expected_keys or set(args.keys())
    result: dict[str, Any] = {}
    for canonical_key, aliases in ARG_KEY_ALIASES.items():
        if expected_keys and canonical_key not in expected_keys:
            continue
        for alias in aliases:
            if alias in args and args.get(alias) not in (None, ""):
                result[canonical_key] = normalize_arg_value(args.get(alias))
                break
    for key in expected_keys:
        if key not in result and key in args:
            result[key] = normalize_arg_value(args[key])
    return result


def normalize_arg_value(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        lowered = text.lower()
        mapping = {
            "완료": "success",
            "성공": "success",
            "success": "success",
            "실패": "fail",
            "fail": "fail",
            "오늘": "today",
            "일반 규칙": "general_rule",
            "일반규칙": "general_rule",
            "가이드": "general_rule",
            "변경": "change",
            "바꾸기": "change",
            "난이도 하향": "easier",
            "난이도 상향": "harder",
            "행동": "behavior",
            "장소": "place",
            "시간": "time",
            "주간 요약": "weekly_summary",
            "월간 요약": "monthly_summary",
            "일간 요약": "daily_summary",
        }
        return mapping.get(lowered, mapping.get(text, text))
    return value


def args_subset_match(expected_args: dict[str, Any], actual_args: dict[str, Any]) -> bool:
    if not expected_args:
        return True
    expected_keys = set(expected_args.keys())
    exp = canonicalize_args(expected_args, expected_keys)
    act = canonicalize_args(actual_args, expected_keys)
    for key, expected_value in exp.items():
        if key not in act:
            return False
        if normalize_arg_value(act[key]) != normalize_arg_value(expected_value):
            return False
    return True


@dataclass
class TestCase:
    idx: int
    case_id: str
    mission_id: int
    mission_name: str
    activity_key: str
    user_message: str
    expected_function: str
    expected_args: dict[str, Any]
    expected_db_changed: bool
    expected_response_type: str
    case_type: str
    note: str
    demo_safe: bool

    @property
    def chat_student_id(self) -> int:
        return CHAT_STUDENT_START + self.idx

    @property
    def stream_student_id(self) -> int:
        return STREAM_STUDENT_START + self.idx


def parse_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def load_cases(path: Path) -> list[TestCase]:
    cases: list[TestCase] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            raw_args = (row.get("expected_args") or "{}").strip()
            try:
                expected_args = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                expected_args = {}
            cases.append(
                TestCase(
                    idx=idx,
                    case_id=row["case_id"],
                    mission_id=int(float(row["mission_id"])),
                    mission_name=row["mission_name"],
                    activity_key=row.get("activity_key", ""),
                    user_message=row["user_message"],
                    expected_function=normalize_function_name(row.get("expected_function") or "none") or "none",
                    expected_args=expected_args,
                    expected_db_changed=parse_bool(row.get("expected_db_changed")),
                    expected_response_type=(row.get("expected_response_type") or "").strip(),
                    case_type=(row.get("case_type") or "").strip(),
                    note=row.get("note", ""),
                    demo_safe=parse_bool(row.get("demo_safe")),
                )
            )
    if len(cases) != TEST_CASE_COUNT:
        print(f"[warn] expected {TEST_CASE_COUNT} cases, got {len(cases)}")
    return cases


def load_env() -> None:
    load_dotenv(BASE_DIR / ".env")
    load_dotenv()


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL이 설정되어 있지 않습니다. backend/.env 또는 환경변수를 확인하세요.")
    return url


def get_conn():
    return psycopg2.connect(get_database_url())


def kst_today_sql() -> str:
    return "(NOW() AT TIME ZONE 'Asia/Seoul')::date"


def table_exists(cur, table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
    return cur.fetchone()[0] is not None


def column_exists(cur, table_name: str, column_name: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s AND column_name=%s
        """,
        (table_name, column_name),
    )
    return cur.fetchone() is not None


def test_student_ids(cur) -> list[int]:
    if not table_exists(cur, "students"):
        return []
    cur.execute(
        """
        SELECT student_id
        FROM students
        WHERE student_id BETWEEN %s AND %s
          AND student_note LIKE '답변테스트용/%%'
        ORDER BY student_id
        """,
        (TEST_STUDENT_MIN, TEST_STUDENT_MAX),
    )
    return [int(r[0]) for r in cur.fetchall()]


def delete_from_table_by_student_ids(cur, table_name: str, ids: list[int]) -> int:
    if not ids or not table_exists(cur, table_name) or not column_exists(cur, table_name, "student_id"):
        return 0
    cur.execute(f"DELETE FROM {table_name} WHERE student_id = ANY(%s)", (ids,))
    return cur.rowcount


def cleanup_test_data(*, force: bool = False) -> dict[str, int]:
    deleted: dict[str, int] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            ids = test_student_ids(cur)
            if not ids:
                conn.commit()
                print("[cleanup] 삭제할 답변테스트용 학생이 없습니다.")
                return deleted

            if table_exists(cur, "chat_messages") and table_exists(cur, "chat_sessions"):
                cur.execute(
                    """
                    DELETE FROM chat_messages
                    WHERE session_id IN (
                        SELECT session_id FROM chat_sessions WHERE student_id = ANY(%s)
                    )
                    """,
                    (ids,),
                )
                deleted["chat_messages"] = cur.rowcount

            for table in [
                "session_profiles",
                "xp_history",
                "draw_runs",
                "attendance_log",
                "game_runs",
                "lesson_progress",
                "user_memories",
                "pending_actions",
                "pending_mission_suggestions",
                "mission_change_logs",
                "mission_reviews",
                "mission_ui_actions",
                "generated_missions",
                "mission_changes",
                "checkin_log",
                "student_daily_missions",
                "student_app_state",
                "student_health_notes",
                "chat_sessions",
            ]:
                deleted[table] = delete_from_table_by_student_ids(cur, table, ids)

            cur.execute(
                """
                DELETE FROM students
                WHERE student_id = ANY(%s)
                  AND student_id BETWEEN %s AND %s
                  AND student_note LIKE '답변테스트용/%%'
                """,
                (ids, TEST_STUDENT_MIN, TEST_STUDENT_MAX),
            )
            deleted["students"] = cur.rowcount
        conn.commit()
    print("[cleanup]", deleted)
    return deleted


def setup_students() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            for n in range(1, TEST_CASE_COUNT + 1):
                cur.execute(
                    """
                    INSERT INTO students (
                        student_id, student_name, age, gender, phone_number,
                        location, is_active, student_note
                    )
                    VALUES (%s, %s, NULL, '', %s, '', TRUE, %s)
                    ON CONFLICT (student_id) DO UPDATE SET
                        student_name = EXCLUDED.student_name,
                        phone_number = EXCLUDED.phone_number,
                        is_active = EXCLUDED.is_active,
                        student_note = EXCLUDED.student_note
                    """,
                    (100 + n, f"채팅만{n:03d}", "1004", CHAT_NOTE),
                )
                cur.execute(
                    """
                    INSERT INTO students (
                        student_id, student_name, age, gender, phone_number,
                        location, is_active, student_note
                    )
                    VALUES (%s, %s, NULL, '', %s, '', TRUE, %s)
                    ON CONFLICT (student_id) DO UPDATE SET
                        student_name = EXCLUDED.student_name,
                        phone_number = EXCLUDED.phone_number,
                        is_active = EXCLUDED.is_active,
                        student_note = EXCLUDED.student_note
                    """,
                    (200 + n, f"스트림{n:03d}", "1005", STREAM_NOTE),
                )
            if table_exists(cur, "student_app_state"):
                cur.execute(
                    """
                    INSERT INTO student_app_state (student_id)
                    SELECT student_id FROM students
                    WHERE student_id BETWEEN %s AND %s
                      AND student_note LIKE '답변테스트용/%%'
                    ON CONFLICT (student_id) DO NOTHING
                    """,
                    (TEST_STUDENT_MIN, TEST_STUDENT_MAX),
                )
        conn.commit()
    print("[setup] 테스트용 학생 200명 생성/갱신 완료")


def setup_missions_and_sessions(cases: list[TestCase]) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            ids = []
            for case in cases:
                ids.extend([case.chat_student_id, case.stream_student_id])

            # 오늘 테스트 실행에 영향을 줄 수 있는 데이터만 정리한다.
            for table in [
                "checkin_log",
                "student_daily_missions",
                "pending_actions",
                "pending_mission_suggestions",
                "mission_ui_actions",
                "mission_changes",
                "mission_change_logs",
                "mission_reviews",
                "user_memories",
            ]:
                delete_from_table_by_student_ids(cur, table, ids)

            if table_exists(cur, "chat_messages") and table_exists(cur, "chat_sessions"):
                cur.execute(
                    """
                    DELETE FROM chat_messages
                    WHERE session_id IN (
                        SELECT session_id FROM chat_sessions WHERE student_id = ANY(%s)
                    )
                    """,
                    (ids,),
                )
            for table in ["session_profiles", "chat_sessions"]:
                delete_from_table_by_student_ids(cur, table, ids)

            has_assigned_by = column_exists(cur, "student_daily_missions", "assigned_by")
            has_created_at = column_exists(cur, "student_daily_missions", "created_at")
            has_updated_at = column_exists(cur, "student_daily_missions", "updated_at")

            base_columns = ["student_id", "mission_id", "assigned_date", "status"]
            extra_columns = []
            extra_values_sql = []
            if has_assigned_by:
                extra_columns.append("assigned_by")
                extra_values_sql.append("'answer_regression'")
            if has_created_at:
                extra_columns.append("created_at")
                extra_values_sql.append("NOW()")
            if has_updated_at:
                extra_columns.append("updated_at")
                extra_values_sql.append("NOW()")
            columns_sql = ", ".join(base_columns + extra_columns)
            values_sql = ", ".join(["%s", "%s", f"{kst_today_sql()}", "'assigned'"] + extra_values_sql)

            for case in cases:
                for student_id in (case.chat_student_id, case.stream_student_id):
                    cur.execute(
                        f"""
                        INSERT INTO student_daily_missions ({columns_sql})
                        VALUES ({values_sql})
                        """,
                        (student_id, case.mission_id),
                    )

            for case in cases:
                for endpoint_name, student_id in (("chat", case.chat_student_id), ("stream", case.stream_student_id)):
                    session_key = f"reg-{endpoint_name}-{case.case_id}"
                    cur.execute(
                        "INSERT INTO chat_sessions (student_id, started_at) VALUES (%s, NOW()) RETURNING session_id",
                        (student_id,),
                    )
                    db_session_id = cur.fetchone()[0]
                    cur.execute(
                        """
                        INSERT INTO session_profiles (session_id, student_id, student_name, db_session_id)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (session_id) DO UPDATE SET
                            student_id = EXCLUDED.student_id,
                            student_name = EXCLUDED.student_name,
                            db_session_id = EXCLUDED.db_session_id
                        """,
                        (
                            session_key,
                            student_id,
                            f"채팅만{case.idx + 1:03d}" if endpoint_name == "chat" else f"스트림{case.idx + 1:03d}",
                            db_session_id,
                        ),
                    )
        conn.commit()
    print("[setup] 테스트 케이스별 오늘 미션/세션 배정 완료")


def setup(cases: list[TestCase]) -> None:
    setup_students()
    setup_missions_and_sessions(cases)


def get_checkin_result(student_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if not table_exists(cur, "checkin_log"):
                return None
            cur.execute(
                f"""
                SELECT mission_id, mission_result, result_reason, function_called, checkin_id, created_at
                FROM checkin_log
                WHERE student_id = %s
                  AND checkin_date = {kst_today_sql()}
                  AND function_called = 'submit_mission_result'
                ORDER BY created_at DESC NULLS LAST, checkin_id DESC
                LIMIT 1
                """,
                (student_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def extract_actual_args(
    response_payload: dict[str, Any],
    debug: dict[str, Any],
    checkin: dict[str, Any] | None,
    expected_function: str,
    expected_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    expected_args = expected_args or {}
    if checkin and checkin.get("mission_result"):
        return {"result_type": checkin.get("mission_result")}

    submit_result = debug.get("submit_result") if isinstance(debug, dict) else None
    if isinstance(submit_result, dict) and submit_result.get("result_type"):
        return {"result_type": submit_result.get("result_type")}

    raw_args = extract_possible_args(response_payload, debug, expected_function)
    if expected_args:
        return canonicalize_args(raw_args, set(expected_args.keys()))
    return raw_args if isinstance(raw_args, dict) else {}


def get_db_change_markers(student_id: int) -> dict[str, int]:
    """채팅 로그가 아닌 미션 관련 DB 변경 흔적을 확인한다."""
    markers: dict[str, int] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            for table in DB_MARKER_TABLES:
                if not table_exists(cur, table) or not column_exists(cur, table, "student_id"):
                    continue
                cur.execute(f"SELECT COUNT(*) FROM {table} WHERE student_id = %s", (student_id,))
                count = int(cur.fetchone()[0] or 0)
                if count > 0:
                    markers[table] = count
    return markers


def infer_function(
    response_payload: dict[str, Any],
    debug: dict[str, Any],
    checkin: dict[str, Any] | None,
    db_markers: dict[str, int] | None = None,
) -> str:
    if checkin:
        return "submit_mission_result"

    # top-level / debug의 명시적 함수명
    for key in ("detected_function", "function_name", "function_called", "fn_name"):
        fn = normalize_function_name(response_payload.get(key))
        if fn and fn != "none":
            return fn
        fn = normalize_function_name(debug.get(key)) if isinstance(debug, dict) else None
        if fn and fn != "none":
            return fn

    # function_calls/fn_calls 배열
    for fn, _args in collect_function_calls({"payload": response_payload, "debug": debug}):
        if fn and fn != "none":
            return fn

    # args만 있는 debug에서 추정. 단 submit은 DB 변경이 없으면 실행 함수로 보지 않는다.
    for d in iter_dicts({"payload": response_payload, "debug": debug}):
        for key in ("fn_args", "function_args", "arguments", "args", "parameters"):
            raw_args = d.get(key)
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    raw_args = {}
            if isinstance(raw_args, dict):
                inferred = function_from_args(raw_args)
                if inferred and inferred != "submit_mission_result":
                    return inferred

    if response_payload.get("ui_action"):
        return "request_mission_adjustment"
    intent = debug.get("intent") if isinstance(debug, dict) else None
    if intent and "REPLACEMENT" in str(intent):
        return "request_mission_adjustment"

    db_markers = db_markers or {}
    if any(db_markers.get(t, 0) for t in ("mission_changes", "mission_change_logs", "mission_ui_actions", "pending_mission_suggestions")):
        return "request_mission_adjustment"
    if db_markers.get("pending_actions", 0):
        return "cancel_mission_action"
    return "none"

def infer_response_type(
    response_text: str,
    response_payload: dict[str, Any],
    debug: dict[str, Any],
    checkin: dict[str, Any] | None,
    expected_response_type: str,
    actual_function: str = "none",
) -> str:
    if checkin:
        result = checkin.get("mission_result")
        if result == "success":
            return "submit_success"
        if result == "fail":
            return "submit_fail"

    if actual_function == "request_mission_adjustment":
        return "mission_change"
    if actual_function in {"get_mission_info", "get_user_history", "check_mission_equivalency"}:
        # 정보/동치 질문은 대부분 info지만, 서버가 재질문해야 하는 케이스는 clarify로 남긴다.
        if expected_response_type in {"info", "clarify"}:
            return expected_response_type
        return "info"
    if actual_function == "cancel_mission_action":
        return "mission_change"

    if response_payload.get("ui_action"):
        return "mission_change"
    intent = debug.get("intent") if isinstance(debug, dict) else None
    if intent and "REPLACEMENT" in str(intent):
        return "mission_change"

    text = response_text or ""
    if expected_response_type == "smalltalk" and not COMPLETION_ACK_RE.search(text):
        return "smalltalk"
    if re.search(r"어떤|언제|얼마나|몇\s*(분|개|번|초|잔)|더 알려|확인|같이|말해줄래|알려줄래", text):
        return "clarify"
    if re.search(r"알려줄게|기준|해야|해도 돼|먹어도 돼|마셔도 돼|오늘 미션|규칙|방법", text):
        return "info"
    if re.search(r"오류|실패|안 됐|다시", text) and not COMPLETION_ACK_RE.search(text):
        return "error"
    return expected_response_type if expected_response_type in {"smalltalk", "info", "clarify"} else "info"

def has_confirm_ack_without_db(actual_response: str, actual_db_changed: bool) -> bool:
    return (not actual_db_changed) and bool(COMPLETION_ACK_RE.search(actual_response or ""))


def parse_jsonish(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value in (None, ""):
        return {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def compare_result(row: dict[str, Any]) -> tuple[bool, str]:
    errors: list[str] = []
    expected_function = normalize_function_name(row.get("expected_function")) or "none"
    actual_function = normalize_function_name(row.get("actual_function")) or "none"
    expected_args = parse_jsonish(row.get("expected_args"))
    actual_args = parse_jsonish(row.get("actual_args"))
    expected_db_changed = parse_bool(row.get("expected_db_changed"))
    actual_db_changed = parse_bool(row.get("actual_db_changed"))
    expected_response_type = row.get("expected_response_type") or ""
    actual_response_type = row.get("actual_response_type") or ""

    expected_submit = expected_function == "submit_mission_result"
    actual_submit = actual_function == "submit_mission_result" or bool(actual_db_changed and actual_args.get("result_type"))

    if expected_submit and not actual_submit:
        errors.append("SUBMIT_FAILED")
    elif not expected_submit and actual_submit:
        errors.append("UNEXPECTED_SUBMIT")
    elif expected_function != actual_function:
        errors.append("WRONG_FUNC")

    if expected_function == actual_function and expected_args:
        if not args_subset_match(expected_args, actual_args):
            if expected_function == "submit_mission_result":
                exp_result = normalize_arg_value(expected_args.get("result_type"))
                act_result = normalize_arg_value(actual_args.get("result_type"))
                if exp_result and act_result and exp_result != act_result:
                    errors.append("WRONG_RESULT")
                else:
                    errors.append("WRONG_ARGS")
            else:
                errors.append("WRONG_ARGS")

    if expected_db_changed != actual_db_changed:
        errors.append("DB_CHANGED_MISMATCH")

    if expected_response_type != actual_response_type:
        errors.append("WRONG_RESPONSE_TYPE")

    if has_confirm_ack_without_db(row.get("actual_response", ""), actual_db_changed):
        errors.append("NO_DB_BUT_CONFIRM_ACK")

    actual_validator_action = row.get("actual_validator_action") or ""
    if expected_submit and actual_validator_action in {"clarify", "block"}:
        errors.append("VALIDATOR_MISMATCH")
    if not expected_submit and actual_validator_action == "execute":
        errors.append("VALIDATOR_MISMATCH")

    unique = []
    for e in errors:
        if e not in unique:
            unique.append(e)
    return (not unique, ";".join(unique))

def flatten_result(
    *,
    case: TestCase,
    endpoint: str,
    student_id: int,
    response_payload: dict[str, Any],
    response_text: str,
    elapsed_ms: float | None = None,
    first_token_ms: float | None = None,
    total_elapsed_ms: float | None = None,
) -> dict[str, Any]:
    debug = response_payload.get("debug") if isinstance(response_payload.get("debug"), dict) else {}
    submit_validation = debug.get("submit_validation") if isinstance(debug.get("submit_validation"), dict) else {}
    checkin = get_checkin_result(student_id)
    db_markers = get_db_change_markers(student_id)
    actual_function = infer_function(response_payload, debug, checkin, db_markers)
    actual_args = extract_actual_args(response_payload, debug, checkin, actual_function if actual_function != "none" else case.expected_function, case.expected_args)
    actual_db_changed = bool(db_markers)
    if actual_function in NON_DB_FUNCTIONS and not checkin:
        # 정보 조회류는 채팅 저장 외 미션 DB 변경을 기대하지 않는다.
        actual_db_changed = False
    actual_response_type = infer_response_type(response_text, response_payload, debug, checkin, case.expected_response_type, actual_function)

    row = {
        "case_id": case.case_id,
        "endpoint": endpoint,
        "test_student_id": student_id,
        "mission_id": case.mission_id,
        "mission_name": case.mission_name,
        "case_type": case.case_type,
        "demo_safe": str(case.demo_safe).lower(),
        "user_message": case.user_message,
        "expected_function": case.expected_function,
        "actual_function": actual_function,
        "expected_args": case.expected_args,
        "actual_args": actual_args,
        "expected_db_changed": case.expected_db_changed,
        "actual_db_changed": actual_db_changed,
        "expected_response_type": case.expected_response_type,
        "actual_response_type": actual_response_type,
        "actual_validator_action": submit_validation.get("action", ""),
        "actual_validator_result_type": submit_validation.get("result_type", ""),
        "actual_validator_reason": submit_validation.get("reason", ""),
        "actual_db_markers": db_markers,
        "elapsed_ms": elapsed_ms if elapsed_ms is not None else "",
        "first_token_ms": first_token_ms if first_token_ms is not None else "",
        "total_elapsed_ms": total_elapsed_ms if total_elapsed_ms is not None else "",
        "actual_response": response_text,
    }
    passed, error_type = compare_result(row)
    row["pass"] = passed
    row["error_type"] = error_type
    return row


def post_chat(base_url: str, case: TestCase, timeout: int) -> dict[str, Any]:
    session_id = f"reg-chat-{case.case_id}"
    payload = {"message": case.user_message, "session_id": session_id, "mission": case.mission_name}
    start = time.perf_counter()
    response = requests.post(f"{base_url.rstrip('/')}/chat", json=payload, timeout=timeout)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    response.raise_for_status()
    data = response.json()
    text = data.get("response", "")
    return flatten_result(
        case=case,
        endpoint="/chat",
        student_id=case.chat_student_id,
        response_payload=data,
        response_text=text,
        elapsed_ms=elapsed_ms,
    )


def parse_sse_event(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line.startswith("data:"):
        return None
    raw = line[5:].strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def post_stream(base_url: str, case: TestCase, timeout: int) -> dict[str, Any]:
    session_id = f"reg-stream-{case.case_id}"
    payload = {"message": case.user_message, "session_id": session_id, "mission": case.mission_name}
    start = time.perf_counter()
    first_token_ms: float | None = None
    tokens: list[str] = []
    done_payload: dict[str, Any] = {}
    with requests.post(f"{base_url.rstrip('/')}/chat/stream", json=payload, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            event = parse_sse_event(raw_line)
            if not event:
                continue
            if first_token_ms is None:
                first_token_ms = round((time.perf_counter() - start) * 1000, 2)
            if event.get("type") == "token":
                tokens.append(str(event.get("content", "")))
            elif event.get("type") == "done":
                done_payload = event
    total_elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    response_text = "".join(tokens)
    return flatten_result(
        case=case,
        endpoint="/chat/stream",
        student_id=case.stream_student_id,
        response_payload=done_payload,
        response_text=response_text,
        first_token_ms=first_token_ms or total_elapsed_ms,
        total_elapsed_ms=total_elapsed_ms,
    )


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            clean_row = {}
            for key in fieldnames:
                value = row.get(key, "")
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                clean_row[key] = value
            writer.writerow(clean_row)


def run_chat(cases: list[TestCase], base_url: str, output_dir: Path, timeout: int) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        print(f"[/chat] {case.case_id} {case.user_message}")
        try:
            rows.append(post_chat(base_url, case, timeout))
        except Exception as exc:
            rows.append(error_row(case, "/chat", case.chat_student_id, exc))
    fieldnames = chat_result_fields()
    write_csv(output_dir / "demo_test_results_chat.csv", rows, fieldnames)
    return rows


def run_stream(cases: list[TestCase], base_url: str, output_dir: Path, timeout: int) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        print(f"[/chat/stream] {case.case_id} {case.user_message}")
        try:
            rows.append(post_stream(base_url, case, timeout))
        except Exception as exc:
            rows.append(error_row(case, "/chat/stream", case.stream_student_id, exc))
    fieldnames = stream_result_fields()
    write_csv(output_dir / "demo_test_results_stream.csv", rows, fieldnames)
    return rows


def error_row(case: TestCase, endpoint: str, student_id: int, exc: Exception) -> dict[str, Any]:
    row = {
        "case_id": case.case_id,
        "endpoint": endpoint,
        "test_student_id": student_id,
        "mission_id": case.mission_id,
        "mission_name": case.mission_name,
        "case_type": case.case_type,
        "demo_safe": str(case.demo_safe).lower(),
        "user_message": case.user_message,
        "expected_function": case.expected_function,
        "actual_function": "error",
        "expected_args": case.expected_args,
        "actual_args": {},
        "expected_db_changed": case.expected_db_changed,
        "actual_db_changed": False,
        "expected_response_type": case.expected_response_type,
        "actual_response_type": "error",
        "actual_validator_action": "",
        "actual_validator_result_type": "",
        "actual_validator_reason": "",
        "actual_db_markers": {},
        "elapsed_ms": "",
        "first_token_ms": "",
        "total_elapsed_ms": "",
        "pass": False,
        "error_type": "REQUEST_ERROR",
        "actual_response": repr(exc),
    }
    return row


def chat_result_fields() -> list[str]:
    return [
        "case_id", "endpoint", "test_student_id", "mission_id", "mission_name", "case_type", "demo_safe",
        "user_message", "expected_function", "actual_function", "expected_args", "actual_args",
        "expected_db_changed", "actual_db_changed", "expected_response_type", "actual_response_type",
        "actual_validator_action", "actual_validator_result_type", "actual_validator_reason", "actual_db_markers",
        "elapsed_ms", "pass", "error_type", "actual_response",
    ]


def stream_result_fields() -> list[str]:
    return [
        "case_id", "endpoint", "test_student_id", "mission_id", "mission_name", "case_type", "demo_safe",
        "user_message", "expected_function", "actual_function", "expected_args", "actual_args",
        "expected_db_changed", "actual_db_changed", "expected_response_type", "actual_response_type",
        "actual_validator_action", "actual_validator_result_type", "actual_validator_reason", "actual_db_markers",
        "first_token_ms", "total_elapsed_ms", "pass", "error_type", "actual_response",
    ]


def read_result_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def report(cases: list[TestCase], output_dir: Path) -> None:
    chat_rows = read_result_csv(output_dir / "demo_test_results_chat.csv")
    stream_rows = read_result_csv(output_dir / "demo_test_results_stream.csv")
    chat_by_case = {r["case_id"]: r for r in chat_rows}
    stream_by_case = {r["case_id"]: r for r in stream_rows}

    failures = []
    for source_rows in (chat_rows, stream_rows):
        for row in source_rows:
            passed = parse_bool(row.get("pass"))
            error_type = row.get("error_type", "")
            if not passed:
                if row.get("endpoint") == "/chat/stream":
                    chat_row = chat_by_case.get(row["case_id"])
                    if chat_row and parse_bool(chat_row.get("pass")) and "STREAM_ONLY_ERROR" not in error_type:
                        error_type = (error_type + ";" if error_type else "") + "STREAM_ONLY_ERROR"
                failures.append(failure_summary(row, error_type))

    failure_fields = [
        "case_id", "endpoint", "mission_id", "mission_name", "user_message",
        "expected_summary", "actual_summary", "error_type", "why_it_matters", "suggested_owner",
    ]
    write_csv(output_dir / "failure_cases.csv", failures, failure_fields)

    safe_rows = []
    for case in cases:
        chat = chat_by_case.get(case.case_id)
        stream = stream_by_case.get(case.case_id)
        if not (case.demo_safe and chat and stream):
            continue
        if parse_bool(chat.get("pass")) and parse_bool(stream.get("pass")):
            safe_rows.append(
                {
                    "case_id": case.case_id,
                    "mission_id": case.mission_id,
                    "mission_name": case.mission_name,
                    "user_message": case.user_message,
                    "expected_response_type": case.expected_response_type,
                    "chat_pass": True,
                    "stream_pass": True,
                    "chat_elapsed_ms": chat.get("elapsed_ms", ""),
                    "stream_first_token_ms": stream.get("first_token_ms", ""),
                    "stream_total_elapsed_ms": stream.get("total_elapsed_ms", ""),
                    "front_checked": False,
                    "note": case.note,
                }
            )
    safe_fields = [
        "case_id", "mission_id", "mission_name", "user_message", "expected_response_type",
        "chat_pass", "stream_pass", "chat_elapsed_ms", "stream_first_token_ms",
        "stream_total_elapsed_ms", "front_checked", "note",
    ]
    write_csv(output_dir / "demo_safe_cases.csv", safe_rows, safe_fields)

    summary = build_time_summary(chat_rows, stream_rows, failures, safe_rows)
    (output_dir / "regression_summary.md").write_text(summary, encoding="utf-8")
    print(summary)


def failure_summary(row: dict[str, Any], error_type: str) -> dict[str, Any]:
    expected = f"{row.get('expected_function')} / {row.get('expected_args')} / db_changed={row.get('expected_db_changed')} / {row.get('expected_response_type')}"
    actual = f"{row.get('actual_function')} / {row.get('actual_args')} / db_changed={row.get('actual_db_changed')} / {row.get('actual_response_type')}"
    return {
        "case_id": row.get("case_id", ""),
        "endpoint": row.get("endpoint", ""),
        "mission_id": row.get("mission_id", ""),
        "mission_name": row.get("mission_name", ""),
        "user_message": row.get("user_message", ""),
        "expected_summary": expected,
        "actual_summary": actual,
        "error_type": error_type,
        "why_it_matters": why_it_matters(error_type),
        "suggested_owner": suggested_owner(error_type, row.get("case_type", "")),
    }


def why_it_matters(error_type: str) -> str:
    if "UNEXPECTED_SUBMIT" in error_type:
        return "submit 되면 안 되는 문장이 DB에 기록될 수 있음"
    if "SUBMIT_FAILED" in error_type:
        return "정상 수행 보고가 기록되지 않아 사용자 경험이 저하될 수 있음"
    if "WRONG_RESULT" in error_type:
        return "success/fail이 반대로 저장될 수 있음"
    if "NO_DB_BUT_CONFIRM_ACK" in error_type:
        return "DB 변경 없이 완료형 응답이 나와 사용자에게 잘못 안내할 수 있음"
    if "STREAM_ONLY_ERROR" in error_type:
        return "/chat과 /chat/stream 결과가 달라 시연 화면에서만 오류가 날 수 있음"
    if "VALIDATOR_MISMATCH" in error_type:
        return "submit validator의 execute/clarify/block 판단이 기대와 다름"
    return "기대 결과와 실제 결과가 일치하지 않음"


def suggested_owner(error_type: str, case_type: str) -> str:
    if case_type == "equivalency" or "equivalency" in case_type:
        return "한채원"
    if any(key in error_type for key in ["UNEXPECTED_SUBMIT", "SUBMIT_FAILED", "WRONG_RESULT", "VALIDATOR_MISMATCH", "NO_DB_BUT_CONFIRM_ACK"]):
        return "이채원"
    return "장수정"


def to_float(value: str | None) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except ValueError:
        return None


def stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"avg": None, "min": None, "max": None}
    return {"avg": round(sum(values) / len(values), 2), "min": round(min(values), 2), "max": round(max(values), 2)}


def build_time_summary(chat_rows: list[dict[str, Any]], stream_rows: list[dict[str, Any]], failures: list[dict[str, Any]], safe_rows: list[dict[str, Any]]) -> str:
    chat_elapsed = [v for v in (to_float(r.get("elapsed_ms")) for r in chat_rows) if v is not None]
    stream_first = [v for v in (to_float(r.get("first_token_ms")) for r in stream_rows) if v is not None]
    stream_total = [v for v in (to_float(r.get("total_elapsed_ms")) for r in stream_rows) if v is not None]
    chat_stats = stats(chat_elapsed)
    stream_first_stats = stats(stream_first)
    stream_total_stats = stats(stream_total)

    slow_candidates = []
    for row in chat_rows:
        elapsed = to_float(row.get("elapsed_ms"))
        if elapsed is not None:
            slow_candidates.append((elapsed, row.get("case_id", ""), row.get("endpoint", ""), row.get("user_message", "")))
    for row in stream_rows:
        elapsed = to_float(row.get("total_elapsed_ms"))
        if elapsed is not None:
            slow_candidates.append((elapsed, row.get("case_id", ""), row.get("endpoint", ""), row.get("user_message", "")))
    slow_candidates.sort(reverse=True)
    slow_lines = [f"- {case_id} {endpoint}: {elapsed}ms / {msg}" for elapsed, case_id, endpoint, msg in slow_candidates[:5]]

    return "\n".join([
        "# 응답 안정화 회귀 테스트 요약",
        "",
        f"- /chat 실행 케이스: {len(chat_rows)}개",
        f"- /chat/stream 실행 케이스: {len(stream_rows)}개",
        f"- 실패 케이스: {len(failures)}개",
        f"- 시연 후보 통과 케이스: {len(safe_rows)}개",
        "",
        "## 응답 시간",
        f"- /chat elapsed_ms: avg={chat_stats['avg']}, min={chat_stats['min']}, max={chat_stats['max']}",
        f"- /chat/stream first_token_ms: avg={stream_first_stats['avg']}, min={stream_first_stats['min']}, max={stream_first_stats['max']}",
        f"- /chat/stream total_elapsed_ms: avg={stream_total_stats['avg']}, min={stream_total_stats['min']}, max={stream_total_stats['max']}",
        "",
        "## 느린 케이스 TOP 5",
        *(slow_lines or ["- 아직 실행 결과가 없습니다."]),
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description="응답 안정화 회귀 테스트 자동화 스크립트")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--base-url", default=os.getenv("REGRESSION_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("REGRESSION_TIMEOUT", "180")))
    parser.add_argument("--reset", action="store_true", help="기존 답변테스트용 데이터를 삭제하고 시작")
    parser.add_argument("--setup", action="store_true", help="테스트용 학생 생성 및 오늘 미션 배정")
    parser.add_argument("--run-chat", action="store_true", help="/chat 100개 테스트 실행")
    parser.add_argument("--run-stream", action="store_true", help="/chat/stream 100개 테스트 실행")
    parser.add_argument("--run", action="store_true", help="/chat과 /chat/stream 모두 실행")
    parser.add_argument("--report", action="store_true", help="결과 비교 및 리포트 생성")
    parser.add_argument("--cleanup", action="store_true", help="테스트용 DB 데이터 삭제. 기본값은 실행하지 않음")
    parser.add_argument("--force-cleanup", action="store_true", help="실패 결과가 있어도 강제 cleanup")
    args = parser.parse_args()

    load_env()
    cases = load_cases(args.cases)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.reset:
        cleanup_test_data(force=True)

    if args.setup:
        setup(cases)

    if args.run or args.run_chat:
        run_chat(cases, args.base_url, args.output_dir, args.timeout)

    if args.run or args.run_stream:
        run_stream(cases, args.base_url, args.output_dir, args.timeout)

    if args.report:
        report(cases, args.output_dir)

    if args.cleanup:
        if not args.force_cleanup:
            failure_path = args.output_dir / "failure_cases.csv"
            if failure_path.exists():
                with failure_path.open("r", encoding="utf-8-sig", newline="") as f:
                    failure_count = max(sum(1 for _ in f) - 1, 0)
                if failure_count > 0:
                    print(f"[cleanup] 실패 케이스 {failure_count}개가 있어 cleanup을 건너뜁니다. 강제 삭제하려면 --force-cleanup을 추가하세요.")
                    return
        cleanup_test_data(force=args.force_cleanup)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("중단됨")
        sys.exit(130)
