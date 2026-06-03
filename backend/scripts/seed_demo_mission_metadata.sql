-- demo_mission 시트 메타데이터 일괄 적재.
-- 컬럼은 backend/database.py의 init_db()가 자동으로 ALTER TABLE로 추가한다.
-- 이 스크립트는 NeonDB(또는 psql)에서 1회만 실행하면 된다.
-- 백엔드는 mission_id/is_active만 부팅 시 동기화하므로 메타데이터는 그대로 유지된다.

UPDATE demo_mission SET
    success_criteria    = '점심 식사 후 10분 이상 천천히 걷기',
    strict_requirements = '식사 후 수행, 10분 이상, 뛰기보다 걷기',
    target_metric       = 'duration',
    target_value        = '10',
    target_unit         = '분',
    time_condition      = '식사 후',
    allowed_substitutes = '아침/저녁 식사 후 10분 걷기는 대체 수행으로 인정, 운동장 걷기 10분, 복도 걷기 10분, 실내 안전한 곳에서 10분 걷기, 천천히 산책 10분',
    denied_substitutes  = '달리기 하기, 자전거 타기, 스트레칭만 하기, 10분 미만 걷기'
WHERE order_no = 1;

UPDATE demo_mission SET
    success_criteria    = '엘리베이터 대신 계단으로 최소 3층 이상 올라가기',
    strict_requirements = '계단 이용, 최소 3층 이상, 올라가는 동작 중심',
    target_metric       = 'count',
    target_value        = '3',
    target_unit         = '층',
    time_condition      = '제한 없음',
    allowed_substitutes = '학교 계단 3층 이상 오르기, 집 계단을 반복해서 총 3층 이상 오르기, 건물 계단 3층 이상 오르기, 낮은 건물 계단을 여러 번 올라 총 3층 이상 채우기, 엘리베이터 대신 계단으로 한 층씩 여러 번 올라가기',
    denied_substitutes  = '엘리베이터 이용, 에스컬레이터 이용, 내려가기만 하기, 3층 미만'
WHERE order_no = 2;

UPDATE demo_mission SET
    success_criteria    = '줄넘기 50회 완료 또는 비슷한 강도의 전신 심폐 운동 수행',
    strict_requirements = '50회 기준 우선, 안전한 장소',
    target_metric       = 'reps',
    target_value        = '50',
    target_unit         = '회',
    time_condition      = '제한 없음',
    allowed_substitutes = '줄넘기 50회 이상, 제자리뛰기 50회 이상, 숨이 살짝 찰 정도의 달리기 5분 이상, 달리기 1km 이상, 버피 15회 이상',
    denied_substitutes  = '걷기만 하기, 스트레칭만 하기, 줄넘기 49회 이하'
WHERE order_no = 3;

UPDATE demo_mission SET
    success_criteria    = '계단 오르내리기 10분 수행',
    strict_requirements = '10분 이상, 계단 이용',
    target_metric       = 'duration',
    target_value        = '10',
    target_unit         = '분',
    time_condition      = '제한 없음',
    allowed_substitutes = '계단 오르기 중심 10분, 실내 계단 왕복 10분, 스텝박스 운동 10분',
    denied_substitutes  = '엘리베이터 이용, 평지 걷기만 하기, 10분 미만, 앉았다 일어나기만 하기'
WHERE order_no = 4;

UPDATE demo_mission SET
    success_criteria    = '버피테스트 25회 완료 또는 비슷한 강도의 전신 운동 수행',
    strict_requirements = '25회 기준 우선, 전신 근력과 심폐 강도',
    target_metric       = 'reps',
    target_value        = '25',
    target_unit         = '회',
    time_condition      = '제한 없음',
    allowed_substitutes = '버피 25회 이상, 스쿼트 30회 이상, 제자리뛰기 연속해서 3분',
    denied_substitutes  = '가벼운 산책, 스트레칭만 하기, 팔굽혀펴기 5회만 하기, 25회보다 많이 부족한 수행'
WHERE order_no = 5;

UPDATE demo_mission SET
    success_criteria    = '전신 스트레칭을 12분 이상 수행',
    strict_requirements = '12분 이상, 목/어깨/팔/허리/다리 등 전신 또는 여러 부위, 무리한 반동 금지',
    target_metric       = 'duration',
    target_value        = '12',
    target_unit         = '분',
    time_condition      = '제한 없음',
    allowed_substitutes = '영상 보며 스트레칭 12분, 요가식 가벼운 전신 스트레칭 12분, 부위별 스트레칭 12분, 필라테스 12분',
    denied_substitutes  = '근력운동만 하기, 달리기만 하기, 12분 미만 스트레칭, 한 부위만 아주 짧게 하기'
