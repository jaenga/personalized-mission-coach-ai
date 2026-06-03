import os
from datetime import datetime, timedelta, timezone

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ModuleNotFoundError as e:
    gspread = None
    Credentials = None
    print(f"[Sheets] Google Sheets dependency missing - sync disabled: {e}")

KST = timezone(timedelta(hours=9))
TOMATO_RGB = {"red": 0.89, "green": 0.36, "blue": 0.29}  # #E35D49
LEAF_RGB = {"red": 0.48, "green": 0.75, "blue": 0.26}  # #7BC043
BODY_BG_RGB = {"red": 0.99, "green": 0.98, "blue": 0.97}
BODY_TEXT_RGB = {"red": 0.12, "green": 0.14, "blue": 0.16}
WHITE_RGB = {"red": 1, "green": 1, "blue": 1}

SPREADSHEET_ID = os.environ.get("GOOGLE_SPREADSHEET_ID", "")
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "google_credentials.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
WORKSHEET_NOT_FOUND = gspread.WorksheetNotFound if gspread is not None else Exception

STUDENT_INFO_SHEET_TITLE = os.environ.get("GOOGLE_STUDENT_INFO_SHEET_TITLE", "학생 등록 정보")

DAILY_STATUS_HEADERS = [
    "student_id",
    "학생 이름",
    "날짜",
    "미션명",
    "현재 상태 (성공여부)",
    "변경 여부",
    "변경 전 미션명",
    "변경 사유",
    "처리 시간",
]

STUDENT_INFO_HEADERS = [
    "student_id",
    "학생 이름",
    "전화번호",
    "생년월일",
    "나이",
    "성별",
    "활성 여부",
    "학생 메모",
]


def _now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def _get_spreadsheet():
    if not SPREADSHEET_ID or gspread is None or Credentials is None:
        return None
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)


def _show_student_id_column(sheet) -> None:
    try:
        sheet.spreadsheet.batch_update({
            "requests": [
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet.id,
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": 1,
                        },
                        "properties": {"hiddenByUser": False},
                        "fields": "hiddenByUser",
                    }
                }
            ]
        })
    except Exception:
        pass


def _resize_columns(sheet, header_count: int) -> None:
    try:
        sheet.resize(cols=header_count)
    except Exception:
        pass


def _ensure_grid_size(sheet, min_rows: int, min_cols: int | None = None) -> None:
    try:
        rows = max(int(getattr(sheet, "row_count", 0) or 0), min_rows)
        cols = max(int(getattr(sheet, "col_count", 0) or 0), min_cols or 0)
        kwargs = {"rows": rows}
        if min_cols is not None:
            kwargs["cols"] = cols
        sheet.resize(**kwargs)
    except Exception:
        pass


def _apply_sheet_layout(sheet, headers: list[str]) -> None:
    column_widths = {
        "student_id": 90,
        "학생 이름": 150,
        "날짜": 120,
        "미션명": 360,
        "현재 상태 (성공여부)": 170,
        "변경 여부": 105,
        "변경 전 미션명": 300,
        "변경 사유": 150,
        "처리 시간": 180,
        "전화번호": 140,
        "생년월일": 130,
        "나이": 90,
        "성별": 90,
        "활성 여부": 110,
        "학생 메모": 280,
    }
    try:
        requests = [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet.id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": TOMATO_RGB,
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment": "MIDDLE",
                            "textFormat": {
                                "bold": True,
                                "fontSize": 10,
                                "foregroundColor": WHITE_RGB,
                            },
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,textFormat)",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet.id,
                        "startRowIndex": 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": BODY_BG_RGB,
                            "verticalAlignment": "MIDDLE",
                            "wrapStrategy": "WRAP",
                            "textFormat": {
                                "fontSize": 10,
                                "foregroundColor": BODY_TEXT_RGB,
                            },
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,verticalAlignment,wrapStrategy,textFormat)",
                }
            },
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet.id,
                        "gridProperties": {"frozenRowCount": 1},
                    },
                    "fields": "gridProperties.frozenRowCount",
                }
            },
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet.id,
                        "dimension": "ROWS",
                        "startIndex": 0,
                        "endIndex": 1,
                    },
                    "properties": {"pixelSize": 34},
                    "fields": "pixelSize",
                }
            },
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet.id,
                        "dimension": "ROWS",
                        "startIndex": 1,
                    },
                    "properties": {"pixelSize": 30},
                    "fields": "pixelSize",
                }
            },
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet.id,
                        "dimension": "COLUMNS",
                        "startIndex": 0,
                        "endIndex": 1,
                    },
                    "properties": {"hiddenByUser": False},
                    "fields": "hiddenByUser",
                }
            },
        ]
        for idx, header in enumerate(headers):
            requests.append({
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet.id,
                        "dimension": "COLUMNS",
                        "startIndex": idx,
                        "endIndex": idx + 1,
                    },
                    "properties": {"pixelSize": column_widths.get(header, 160)},
                    "fields": "pixelSize",
                }
            })
            if header in {"날짜", "현재 상태 (성공여부)", "변경 여부", "처리 시간", "전화번호", "생년월일", "나이", "성별", "활성 여부"}:
                requests.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet.id,
                            "startRowIndex": 1,
                            "startColumnIndex": idx,
                            "endColumnIndex": idx + 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "horizontalAlignment": "CENTER",
                            }
                        },
                        "fields": "userEnteredFormat.horizontalAlignment",
                    }
                })
            elif header in {"미션명", "변경 전 미션명", "변경 사유", "학생 메모"}:
                requests.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet.id,
                            "startRowIndex": 1,
                            "startColumnIndex": idx,
                            "endColumnIndex": idx + 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "horizontalAlignment": "LEFT",
                            }
                        },
                        "fields": "userEnteredFormat.horizontalAlignment",
                    }
                })
        sheet.spreadsheet.batch_update({"requests": requests})
    except Exception:
        pass


