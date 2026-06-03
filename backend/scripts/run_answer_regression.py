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

SUPPORTED_INTENTS = {"A", "B", "C", "D"}

FUNCTION_ALIASES = {
    "submit_mission_action": "submit_mission_result",
    "submit": "submit_mission_result",
    "mission_info": "get_mission_info",
    "history": "get_user_history",
    "equiv": "check_mission_equivalency",
    "equivalency": "check_mission_equivalency",
    "adjust": "request_mission_adjustment",
    "cancel": "cancel_mission_action",
    "cancel_mission": "cancel_mission_action",
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

FUNCTION_ARG_KEYS = set().union(*ARG_KEY_ALIASES.values())


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
    raw = FUNCTION_ALIASES.get(raw, raw)
    if raw in SUPPORTED_FUNCTIONS:
        return raw
    lowered = raw.lower()
    if lowered in FUNCTION_ALIASES:
        return FUNCTION_ALIASES[lowered]
    for fn in SUPPORTED_FUNCTIONS:
        if fn != "none" and fn in raw:
            return fn
    for alias, fn in FUNCTION_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return fn
    return None


def normalize_function_spec(value: Any) -> str:
    raw = str(value or "none").strip() or "none"
    parts = []
    for part in raw.split("|"):
        normalized = normalize_function_name(part) or str(part or "").strip()
        if normalized:
            parts.append(normalized)
    return "|".join(parts) if parts else "none"


def split_allowed_values(value: Any, *, default: str = "") -> list[str]:
    raw = str(value if value is not None else default).strip()
    if not raw:
        raw = default
    return [part.strip() for part in raw.split("|") if part.strip()]


def split_allowed_functions(value: Any) -> list[str]:
    return [normalize_function_name(part) or "none" for part in split_allowed_values(value, default="none")]


def normalize_actual_function(value: Any) -> str:
    normalized = normalize_function_name(value)
    if normalized:
        return normalized
    raw = str(value or "").strip()
    return "none" if not raw else raw


def normalize_intent(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("intent", "route_intent", "initial_intent", "actual_intent", "label", "value", "name"):
            found = normalize_intent(value.get(key))
            if found:
                return found
        return ""
    if isinstance(value, (list, tuple)) and value:
        return normalize_intent(value[0])
    raw = str(value).strip()
    if not raw:
        return ""
    upper = raw.upper()
    if upper in SUPPORTED_INTENTS:
        return upper
    match = re.search(r"(?:^|[^A-Z])([ABCD])(?:[^A-Z]|$)", upper)
    return match.group(1) if match else ""


def extract_actual_intent(response_payload: dict[str, Any], debug: dict[str, Any]) -> str:
    for source in (response_payload, debug):
        if not isinstance(source, dict):
            continue
        for key in ("intent", "route_intent", "initial_intent", "actual_intent", "classified_intent"):
            found = normalize_intent(source.get(key))
            if found:
                return found

    for event in response_payload.get("events", []) if isinstance(response_payload, dict) else []:
        if not isinstance(event, dict):
            continue
        if event.get("type") == "pipeline":
            found = normalize_intent(event)
            if found:
                return found
        event_debug = event.get("debug") if isinstance(event.get("debug"), dict) else {}
        found = normalize_intent(event_debug)
        if found:
            return found

    for d in iter_dicts({"payload": response_payload, "debug": debug}):
        for key in ("intent", "route_intent", "initial_intent", "actual_intent", "classified_intent"):
            found = normalize_intent(d.get(key))
            if found:
                return found
    return ""


def normalize_decision(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("decision", "equivalency_decision", "value", "name"):
            found = normalize_decision(value.get(key))
            if found:
                return found
        return ""
    if isinstance(value, (list, tuple)) and value:
        return normalize_decision(value[0])
    return str(value).strip().lower()


def extract_actual_decision(response_payload: dict[str, Any], debug: dict[str, Any]) -> str:
    sources: list[Any] = [response_payload, debug]
    if isinstance(response_payload, dict):
        sources.extend(response_payload.get("events", []))

    for source in sources:
        if not isinstance(source, dict):
            continue
        judgment = source.get("equivalency_judgment")
        found = normalize_decision(judgment)
        if found:
            return found
        for key in ("decision", "equivalency_decision"):
            found = normalize_decision(source.get(key))
            if found:
                return found
        event_debug = source.get("debug") if isinstance(source.get("debug"), dict) else {}
        judgment = event_debug.get("equivalency_judgment")
        found = normalize_decision(judgment)
        if found:
            return found
        for key in ("decision", "equivalency_decision"):
            found = normalize_decision(event_debug.get(key))
            if found:
                return found

    for d in iter_dicts({"payload": response_payload, "debug": debug}):
        judgment = d.get("equivalency_judgment")
        found = normalize_decision(judgment)
        if found:
            return found
    return ""


def intent_matches(expected_intent: Any, actual_intent: Any) -> bool:
    allowed = [part.upper() for part in split_allowed_values(expected_intent, default="ANY")]
    if not allowed or "ANY" in allowed:
        return True
    actual = normalize_intent(actual_intent)
    return bool(actual and actual in allowed)


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


def direct_function_args(d: dict[str, Any]) -> dict[str, Any]:
    """debug/payload 최상위에 바로 놓인 함수 인자들을 모은다."""
    if not isinstance(d, dict):
        return {}
    return {key: value for key, value in d.items() if key in FUNCTION_ARG_KEYS and value not in (None, "")}


def extract_possible_args(payload: dict[str, Any], debug: dict[str, Any], expected_function: str) -> dict[str, Any]:
    """payload/debug에서 expected_function에 대응되는 args를 최대한 찾아낸다."""
    # 1) 명시적 function call 배열에서 우선 추출
    for fn, args in collect_function_calls({"payload": payload, "debug": debug}):
        if fn == expected_function and isinstance(args, dict):
            return args

    # 2) 자주 쓰는 args 필드 직접 확인
    for d in iter_dicts({"payload": payload, "debug": debug}):
        direct_args = direct_function_args(d)
        if direct_args:
            inferred = function_from_args(direct_args)
            if inferred == expected_function or expected_function == "none":
                return direct_args

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
    expected_decision: str
    expected_submit: bool
    expected_intent: str
    metric_group: str
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


def infer_expected_decision(row: dict[str, str]) -> str:
    explicit = (row.get("expected_decision") or "").strip().lower()
    if explicit:
        return explicit
    case_type = (row.get("case_type") or "").strip().lower()
    if "equivalency_allowed" in case_type:
        return "approved"
    if "equivalency_denied" in case_type:
        return "denied"
    if "equivalency_clarify" in case_type:
        return "clarify"
    return ""


def infer_expected_response_type(row: dict[str, str]) -> str:
    explicit = (row.get("expected_response_type") or "").strip()
    if explicit:
        return explicit
    case_type = (row.get("case_type") or "").strip().lower()
    if "equivalency_clarify" in case_type:
        return "clarify"
    return explicit


def infer_expected_submit(row: dict[str, str], expected_function: str) -> bool:
    explicit = row.get("expected_submit")
    if explicit not in (None, ""):
        return parse_bool(explicit)
    return "submit_mission_result" in split_allowed_functions(expected_function)


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
                    expected_function=normalize_function_spec(row.get("expected_function") or "none"),
                    expected_args=expected_args,
                    expected_db_changed=parse_bool(row.get("expected_db_changed")),
                    expected_response_type=infer_expected_response_type(row),
                    expected_decision=infer_expected_decision(row),
                    expected_submit=infer_expected_submit(row, normalize_function_spec(row.get("expected_function") or "none")),
                    expected_intent=(row.get("expected_intent") or "ANY").strip().upper() or "ANY",
                    metric_group=(row.get("metric_group") or row.get("case_type") or "default").strip() or "default",
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


TRANSIENT_DB_ERRORS = (psycopg2.OperationalError, psycopg2.InterfaceError)


def run_db_transaction(label: str, work, *, attempts: int = 3):
    """SSL 끊김 같은 일시적 DB 연결 오류는 새 연결로 재시도한다."""
    last_exc = None
    for attempt in range(1, attempts + 1):
        conn = None
        try:
            conn = get_conn()
            result = work(conn)
            conn.commit()
            return result
        except TRANSIENT_DB_ERRORS as exc:
            last_exc = exc
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            if attempt >= attempts:
                raise
            wait_sec = round(1.5 * attempt, 1)
            print(f"[db-retry] {label} 연결 오류({type(exc).__name__}), {wait_sec}s 후 재시도 {attempt + 1}/{attempts}")
            time.sleep(wait_sec)
        except Exception:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    if last_exc:
        raise last_exc


def kst_today_sql() -> str:
    return "(NOW() AT TIME ZONE 'Asia/Seoul')::date"


def table_exists(cur, table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
    row = cur.fetchone()
    if row is None:
        return False
    if isinstance(row, dict):
        return next(iter(row.values())) is not None
    return row[0] is not None


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
    def work(conn):
        deleted: dict[str, int] = {}
        with conn.cursor() as cur:
            ids = test_student_ids(cur)
            if not ids:
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
        return deleted

    deleted = run_db_transaction("cleanup", work)
    print("[cleanup]", deleted)
    return deleted


def iter_case_students(case: TestCase, endpoints: set[str]):
    if "chat" in endpoints:
        yield "chat", case.chat_student_id, f"채팅만{case.idx + 1:03d}", "1004", CHAT_NOTE
    if "stream" in endpoints:
        yield "stream", case.stream_student_id, f"스트림{case.idx + 1:03d}", "1005", STREAM_NOTE


def setup_students(cases: list[TestCase], endpoints: set[str]) -> None:
    def work(conn):
        with conn.cursor() as cur:
            ids: list[int] = []
            for case in cases:
                for _endpoint_name, student_id, student_name, phone_number, student_note in iter_case_students(case, endpoints):
                    ids.append(student_id)
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
                        (student_id, student_name, phone_number, student_note),
                    )
            if ids and table_exists(cur, "student_app_state"):
                cur.execute(
                    """
                    INSERT INTO student_app_state (student_id)
                    SELECT student_id FROM students
                    WHERE student_id = ANY(%s)
                      AND student_note LIKE '답변테스트용/%%'
                    ON CONFLICT (student_id) DO NOTHING
                    """,
                    (ids,),
                )
        return len(ids)

    student_count = run_db_transaction("setup_students", work)
    print(f"[setup] 테스트용 학생 {student_count}명 생성/갱신 완료")


def setup_missions_and_sessions(cases: list[TestCase], endpoints: set[str]) -> None:
    def work(conn):
        with conn.cursor() as cur:
            ids = []
            for case in cases:
                ids.extend(student_id for _endpoint_name, student_id, _student_name, _phone_number, _note in iter_case_students(case, endpoints))

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
                for _endpoint_name, student_id, _student_name, _phone_number, _note in iter_case_students(case, endpoints):
                    cur.execute(
                        f"""
                        INSERT INTO student_daily_missions ({columns_sql})
                        VALUES ({values_sql})
                        """,
                        (student_id, case.mission_id),
                    )

            for case in cases:
                for endpoint_name, student_id, student_name, _phone_number, _note in iter_case_students(case, endpoints):
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
                            student_name,
                            db_session_id,
                        ),
                    )
        return len(ids)

    student_count = run_db_transaction("setup_missions_and_sessions", work)
    print(f"[setup] 테스트 케이스별 오늘 미션/세션 배정 완료 ({student_count}명)")


def setup(cases: list[TestCase], endpoints: set[str]) -> None:
    setup_students(cases, endpoints)
    setup_missions_and_sessions(cases, endpoints)


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
    marker_delta: dict[str, int] | None = None,
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
        direct_args = direct_function_args(d)
        if direct_args:
            inferred = function_from_args(direct_args)
            if inferred and inferred != "submit_mission_result":
                return inferred

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

    marker_delta = marker_delta or {}
    if any(
        marker_delta.get(t, 0) > 0
        for t in ("mission_changes", "mission_change_logs", "mission_ui_actions", "pending_mission_suggestions")
    ):
        return "request_mission_adjustment"
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
    if re.search(r"성공(?:으로)?\s*(?:기록|저장)|성공[!！]?\s*기록|성공 기록", text):
        return "submit_success"
    if re.search(r"실패(?:로)?\s*(?:기록|저장)|기록해뒀어", text):
        return "submit_fail"
    if re.search(r"미션(?:을)?\s*(?:바꿔|변경)|새 미션|오늘 미션은", text):
        return "mission_change"
    if re.search(r"아직 기록이 없어|이번 주 기록|주간 기록|기록을 알려", text):
        return "info"
    if expected_response_type == "smalltalk" and not COMPLETION_ACK_RE.search(text):
        return "smalltalk"
    if re.search(r"어떤|언제|얼마나|몇\s*(분|개|번|초|잔)|더 알려|확인해볼까|확인|같이|말해줄래|알려줄래|오늘 한 거야|다시 말해줘|기록할 수 없어|바꾸고 싶은 거라면", text):
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


def primary_expected_function(expected_function: str) -> str:
    allowed = split_allowed_functions(expected_function)
    for preferred in ("submit_mission_result", "request_mission_adjustment", "cancel_mission_action"):
        if preferred in allowed:
            return preferred
    for fn in allowed:
        if fn != "none":
            return fn
    return "none"


def allowed_response_types(value: Any) -> list[str]:
    return split_allowed_values(value, default="")


def compare_result(row: dict[str, Any]) -> tuple[bool, str]:
    errors: list[str] = []
    expected_functions = split_allowed_functions(row.get("expected_function"))
    actual_function = normalize_actual_function(row.get("actual_function"))
    expected_args = parse_jsonish(row.get("expected_args"))
    actual_args = parse_jsonish(row.get("actual_args"))
    expected_db_changed = parse_bool(row.get("expected_db_changed"))
    actual_db_changed = parse_bool(row.get("actual_db_changed"))
    expected_response_type = row.get("expected_response_type") or ""
    actual_response_type = row.get("actual_response_type") or ""
    expected_decision = (row.get("expected_decision") or "").strip().lower()
    actual_decision = (row.get("actual_decision") or "").strip().lower()
    expected_submit_raw = row.get("expected_submit")
    expected_intent = row.get("expected_intent") or "ANY"
    actual_intent = row.get("actual_intent") or ""
    response_types = allowed_response_types(expected_response_type)

    intent_pass = intent_matches(expected_intent, actual_intent)
    function_pass = actual_function in expected_functions
    args_pass = True if not expected_args else args_subset_match(expected_args, actual_args)
    fc_pass = function_pass and args_pass
    db_pass = expected_db_changed == actual_db_changed
    response_type_pass = actual_response_type in response_types if response_types else actual_response_type == ""

    expected_submit = (
        parse_bool(expected_submit_raw)
        if expected_submit_raw not in (None, "")
        else "submit_mission_result" in expected_functions
    )
    actual_submit_raw = row.get("actual_submit")
    actual_submit = (
        parse_bool(actual_submit_raw)
        if actual_submit_raw not in (None, "")
        else actual_function == "submit_mission_result" or bool(actual_db_changed and actual_args.get("result_type"))
    )
    submit_pass = expected_submit == actual_submit
    decision_pass = True if not expected_decision else expected_decision == actual_decision

    actual_validator_action = row.get("actual_validator_action") or ""
    validator_pass = True
    if expected_submit and actual_validator_action in {"clarify", "block"}:
        validator_pass = False
    if not expected_submit and actual_submit:
        validator_pass = False

    if expected_submit and not actual_submit:
        errors.append("SUBMIT_FAILED")
    elif not expected_submit and actual_submit:
        errors.append("UNEXPECTED_SUBMIT")
    elif not function_pass:
        errors.append("WRONG_FUNC")

    if expected_args and not args_pass:
        if "submit_mission_result" in expected_functions:
            exp_result = normalize_arg_value(expected_args.get("result_type"))
            act_result = normalize_arg_value(actual_args.get("result_type"))
            if exp_result and act_result and exp_result != act_result:
                errors.append("WRONG_RESULT")
            else:
                errors.append("WRONG_ARGS")
        else:
            errors.append("WRONG_ARGS")

    if not db_pass:
        errors.append("DB_CHANGED_MISMATCH")

    if not response_type_pass:
        errors.append("WRONG_RESPONSE_TYPE")

    if not decision_pass:
        errors.append("WRONG_DECISION")

    if has_confirm_ack_without_db(row.get("actual_response", ""), actual_db_changed):
        errors.append("NO_DB_BUT_CONFIRM_ACK")

    if not validator_pass:
        errors.append("VALIDATOR_MISMATCH")

    unique = []
    for e in errors:
        if e not in unique:
            unique.append(e)

    execution_pass = fc_pass and db_pass and validator_pass and submit_pass and decision_pass
    e2e_pass = intent_pass and fc_pass and db_pass and response_type_pass and validator_pass and submit_pass and decision_pass
    row.update(
        {
            "expected_intent": expected_intent,
            "actual_intent": actual_intent,
            "intent_pass": intent_pass,
            "expected_decision": expected_decision,
            "actual_decision": actual_decision,
            "decision_pass": decision_pass,
            "expected_submit": expected_submit,
            "actual_submit": actual_submit,
            "submit_pass": submit_pass,
            "function_pass": function_pass,
            "args_pass": args_pass,
            "fc_pass": fc_pass,
            "db_pass": db_pass,
            "response_type_pass": response_type_pass,
            "validator_pass": validator_pass,
            "execution_pass": execution_pass,
            "e2e_pass": e2e_pass,
        }
    )
    return (e2e_pass, ";".join(unique))

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
    before_db_markers: dict[str, int] | None = None,
) -> dict[str, Any]:
    debug = response_payload.get("debug") if isinstance(response_payload.get("debug"), dict) else {}
    submit_validation = debug.get("submit_validation") if isinstance(debug.get("submit_validation"), dict) else {}
    checkin = get_checkin_result(student_id)
    db_markers = get_db_change_markers(student_id)
    before_db_markers = before_db_markers or {}
    marker_delta = {
        table: db_markers.get(table, 0) - before_db_markers.get(table, 0)
        for table in sorted(set(db_markers) | set(before_db_markers))
    }
    marker_changed = any(
        delta != 0
        for table, delta in marker_delta.items()
        if table != "pending_actions"
    )
    actual_function = infer_function(response_payload, debug, checkin, db_markers, marker_delta)
    expected_function_for_args = actual_function if actual_function != "none" else primary_expected_function(case.expected_function)
    actual_args = extract_actual_args(response_payload, debug, checkin, expected_function_for_args, case.expected_args)
    actual_db_changed = marker_changed
    if actual_function in NON_DB_FUNCTIONS and not checkin:
        # 정보 조회류는 채팅 저장 외 미션 DB 변경을 기대하지 않는다.
        actual_db_changed = False
    actual_response_type = infer_response_type(response_text, response_payload, debug, checkin, case.expected_response_type, actual_function)
    actual_intent = extract_actual_intent(response_payload, debug)
    actual_decision = extract_actual_decision(response_payload, debug)
    actual_submit = bool(checkin) or actual_function == "submit_mission_result" or bool(actual_db_changed and actual_args.get("result_type"))
    stream_after_first_ms = ""
    if first_token_ms is not None and total_elapsed_ms is not None:
        stream_after_first_ms = round(total_elapsed_ms - first_token_ms, 2)

    row = {
        "case_id": case.case_id,
        "endpoint": endpoint,
        "test_student_id": student_id,
        "mission_id": case.mission_id,
        "mission_name": case.mission_name,
        "case_type": case.case_type,
        "metric_group": case.metric_group,
        "demo_safe": str(case.demo_safe).lower(),
        "user_message": case.user_message,
        "expected_intent": case.expected_intent,
        "actual_intent": actual_intent,
        "expected_function": case.expected_function,
        "actual_function": actual_function,
        "expected_args": case.expected_args,
        "actual_args": actual_args,
        "expected_db_changed": case.expected_db_changed,
        "actual_db_changed": actual_db_changed,
        "expected_response_type": case.expected_response_type,
        "actual_response_type": actual_response_type,
        "expected_decision": case.expected_decision,
        "actual_decision": actual_decision,
        "expected_submit": case.expected_submit,
        "actual_submit": actual_submit,
        "actual_validator_action": submit_validation.get("action", ""),
        "actual_validator_result_type": submit_validation.get("result_type", ""),
        "actual_validator_reason": submit_validation.get("reason", ""),
        "actual_db_markers": {"before": before_db_markers, "after": db_markers, "delta": marker_delta},
        "elapsed_ms": elapsed_ms if elapsed_ms is not None else "",
        "first_token_ms": first_token_ms if first_token_ms is not None else "",
        "total_elapsed_ms": total_elapsed_ms if total_elapsed_ms is not None else "",
        "stream_after_first_ms": stream_after_first_ms,
        "actual_response": response_text,
        "raw_error": "",
    }
    passed, error_type = compare_result(row)
    row["pass"] = passed
    row["error_type"] = error_type
    return row