WHERE order_no = 6;

UPDATE demo_mission SET
    success_criteria    = '집에서 음악을 틀고 10분 이상 몸을 움직이며 춤추기',
    strict_requirements = '10분 이상, 실제 신체 활동, 실내 안전 및 층간소음 주의',
    target_metric       = 'duration',
    target_value        = '10',
    target_unit         = '분',
    time_condition      = '제한 없음',
    allowed_substitutes = '좋아하는 노래에 맞춰 춤 10분, 실내 에어로빅 10분, 음악 틀고 율동 10분',
    denied_substitutes  = '노래만 듣기, 영상만 보기, 앉아서 리듬만 타기, 10분 미만'
WHERE order_no = 7;

UPDATE demo_mission SET
    success_criteria    = '아침 시간에 실제 식사를 하기',
    strict_requirements = '아침에 먹기, 음식 섭취, 과식하지 않기',
    target_metric       = 'meal_completion',
    target_value        = '1',
    target_unit         = '끼',
    time_condition      = '아침',
    allowed_substitutes = '밥 먹기, 빵 먹기, 시리얼 먹기, 요거트와 과일 먹기, 간단한 아침식사',
    denied_substitutes  = '물만 마시기, 음료만 마시기, 점심을 아침 대신으로 말하기, 과자만 먹기, 단백질 음료 먹기'
WHERE order_no = 8;

UPDATE demo_mission SET
    success_criteria    = '식사 직전과 직후에 비누로 30초 이상 손 씻기',
    strict_requirements = '식사 전후 모두, 비누 사용, 30초 이상',
    target_metric       = 'duration_each',
    target_value        = '30',
    target_unit         = '초',
    time_condition      = '식사 직전과 직후',
    allowed_substitutes = '비누로 손 씻기, 식사 전후 각각 30초 씻기, 흐르는 물과 비누로 꼼꼼히 씻기',
    denied_substitutes  = '물로만 대충 헹구기, 물티슈만 사용, 식사 전만 씻기, 식사 후만 씻기'
WHERE order_no = 9;

UPDATE demo_mission SET
    success_criteria    = '기상 직후 미지근한 물 한 잔 마시기',
    strict_requirements = '기상 후 수행, 한 잔 분량, 물 중심',
    target_metric       = 'count',
    target_value        = '1',
    target_unit         = '잔',
    time_condition      = '기상 직후',
    allowed_substitutes = '미지근한 물 한 잔, 미지근한 물 한 컵, 생수 한 잔, 생수 한 컵, 보리차 한 잔, 보리차 한 컵, 무가당 둥굴레차 한 잔, 무가당 둥굴레차 한 컵',
    denied_substitutes  = '주스, 탄산음료, 커피, 당이 들어간 음료, 우유만 마시기'
WHERE order_no = 10;

UPDATE demo_mission SET
    success_criteria    = '하루 동안 생수 기준 물 1L 이상 마시기',
    strict_requirements = '1L 이상, 하루 동안, 오직 생수만 인정, 커피/녹차/차류 제외',
    target_metric       = 'volume',
    target_value        = '1',
    target_unit         = 'L',
    time_condition      = '하루 동안',
    allowed_substitutes = '생수 1L, 생수 1리터, 생수 1000ml, 500ml 생수병 2개, 500ml 생수 두 병, 생수 두 병, 미지근한 생수 1L, 미지근한 생수 1리터, 일반 컵 약 5잔, 일반컵 5컵, 종이컵 약 6잔, 종이컵 6컵, 생수 1000ml',
    denied_substitutes  = '녹차, 커피, 보리차, 옥수수차, 둥굴레차, 주스, 탄산음료, 이온음료, 당이 들어간 음료, 1L 미만, 한두 컵만 마시기, 조금만 마시기'
WHERE order_no = 11;

UPDATE demo_mission SET
    success_criteria    = '오늘 하루 동안 과자류를 먹지 않기',
    strict_requirements = '하루 전체, 모든 스낵류 과자 금지',
    target_metric       = 'avoid',
    target_value        = '0',
    target_unit         = '회',
    time_condition      = '오늘 하루 동안',
    allowed_substitutes = '과일로 대신하기, 견과류로 대신하기, 요거트 먹기, 과자를 아예 먹지 않기',
    denied_substitutes  = '감자칩, 쿠키, 초콜릿 과자, 스낵류, 과자를 조금만 먹기'