def _get_or_create_sheet(ss, title: str, headers: list[str], rows: int = 500):
    try:
        sheet = ss.worksheet(title)
    except WORKSHEET_NOT_FOUND:
        sheet = ss.add_worksheet(title=title, rows=rows, cols=len(headers))
        sheet.update("A1", [headers])
        _apply_sheet_layout(sheet, headers)
        _show_student_id_column(sheet)
        return sheet

    values = sheet.get_all_values()
    if not values:
        sheet.update("A1", [headers])
    elif values[0] != headers:
        sheet.update("A1", [headers])
    _resize_columns(sheet, len(headers))
    _apply_sheet_layout(sheet, headers)
    _show_student_id_column(sheet)
    return sheet


def _find_row_by_student_id(sheet, headers: list[str], student_id: int) -> int | None:
    values = sheet.get_all_values()
    if not values:
        return None
    try:
        student_id_idx = headers.index("student_id")
    except ValueError:
        return None
    for row_no, row in enumerate(values[1:], start=2):
        value = row[student_id_idx] if len(row) > student_id_idx else ""
        if str(value) == str(student_id):
            return row_no
    return None


def _row_value(row: list[str], idx: int) -> str:
    return row[idx] if len(row) > idx else ""


def _append_row_at_column_a(sheet, row_values: list) -> int:
    next_row = len(sheet.get_all_values()) + 1
    _ensure_grid_size(sheet, next_row, len(row_values))
    sheet.update(f"A{next_row}", [row_values])
    return next_row


def _sort_by_student_id(sheet, headers: list[str]) -> None:
    values = sheet.get_all_values()
    if len(values) <= 2:
        return
    try:
        student_id_idx = headers.index("student_id")
        sheet.spreadsheet.batch_update({
            "requests": [
                {
                    "sortRange": {
                        "range": {
                            "sheetId": sheet.id,
                            "startRowIndex": 1,
                            "endRowIndex": len(values),
                            "startColumnIndex": 0,
                            "endColumnIndex": len(headers),
                        },
                        "sortSpecs": [
                            {
                                "dimensionIndex": student_id_idx,
                                "sortOrder": "ASCENDING",
                            }
                        ],
                    }
                }
            ]
        })
    except Exception:
        pass


def _rewrite_sheet(sheet, values: list[list], headers: list[str]) -> None:
    sheet.clear()
    row_count = max(len(values), 2)
    try:
        sheet.resize(rows=row_count, cols=len(headers))
    except Exception:
        pass
    sheet.update("A1", values)
    _resize_columns(sheet, len(headers))
    _apply_sheet_layout(sheet, headers)


