import os
from datetime import datetime, timezone, timedelta

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ModuleNotFoundError as e:
    gspread = None
    Credentials = None
    print(f"[Sheets] Google Sheets dependency 없음 - 시트 동기화 비활성화: {e}")

KST = timezone(timedelta(hours=9))

SPREADSHEET_ID = os.environ.get("GOOGLE_SPREADSHEET_ID", "")
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "google_credentials.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
WORKSHEET_NOT_FOUND = gspread.WorksheetNotFound if gspread is not None else Exception

DAILY_STATUS_HEADERS = [
    "student_id", "student_name", "age", "gender", "location",
    "mission_id", "mission_name", "category", "difficulty",
    "status", "result_reason", "ai_response", "sheet_updated_at",
]

KEYWORDS_COMPLETED = [
    "완료", "다 했", "다했", "성공", "마셨", "먹었", "걸었", "했어", "했어요",
    "다 마셨", "끝났", "끝냈", "달성", "해냈", "해냈어",
]
KEYWORDS_FAILED = [
    "실패", "못했", "못 했", "안했", "안 했", "못하", "못 하", "안해", "포기",
    "조금", "반만", "절반", "부분", "조금만", "일부", "반쯤", "절반만", "조금밖에",
]


def _get_spreadsheet():
    if not SPREADSHEET_ID or gspread is None or Credentials is None:
        return None
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)


def detect_mission_status(user_message: str) -> str | None:
    """유저 메시지에서 미션 결과 감지. success / fail / None"""
    if any(kw in user_message for kw in KEYWORDS_FAILED):
        return "fail"
    if any(kw in user_message for kw in KEYWORDS_COMPLETED):
        return "success"
    return None


def detect_mission_completed(user_message: str) -> bool:
    return detect_mission_status(user_message) is not None


def generate_daily_status(today: str) -> int:
    """
    날짜 탭(예: 2026-03-29)을 생성하고 DB students 테이블의 is_active 학생 전체를 추가
    탭이 이미 있으면 없는 학생만 추가
    """
    from database import get_conn
    import psycopg2.extras

    # DB에서 활성 학생 목록 가져오기
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM students WHERE is_active = TRUE ORDER BY student_id")
            students = [dict(r) for r in cur.fetchall()]

    ss = _get_spreadsheet()
    if ss is None:
        return 0
    try:
        sheet = ss.worksheet(today)
        existing_ids = {str(r["student_id"]) for r in sheet.get_all_records()}
    except WORKSHEET_NOT_FOUND:
        sheet = ss.add_worksheet(title=today, rows=200, cols=len(DAILY_STATUS_HEADERS))
        sheet.append_row(DAILY_STATUS_HEADERS)
        existing_ids = set()

    added = 0
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    for s in students:
        if str(s["student_id"]) in existing_ids:
            continue
        new_row = [""] * len(DAILY_STATUS_HEADERS)
        field_map = {
            "student_id":       s["student_id"],
            "student_name":     s["student_name"],
            "age":              s["age"],
            "gender":           s["gender"],
            "location":         s["location"],
            "status":           "assigned",
            "sheet_updated_at": now,
        }
        for col, val in field_map.items():
            if col in DAILY_STATUS_HEADERS:
                new_row[DAILY_STATUS_HEADERS.index(col)] = val
        sheet.append_row(new_row)
        added += 1

    return added

# 오늘 날짜 탭에서 student_id 행의 결과를 초기화 (status → assigned, result_reason 비움)
def cancel_mission_result(student_id: int, today: str):
    if not SPREADSHEET_ID:
        return

    ss = _get_spreadsheet()
    if ss is None:
        return
    try:
        sheet = ss.worksheet(today)
    except WORKSHEET_NOT_FOUND:
        return

    all_rows = sheet.get_all_values()
    headers = all_rows[0] if all_rows else DAILY_STATUS_HEADERS
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

    try:
        col_student_id    = headers.index("student_id") + 1
        col_status        = headers.index("status") + 1
        col_result_reason = headers.index("result_reason") + 1
        col_updated_at    = headers.index("sheet_updated_at") + 1
        col_ai_response   = headers.index("ai_response") + 1 if "ai_response" in headers else None
    except ValueError:
        return

    for i, row in enumerate(all_rows[1:], start=2):
        row_student_id = row[col_student_id - 1] if len(row) >= col_student_id else ""
        if str(row_student_id) == str(student_id):
            sheet.update_cell(i, col_status,        "assigned")
            sheet.update_cell(i, col_result_reason, "")
            if col_ai_response:
                sheet.update_cell(i, col_ai_response, "")
            sheet.update_cell(i, col_updated_at,    now)
            return


def _get_or_create_daily_sheet(ss, today: str):
    try:
        return ss.worksheet(today)
    except WORKSHEET_NOT_FOUND:
        sheet = ss.add_worksheet(title=today, rows=200, cols=len(DAILY_STATUS_HEADERS))
        sheet.append_row(DAILY_STATUS_HEADERS)
        return sheet


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
   # 오늘 날짜 탭에서 student_id 행 찾아서 업데이트(없으면 새 행 추가)
    if not SPREADSHEET_ID:
        return

    ss = _get_spreadsheet()
    if ss is None:
        return
    sheet = _get_or_create_daily_sheet(ss, today)
    all_rows = sheet.get_all_values()
    headers = all_rows[0] if all_rows else DAILY_STATUS_HEADERS
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

    try:
        col_student_id    = headers.index("student_id") + 1
        col_status        = headers.index("status") + 1
        col_result_reason = headers.index("result_reason") + 1
        col_ai_response   = headers.index("ai_response") + 1
        col_updated_at    = headers.index("sheet_updated_at") + 1
    except ValueError:
        return

    for i, row in enumerate(all_rows[1:], start=2):
        row_student_id = row[col_student_id - 1] if len(row) >= col_student_id else ""
        if str(row_student_id) == str(student_id):
            sheet.update_cell(i, col_status,        status)
            sheet.update_cell(i, col_result_reason, result_reason)
            sheet.update_cell(i, col_ai_response,   ai_response)
            sheet.update_cell(i, col_updated_at,    now)
            return

    # 없으면 새 행 추가
    new_row = [""] * len(headers)
    field_map = {
        "student_id": student_id, "student_name": student_name,
        "age": age, "gender": gender, "location": location,
        "mission_id": mission_id, "mission_name": mission_name,
        "category": category, "difficulty": difficulty,
        "status": status, "result_reason": result_reason,
        "ai_response": ai_response, "sheet_updated_at": now,
    }
    for col_name, value in field_map.items():
        if col_name in headers:
            new_row[headers.index(col_name)] = value if value is not None else ""
    sheet.append_row(new_row)