WHERE order_no = 12;

UPDATE demo_mission SET
    success_criteria    = '오늘 생과일을 1번 이상 먹기',
    strict_requirements = '과일 1회 이상, 생과일 우선, 주스보다 직접 씹어 먹기',
    target_metric       = 'count',
    target_value        = '1',
    target_unit         = '회',
    time_condition      = '오늘 하루 동안',
    allowed_substitutes = '사과, 바나나, 귤, 딸기, 포도, 자른 과일, 과일 샐러드',
    denied_substitutes  = '과일주스만 마시기, 과일맛 음료, 젤리, 과일향 과자'
WHERE order_no = 13;

UPDATE demo_mission SET
    success_criteria    = '잠들기 직전 3분 동안 칫솔과 치약으로 양치하기',
    strict_requirements = '잠들기 전, 3분, 실제 양치질, 양치 후 물 외 음식 금지',
    target_metric       = 'duration',
    target_value        = '3',
    target_unit         = '분',
    time_condition      = '잠들기 직전',
    allowed_substitutes = '칫솔과 치약으로 양치 3분, 전동칫솔로 3분 양치',
    denied_substitutes  = '가글만 하기, 물로 헹구기만 하기, 치실만 하기, 자기 전이 아닌 낮에만 양치하기, 양치 후 간식 먹기'
WHERE order_no = 14;

UPDATE demo_mission SET
    success_criteria    = '10분 동안 책상/바닥/옷장 중 한 곳 이상 정리하기',
    strict_requirements = '10분 이상, 실제 정리 행동, 물건을 버리거나 제자리에 두기',
    target_metric       = 'duration',
    target_value        = '10',
    target_unit         = '분',
    time_condition      = '제한 없음',
    allowed_substitutes = '책상 정리 10분, 바닥 정리 10분, 옷장 정리 10분, 가방 정리 10분, 침구 정리 10분',
    denied_substitutes  = '생각만 하기, 계획만 세우기, 청소 영상 보기, 5분 이하 정리'
WHERE order_no = 15;

UPDATE demo_mission SET
    success_criteria    = '오늘 숙제를 모두 완료한 뒤 게임하기',
    strict_requirements = '숙제 먼저 완료, 대충이 아니라 확인 후 게임, 게임 전 순서 중요',
    target_metric       = 'order',
    target_value        = NULL,
    target_unit         = NULL,
    time_condition      = '오늘 게임하기 전',
    allowed_substitutes = '학교 숙제 완료 후 게임, 학원 숙제 완료 후 게임, 오늘 할 공부를 끝낸 뒤 게임',
    denied_substitutes  = '숙제 전 게임하기, 숙제를 일부만 하고 게임하기, 숙제 대충 하고 게임하기, 게임만 안 하고 숙제도 안 하기'
WHERE order_no = 16;

UPDATE demo_mission SET
    success_criteria    = '오늘 유튜브 시청 시간을 30분 이하로 제한하기',
    strict_requirements = '유튜브 30분 이하, 30분 지나면 종료, 쇼츠 포함',
    target_metric       = 'max_duration',
    target_value        = '30',
    target_unit         = '분',
    time_condition      = '오늘 하루 동안',
    allowed_substitutes = '유튜브 30분 이하, 유튜브를 아예 보지 않기, 타이머 맞추고 30분만 보기',
    denied_substitutes  = '유튜브 30분 초과, 쇼츠를 계속 보기, 유튜브 대신 릴스/OTT를 오래 보기'
WHERE order_no = 17;

UPDATE demo_mission SET
    success_criteria    = '기상 후 외출 전까지 휴대폰 영상이나 TV 등 화면을 보지 않기',
    strict_requirements = '아침 외출 준비 시간 전체, 휴대폰 영상/TV 금지, 준비에 집중',
    target_metric       = 'avoid',
    target_value        = '0',
    target_unit         = '회',
    time_condition      = '기상 후 외출 전까지',
    allowed_substitutes = '화면 보지 않고 씻기/옷 입기/가방 챙기기, 음악만 듣고 준비하기, 가족과 대화하며 준비하기',
    denied_substitutes  = '휴대폰 영상 보기, TV 보기, 유튜브/쇼츠 보기, 게임하기, 잠깐이라도 영상 보기'
WHERE order_no = 18;