def _find_daily_row(sheet, student_id: int, student_name: str, today: str) -> int | None:
    row_no = _find_row_by_student_id(sheet, DAILY_STATUS_HEADERS, student_id)
    if row_no:
        return row_no

    values = sheet.get_all_values()
    try:
        name_idx = DAILY_STATUS_HEADERS.index("학생 이름")
        date_idx = DAILY_STATUS_HEADERS.index("날짜")
    except ValueError:
        return None

    for candidate_row_no, row in enumerate(values[1:], start=2):
        if _row_value(row, name_idx) == str(student_name) and _row_value(row, date_idx) == str(today):
            return candidate_row_no
    return None


def _find_student_info_row(sheet, student: dict) -> int | None:
    row_no = _find_row_by_student_id(sheet, STUDENT_INFO_HEADERS, student.get("student_id"))
    if row_no:
        return row_no

    values = sheet.get_all_values()
    try:
        name_idx = STUDENT_INFO_HEADERS.index("학생 이름")
        phone_idx = STUDENT_INFO_HEADERS.index("전화번호")
    except ValueError:
        return None

    student_name = str(student.get("student_name", ""))
    phone_number = str(student.get("phone_number", ""))
    for candidate_row_no, row in enumerate(values[1:], start=2):
        if _row_value(row, name_idx) == student_name and _row_value(row, phone_idx) == phone_number:
            return candidate_row_no
    return None


def _format_bool(value) -> str:
    return "TRUE" if bool(value) else "FALSE"


def _format_timestamp(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(KST)
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _display_status(status: str | None) -> str:
    labels = {
        "assigned": "미션 배정",
        "success": "성공",
        "fail": "실패",
        "failed": "실패",
    }
    return labels.get((status or "").strip().lower(), status or "미션 배정")


def _display_changed(changed: bool) -> str:
    return "O" if changed else "-"


def _display_change_reason(reason_type: str | None) -> str:
    labels = {
        "too_hard": "어려움",
        "dislike": "싫어함",
        "cant_do": "수행 불가",
        "just_change": "변경 요청",
        "onboarding_auto_replace": "온보딩 자동 변경",
        "personalized_change": "개인화 변경",
        "generated_change": "생성 미션 변경",
    }
    return labels.get((reason_type or "").strip(), reason_type or "")


def _status_cell_format(status: str | None) -> dict:
    normalized = (status or "").strip().lower()
    if normalized in {"성공", "success"}:
        return {
            "backgroundColor": LEAF_RGB,
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
            "textFormat": {"bold": True, "foregroundColor": WHITE_RGB},
        }
    if normalized in {"실패", "fail", "failed"}:
        return {
            "backgroundColor": TOMATO_RGB,
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
            "textFormat": {"bold": True, "foregroundColor": WHITE_RGB},
        }
    return {
        "backgroundColor": BODY_BG_RGB,
        "horizontalAlignment": "CENTER",
        "verticalAlignment": "MIDDLE",
        "textFormat": {"bold": False, "foregroundColor": BODY_TEXT_RGB},
    }


def _format_status_cells(sheet, headers: list[str], row_statuses: list[tuple[int, str]]) -> None:
    if not row_statuses:
        return
    try:
        status_idx = headers.index("현재 상태 (성공여부)")
    except ValueError:
        return
    requests = []
    for row_no, status in row_statuses:
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet.id,
                    "startRowIndex": row_no - 1,
                    "endRowIndex": row_no,
                    "startColumnIndex": status_idx,
                    "endColumnIndex": status_idx + 1,
                },
                "cell": {"userEnteredFormat": _status_cell_format(status)},
                "fields": (
                    "userEnteredFormat(backgroundColor,horizontalAlignment,"
                    "verticalAlignment,textFormat)"
                ),
            }
        })
    try:
        sheet.spreadsheet.batch_update({"requests": requests})
    except Exception as e:
        print(f"[sheets] status format failed: {e}")


def _format_all_daily_status_cells(sheet) -> None:
    values = sheet.get_all_values()
    if len(values) <= 1:
        return
    try:
        status_idx = DAILY_STATUS_HEADERS.index("현재 상태 (성공여부)")
    except ValueError:
        return

    row_statuses = []
    for row_no, row in enumerate(values[1:], start=2):
        status = row[status_idx] if len(row) > status_idx else ""
        row_statuses.append((row_no, status))
    _format_status_cells(sheet, DAILY_STATUS_HEADERS, row_statuses)


