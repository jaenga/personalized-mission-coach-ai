-- Remove the 3-floor threshold from demo mission 12.
-- Run once when updating an existing database:
--   psql "$DATABASE_URL" -f backend/migrations/004_remove_stair_floor_threshold.sql

UPDATE demo_mission SET
    success_criteria    = '엘리베이터나 에스컬레이터 대신 계단 이용하기',
    strict_requirements = '계단 이용',
    target_metric       = NULL,
    target_value        = NULL,
    target_unit         = NULL,
    time_condition      = '제한 없음',
    allowed_substitutes = '계단으로 걷기, 계단 이용하기, 계단으로 올라가기, 엘리베이터 대신 계단 이용하기, 에스컬레이터 대신 계단 이용하기',
    denied_substitutes  = '엘리베이터 이용, 에스컬레이터 이용'
WHERE mission_id = 12 OR order_no = 2;