def post_chat(base_url: str, case: TestCase, timeout: int) -> dict[str, Any]:
    session_id = f"reg-chat-{case.case_id}"
    payload = {"message": case.user_message, "session_id": session_id, "mission": case.mission_name}
    before_markers = get_db_change_markers(case.chat_student_id)
    start = time.perf_counter()
    response = requests.post(f"{base_url.rstrip('/')}/chat", json=payload, timeout=timeout)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    response.raise_for_status()
    data = response.json()
    text = extract_response_text(data)
    return flatten_result(
        case=case,
        endpoint="/chat",
        student_id=case.chat_student_id,
        response_payload=data,
        response_text=text,
        elapsed_ms=elapsed_ms,
        before_db_markers=before_markers,
    )


def extract_response_text(payload: dict[str, Any]) -> str:
    for key in ("response", "message", "content", "text", "answer"):
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, str):
            return value
    return ""


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


def parse_sse_block(lines: list[str]) -> dict[str, Any] | None:
    data_parts: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(":"):
            continue
        if stripped.startswith("data:"):
            data_parts.append(stripped[5:].strip())
    if not data_parts:
        return None
    raw = "\n".join(data_parts).strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"type": "raw", "content": raw}


def merge_stream_event_payload(done_payload: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    payload = dict(done_payload or {})
    payload.setdefault("type", "done" if done_payload else "stream")
    payload["events"] = events
    pipeline_events = [event for event in events if event.get("type") == "pipeline"]
    if pipeline_events:
        payload["pipeline_events"] = pipeline_events
    if "debug" not in payload or not isinstance(payload.get("debug"), dict):
        payload["debug"] = {}
    return payload


def post_stream(base_url: str, case: TestCase, timeout: int) -> dict[str, Any]:
    session_id = f"reg-stream-{case.case_id}"
    payload = {"message": case.user_message, "session_id": session_id, "mission": case.mission_name}
    before_markers = get_db_change_markers(case.stream_student_id)
    start = time.perf_counter()
    first_token_ms: float | None = None
    tokens: list[str] = []
    events: list[dict[str, Any]] = []
    done_payload: dict[str, Any] = {}
    with requests.post(f"{base_url.rstrip('/')}/chat/stream", json=payload, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        event_lines: list[str] = []
        for raw_line in response.iter_lines(decode_unicode=True):
            if raw_line == "":
                event = parse_sse_block(event_lines)
                event_lines = []
                if not event:
                    continue
            else:
                event_lines.append(raw_line)
                continue

            events.append(event)
            if event.get("type") == "token":
                if first_token_ms is None:
                    first_token_ms = round((time.perf_counter() - start) * 1000, 2)
                tokens.append(str(event.get("content", "")))
            elif event.get("type") == "done":
                done_payload = event
            elif event.get("type") in {"message", "response"}:
                if first_token_ms is None:
                    first_token_ms = round((time.perf_counter() - start) * 1000, 2)
                tokens.append(str(event.get("content") or event.get("response") or event.get("message") or ""))

        event = parse_sse_block(event_lines)
        if event:
            events.append(event)
            if event.get("type") == "token":
                if first_token_ms is None:
                    first_token_ms = round((time.perf_counter() - start) * 1000, 2)
                tokens.append(str(event.get("content", "")))
            elif event.get("type") == "done":
                done_payload = event
            elif event.get("type") in {"message", "response"}:
                if first_token_ms is None:
                    first_token_ms = round((time.perf_counter() - start) * 1000, 2)
                tokens.append(str(event.get("content") or event.get("response") or event.get("message") or ""))
    total_elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    response_text = "".join(tokens)
    stream_payload = merge_stream_event_payload(done_payload, events)
    return flatten_result(
        case=case,
        endpoint="/chat/stream",
        student_id=case.stream_student_id,
        response_payload=stream_payload,
        response_text=response_text,
        first_token_ms=first_token_ms or total_elapsed_ms,
        total_elapsed_ms=total_elapsed_ms,
        before_db_markers=before_markers,
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
    error_type = classify_exception(exc)
    row = {
        "case_id": case.case_id,
        "endpoint": endpoint,
        "test_student_id": student_id,
        "mission_id": case.mission_id,
        "mission_name": case.mission_name,
        "case_type": case.case_type,
        "metric_group": case.metric_group,
        "demo_safe": str(case.demo_safe).lower(),
        "user_message": case.user_message,
        "expected_intent": case.expected_intent,
        "actual_intent": "",
        "expected_function": case.expected_function,
        "actual_function": "error",
        "expected_args": case.expected_args,
        "actual_args": {},
        "expected_db_changed": case.expected_db_changed,
        "actual_db_changed": False,
        "expected_response_type": case.expected_response_type,
        "actual_response_type": "error",
        "expected_decision": case.expected_decision,
        "actual_decision": "",
        "expected_submit": case.expected_submit,
        "actual_submit": False,
        "actual_validator_action": "",
        "actual_validator_result_type": "",
        "actual_validator_reason": "",
        "actual_db_markers": {},
        "elapsed_ms": "",
        "first_token_ms": "",
        "total_elapsed_ms": "",
        "stream_after_first_ms": "",
        "actual_response": repr(exc),
        "raw_error": repr(exc),
    }
    compare_result(row)
    row["pass"] = False
    row["e2e_pass"] = False
    row["error_type"] = error_type
    return row


def classify_exception(exc: Exception) -> str:
    if isinstance(exc, requests.exceptions.Timeout):
        return "REQUEST_TIMEOUT"
    if isinstance(exc, requests.exceptions.HTTPError):
        return "HTTP_ERROR"
    if isinstance(exc, requests.exceptions.RequestException):
        return "REQUEST_ERROR"
    return f"SCRIPT_ERROR:{type(exc).__name__}"


def chat_result_fields() -> list[str]:
    return [
        "case_id", "endpoint", "test_student_id", "mission_id", "mission_name", "case_type", "demo_safe",
        "user_message", "expected_intent", "actual_intent", "expected_function", "actual_function", "expected_args", "actual_args",
        "expected_db_changed", "actual_db_changed", "expected_response_type", "actual_response_type",
        "expected_decision", "actual_decision", "expected_submit", "actual_submit",
        "actual_validator_action", "actual_validator_result_type", "actual_validator_reason", "actual_db_markers",
        "intent_pass", "decision_pass", "submit_pass", "function_pass", "args_pass", "fc_pass", "db_pass", "response_type_pass",
        "validator_pass", "execution_pass", "e2e_pass", "metric_group",
        "elapsed_ms", "pass", "error_type", "actual_response", "raw_error",
    ]


def stream_result_fields() -> list[str]:
    return [
        "case_id", "endpoint", "test_student_id", "mission_id", "mission_name", "case_type", "demo_safe",
        "user_message", "expected_intent", "actual_intent", "expected_function", "actual_function", "expected_args", "actual_args",
        "expected_db_changed", "actual_db_changed", "expected_response_type", "actual_response_type",
        "expected_decision", "actual_decision", "expected_submit", "actual_submit",
        "actual_validator_action", "actual_validator_result_type", "actual_validator_reason", "actual_db_markers",
        "intent_pass", "decision_pass", "submit_pass", "function_pass", "args_pass", "fc_pass", "db_pass", "response_type_pass",
        "validator_pass", "execution_pass", "e2e_pass", "metric_group",
        "first_token_ms", "total_elapsed_ms", "stream_after_first_ms", "pass", "error_type", "actual_response", "raw_error",
    ]


def read_result_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


RESULT_FILE_NAMES = [
    "demo_test_results_chat.csv",
    "demo_test_results_stream.csv",
    "failure_cases.csv",
    "demo_safe_cases.csv",
    "regression_summary.md",
]


def reset_results(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    removed = []
    for name in RESULT_FILE_NAMES:
        path = output_dir / name
        if path.exists():
            path.unlink()
            removed.append(name)
    print(f"[reset-results] 삭제: {', '.join(removed) if removed else '없음'}")


def selected_setup_endpoints(args: argparse.Namespace) -> set[str]:
    if args.run:
        return {"chat", "stream"}
    endpoints: set[str] = set()
    if args.run_chat:
        endpoints.add("chat")
    if args.run_stream:
        endpoints.add("stream")
    return endpoints or {"chat", "stream"}


def ensure_result_metrics(row: dict[str, Any], case: TestCase | None = None) -> None:
    if case:
        row.setdefault("expected_intent", case.expected_intent)
        row.setdefault("metric_group", case.metric_group)
        row.setdefault("expected_decision", case.expected_decision)
        row.setdefault("expected_submit", case.expected_submit)
    row["expected_intent"] = row.get("expected_intent") or "ANY"
    row["metric_group"] = row.get("metric_group") or row.get("case_type") or "default"
    row.setdefault("actual_intent", "")
    row.setdefault("expected_decision", "")
    row.setdefault("actual_decision", "")
    row.setdefault("actual_submit", "")
    compare_result(row)
    row["pass"] = row.get("e2e_pass", False)


def report(cases: list[TestCase], output_dir: Path) -> None:
    chat_rows = read_result_csv(output_dir / "demo_test_results_chat.csv")
    stream_rows = read_result_csv(output_dir / "demo_test_results_stream.csv")
    case_by_id = {case.case_id: case for case in cases}
    for row in [*chat_rows, *stream_rows]:
        ensure_result_metrics(row, case_by_id.get(row.get("case_id", "")))
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
    expected = (
        f"intent={row.get('expected_intent', 'ANY')} / "
        f"{row.get('expected_function')} / {row.get('expected_args')} / "
        f"db_changed={row.get('expected_db_changed')} / {row.get('expected_response_type')} / "
        f"submit={row.get('expected_submit', '')} / decision={row.get('expected_decision', '')}"
    )
    actual = (
        f"intent={row.get('actual_intent', '')} / "
        f"{row.get('actual_function')} / {row.get('actual_args')} / "
        f"db_changed={row.get('actual_db_changed')} / {row.get('actual_response_type')} / "
        f"submit={row.get('actual_submit', '')} / decision={row.get('actual_decision', '')}"
    )
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
        return "A non-submit utterance wrote mission result data."
    if "SUBMIT_FAILED" in error_type:
        return "An expected submit did not execute."
    if "WRONG_RESULT" in error_type:
        return "The submitted success/fail result may be inverted."
    if "NO_DB_BUT_CONFIRM_ACK" in error_type:
        return "The response confirmed completion without a DB change."
    if "STREAM_ONLY_ERROR" in error_type:
        return "/chat passed but /chat/stream diverged."
    if "VALIDATOR_MISMATCH" in error_type:
        return "submit validator의 execute/clarify/block 판단이 기대와 다름"
    if "WRONG_DECISION" in error_type:
        return "동치 판정 decision이 기대와 달라 잘못 인정하거나 거절할 수 있음"
    return "기대 결과와 실제 결과가 일치하지 않음"


def suggested_owner(error_type: str, case_type: str) -> str:
    if case_type == "equivalency" or "equivalency" in case_type:
        return "function-routing"
    if any(key in error_type for key in ["UNEXPECTED_SUBMIT", "SUBMIT_FAILED", "WRONG_RESULT", "VALIDATOR_MISMATCH", "NO_DB_BUT_CONFIRM_ACK"]):
        return "execution-validator"
    return "response-quality"


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


def format_ms(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{round(value, 2)}ms"


def ratio_line(label: str, numerator: int, denominator: int) -> str:
    pct = round((numerator / denominator) * 100, 2) if denominator else None
    pct_text = f"{pct}%" if pct is not None else "N/A"
    return f"- {label}: {numerator}/{denominator} ({pct_text})"


def pass_rate(rows: list[dict[str, Any]], pass_field: str, denominator_filter=None) -> tuple[int, int]:
    selected = [row for row in rows if denominator_filter is None or denominator_filter(row)]
    return sum(1 for row in selected if parse_bool(row.get(pass_field))), len(selected)


def has_expected_args(row: dict[str, Any]) -> bool:
    return bool(parse_jsonish(row.get("expected_args")))


def group_rate_lines(
    rows: list[dict[str, Any]],
    group_field: str,
    pass_field: str,
    *,
    label: str,
    default: str = "default",
) -> list[str]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get(group_field) or default)
        groups.setdefault(key, []).append(row)
    lines = [f"## {label}"]
    if not groups:
        return [*lines, "- No rows"]
    for key in sorted(groups):
        numerator, denominator = pass_rate(groups[key], pass_field)
        pct = round((numerator / denominator) * 100, 2) if denominator else None
        pct_text = f"{pct}%" if pct is not None else "N/A"
        lines.append(f"- {key}: {numerator}/{denominator} ({pct_text})")
    return lines


def build_time_summary(chat_rows: list[dict[str, Any]], stream_rows: list[dict[str, Any]], failures: list[dict[str, Any]], safe_rows: list[dict[str, Any]]) -> str:
    all_rows = [*chat_rows, *stream_rows]
    chat_elapsed = [v for v in (to_float(r.get("elapsed_ms")) for r in chat_rows) if v is not None]
    stream_first = [v for v in (to_float(r.get("first_token_ms")) for r in stream_rows) if v is not None]
    stream_total = [v for v in (to_float(r.get("total_elapsed_ms")) for r in stream_rows) if v is not None]
    chat_stats = stats(chat_elapsed)
    stream_first_stats = stats(stream_first)
    stream_total_stats = stats(stream_total)
    stream_after_first = []
    for row in stream_rows:
        after_first = to_float(row.get("stream_after_first_ms"))
        if after_first is None:
            first_token_ms = to_float(row.get("first_token_ms"))
            total_elapsed_ms = to_float(row.get("total_elapsed_ms"))
            if first_token_ms is not None and total_elapsed_ms is not None:
                after_first = total_elapsed_ms - first_token_ms
        if after_first is not None:
            stream_after_first.append(after_first)
    stream_after_first_stats = stats(stream_after_first)

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

    intent_num, intent_den = pass_rate(
        all_rows,
        "intent_pass",
        lambda row: str(row.get("expected_intent") or "ANY").strip().upper() != "ANY",
    )
    function_num, function_den = pass_rate(all_rows, "function_pass")
    args_num, args_den = pass_rate(all_rows, "args_pass", has_expected_args)
    fc_num, fc_den = pass_rate(all_rows, "fc_pass")
    submit_num, submit_den = pass_rate(all_rows, "submit_pass")
    decision_num, decision_den = pass_rate(
        all_rows,
        "decision_pass",
        lambda row: bool(str(row.get("expected_decision") or "").strip()),
    )
    execution_num, execution_den = pass_rate(all_rows, "execution_pass")
    db_change_num, db_change_den = pass_rate(
        all_rows,
        "actual_db_changed",
        lambda row: parse_bool(row.get("expected_db_changed")),
    )
    db_no_change_num, db_no_change_den = pass_rate(
        all_rows,
        "db_pass",
        lambda row: not parse_bool(row.get("expected_db_changed")),
    )
    e2e_num, e2e_den = pass_rate(all_rows, "e2e_pass")

    lines = [
        "# Regression Summary",
        "",
        f"- /chat rows: {len(chat_rows)}",
        f"- /chat/stream rows: {len(stream_rows)}",
        f"- failure rows: {len(failures)}",
        f"- demo safe rows: {len(safe_rows)}",
        "",
        "## Response Time",
        f"- /chat elapsed_ms: avg={chat_stats['avg']}, min={chat_stats['min']}, max={chat_stats['max']}",
        f"- /chat/stream first_token_ms: avg={stream_first_stats['avg']}, min={stream_first_stats['min']}, max={stream_first_stats['max']}",
        f"- /chat/stream total_elapsed_ms: avg={stream_total_stats['avg']}, min={stream_total_stats['min']}, max={stream_total_stats['max']}",
        f"- /chat/stream after_first_ms (total - first token): avg={stream_after_first_stats['avg']}, min={stream_after_first_stats['min']}, max={stream_after_first_stats['max']}",
        f"- /chat/stream user-visible timeline: first={format_ms(stream_first_stats['avg'])}, after_first={format_ms(stream_after_first_stats['avg'])}, total={format_ms(stream_total_stats['avg'])}",
        "",
        "## Slow Cases TOP 5",
        *(slow_lines or ["- No timing rows"]),
        "",
        "## Accuracy",
        ratio_line("Intent classification accuracy (expected_intent != ANY)", intent_num, intent_den),
        ratio_line("Function Calling accuracy (includes expected_function=none)", function_num, function_den),
        ratio_line("Args accuracy (rows with expected_args only)", args_num, args_den),
        ratio_line("FC+Args accuracy", fc_num, fc_den),
        ratio_line("Submit status accuracy", submit_num, submit_den),
        ratio_line("Equivalency decision accuracy (expected_decision present)", decision_num, decision_den),
        ratio_line("Execution accuracy", execution_num, execution_den),
        ratio_line("DB change success rate (expected_db_changed=true)", db_change_num, db_change_den),
        ratio_line("DB no-change compliance (expected_db_changed=false)", db_no_change_num, db_no_change_den),
        ratio_line("End-to-End success rate", e2e_num, e2e_den),
        "",
        *group_rate_lines(all_rows, "metric_group", "e2e_pass", label="metric_group E2E"),
        "",
        *group_rate_lines(all_rows, "case_type", "e2e_pass", label="case_type E2E", default=""),
        "",
        *group_rate_lines(all_rows, "expected_function", "function_pass", label="expected_function Function Calling", default="none"),
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run answer regression tests")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--base-url", default=os.getenv("REGRESSION_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("REGRESSION_TIMEOUT", "180")))
    parser.add_argument("--limit", type=int, default=None, help="Run/report only the first N cases")
    parser.add_argument("--reset-results", action="store_true", help="Delete previous regression result files")
    parser.add_argument("--reset", action="store_true", help="Delete existing regression DB data before starting")
    parser.add_argument("--setup", action="store_true", help="Create test students and assign today's missions")
    parser.add_argument("--run-chat", action="store_true", help="Run /chat regression cases")
    parser.add_argument("--run-stream", action="store_true", help="Run /chat/stream regression cases")
    parser.add_argument("--run", action="store_true", help="Run both /chat and /chat/stream regression cases")
    parser.add_argument("--report", action="store_true", help="Generate comparison CSVs and summary report")
    parser.add_argument("--cleanup", action="store_true", help="Delete regression DB data")
    parser.add_argument("--force-cleanup", action="store_true", help="Cleanup even when failures exist")
    args = parser.parse_args()

    load_env()
    cases = load_cases(args.cases)
    if args.limit is not None:
        if args.limit <= 0:
            raise ValueError("--limit must be a positive integer")
        cases = cases[: args.limit]
        print(f"[limit] using first {len(cases)} cases")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.reset_results:
        reset_results(args.output_dir)

    if args.reset:
        cleanup_test_data(force=True)

    if args.setup:
        setup(cases, selected_setup_endpoints(args))

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
                    print(f"[cleanup] skipped because {failure_count} failure rows exist. Add --force-cleanup to override.")
                    return
        cleanup_test_data(force=args.force_cleanup)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted")
        sys.exit(130)