def _latest_change_info(student_id: int, today: str) -> tuple[bool, str, str]:
    from database import get_conn
    import psycopg2.extras

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    old_m.mission_name AS old_mission_name,
                    (
                        SELECT mcl.reason_type
                        FROM mission_change_logs mcl
                        WHERE mcl.student_id = mc.student_id
                          AND mcl.created_at::date = mc.change_date
                        ORDER BY mcl.created_at DESC
                        LIMIT 1
                    ) AS reason_type
                FROM mission_changes mc
                LEFT JOIN missions old_m ON old_m.mission_id = mc.old_mission_id
                WHERE mc.student_id = %s
                  AND mc.change_date = %s::date
                ORDER BY mc.created_at DESC
                LIMIT 1
                """,
                (student_id, today),
            )
            row = cur.fetchone()
    if not row:
        return False, "", ""
    return True, row.get("old_mission_name") or "", _display_change_reason(row.get("reason_type"))


def upsert_daily_status_row(
    student_id: int,
    today: str,
    student_name: str = "",
    mission_name: str = "",
    status: str = "assigned",
    changed: bool = False,
    previous_mission_name: str = "",
    change_reason: str = "",
):
    if not SPREADSHEET_ID:
        return

    ss = _get_spreadsheet()
    if ss is None:
        return

    sheet = _get_or_create_sheet(ss, today, DAILY_STATUS_HEADERS)
    row_values = [
        student_id,
        student_name,
        today,
        mission_name,
        _display_status(status),
        _display_changed(changed),
        previous_mission_name or "",
        change_reason or "",
        _now_kst(),
    ]

    row_no = _find_daily_row(sheet, student_id, student_name, today)
    if row_no:
        sheet.update(f"A{row_no}", [row_values])
    else:
        row_no = _append_row_at_column_a(sheet, row_values)
    _sort_by_student_id(sheet, DAILY_STATUS_HEADERS)
    _format_all_daily_status_cells(sheet)


def sync_daily_status_for_student(
    student_id: int,
    today: str | None = None,
    *,
    changed: bool | None = None,
    previous_mission_name: str | None = None,
    change_reason: str | None = None,
):
    if not student_id:
        return

    from database import _kst_today, get_student_info_db, get_student_mission_db

    today = today or _kst_today()
    student = get_student_info_db(student_id) or {}
    mission = get_student_mission_db(student_id, today) or {}
    inferred_changed, inferred_previous_mission, inferred_change_reason = _latest_change_info(student_id, today)

    upsert_daily_status_row(
        student_id=student_id,
        today=today,
        student_name=student.get("student_name", ""),
        mission_name=mission.get("mission_name", ""),
        status=mission.get("status", "assigned"),
        changed=inferred_changed if changed is None else changed,
        previous_mission_name=(
            inferred_previous_mission
            if previous_mission_name is None
            else previous_mission_name
        ),
        change_reason=(
            inferred_change_reason
            if change_reason is None
            else change_reason
        ),
    )


def generate_daily_status(today: str) -> int:
    if not SPREADSHEET_ID:
        return 0

    from database import get_conn
    import psycopg2.extras

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    s.student_id,
                    s.student_name,
                    sdm.status,
                    sdm.updated_at AS sdm_updated_at,
                    m.mission_name,
                    old_m.mission_name AS old_mission_name,
                    latest_change.changed_at AS change_at,
                    latest_reason.reason_type AS reason_type
                FROM students s
                LEFT JOIN student_daily_missions sdm
                  ON sdm.student_id = s.student_id
                 AND sdm.assigned_date = %s::date
                LEFT JOIN missions m ON m.mission_id = sdm.mission_id
                LEFT JOIN LATERAL (
                    SELECT mc.old_mission_id, mc.created_at AS changed_at
                    FROM mission_changes mc
                    WHERE mc.student_id = s.student_id
                      AND mc.change_date = %s::date
                    ORDER BY mc.created_at DESC
                    LIMIT 1
                ) latest_change ON TRUE
                LEFT JOIN missions old_m ON old_m.mission_id = latest_change.old_mission_id
                LEFT JOIN LATERAL (
                    SELECT mcl.reason_type
                    FROM mission_change_logs mcl
                    WHERE mcl.student_id = s.student_id
                      AND mcl.created_at::date = %s::date
                    ORDER BY mcl.created_at DESC
                    LIMIT 1
                ) latest_reason ON TRUE
                WHERE s.is_active = TRUE
                ORDER BY s.student_id
                """,
                (today, today, today),
            )
            rows = [dict(r) for r in cur.fetchall()]

    ss = _get_spreadsheet()
    if ss is None:
        return 0

    sheet = _get_or_create_sheet(ss, today, DAILY_STATUS_HEADERS)
    existing_ids = {
        str(row.get("student_id"))
        for row in sheet.get_all_records()
        if row.get("student_id") not in (None, "")
    }

    new_values = [DAILY_STATUS_HEADERS]
    for row in rows:
        changed = bool(row.get("old_mission_name"))
        display_status = _display_status(row.get("status"))
        candidates = [row.get("sdm_updated_at"), row.get("change_at")]
        candidates = [c for c in candidates if c is not None]
        row_timestamp = _format_timestamp(max(candidates)) if candidates else _now_kst()
        new_values.append([
            row["student_id"],
            row.get("student_name", ""),
            today,
            row.get("mission_name", ""),
            display_status,
            _display_changed(changed),
            row.get("old_mission_name") or "",
            _display_change_reason(row.get("reason_type")),
            row_timestamp,
        ])

    _rewrite_sheet(sheet, new_values, DAILY_STATUS_HEADERS)
    _format_all_daily_status_cells(sheet)

    added = sum(1 for row in rows if str(row["student_id"]) not in existing_ids)

    return added


def cancel_mission_result(student_id: int, today: str):
    sync_daily_status_for_student(student_id, today, changed=None, previous_mission_name=None)


def update_mission_result(
    student_id: int,
    today: str,
    result_reason: str,
    ai_response: str,
    status: str = "success",
    student_name: str = "",
    age: int | None = None,
    gender: str = "",
    location: str = "",
    mission_id: int | None = None,
    mission_name: str = "",
    category: str = "",
    difficulty: str = "",
):
    changed, previous_mission_name, change_reason = _latest_change_info(student_id, today)
    upsert_daily_status_row(
        student_id=student_id,
        today=today,
        student_name=student_name,
        mission_name=mission_name,
        status=status,
        changed=changed,
        previous_mission_name=previous_mission_name,
        change_reason=change_reason,
    )


def upsert_student_info(student: dict):
    if not SPREADSHEET_ID or not student:
        return

    ss = _get_spreadsheet()
    if ss is None:
        return

    sheet = _get_or_create_sheet(ss, STUDENT_INFO_SHEET_TITLE, STUDENT_INFO_HEADERS)
    row_values = [
        student.get("student_id", ""),
        student.get("student_name", ""),
        student.get("phone_number", ""),
        _format_timestamp(student.get("birth_date"))[:10],
        student.get("age", ""),
        student.get("gender", ""),
        _format_bool(student.get("is_active")),
        student.get("student_note", ""),
    ]

    row_no = _find_student_info_row(sheet, student)
    if row_no:
        sheet.update(f"A{row_no}", [row_values])
    else:
        _append_row_at_column_a(sheet, row_values)
    _sort_by_student_id(sheet, STUDENT_INFO_HEADERS)


def sync_student_info(student_id: int):
    if not student_id:
        return
    from database import get_student_info_db

    student = get_student_info_db(student_id)
    if student:
        upsert_student_info(student)


def sync_all_student_info() -> int:
    if not SPREADSHEET_ID:
        return 0

    from database import get_conn
    import psycopg2.extras

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM students WHERE is_active = TRUE ORDER BY student_id")
            students = [dict(row) for row in cur.fetchall()]

    ss = _get_spreadsheet()
    if ss is None:
        return 0

    values = [STUDENT_INFO_HEADERS]
    for student in students:
        values.append([
            student.get("student_id", ""),
            student.get("student_name", ""),
            student.get("phone_number", ""),
            _format_timestamp(student.get("birth_date"))[:10],
            student.get("age", ""),
            student.get("gender", ""),
            _format_bool(student.get("is_active")),
            student.get("student_note", ""),
        ])

    sheet = _get_or_create_sheet(ss, STUDENT_INFO_SHEET_TITLE, STUDENT_INFO_HEADERS)
    _rewrite_sheet(sheet, values, STUDENT_INFO_HEADERS)
    return len(students)


def delete_student_info(student_id: int):
    if not SPREADSHEET_ID or not student_id:
        return

    ss = _get_spreadsheet()
    if ss is None:
        return

    try:
        sheet = ss.worksheet(STUDENT_INFO_SHEET_TITLE)
    except WORKSHEET_NOT_FOUND:
        return

    row_no = _find_row_by_student_id(sheet, STUDENT_INFO_HEADERS, student_id)
    if row_no:
        sheet.delete_rows(row_no)
