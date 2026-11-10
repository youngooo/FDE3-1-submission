WITH months AS (
  SELECT DISTINCT
         CAST(date_trunc('month', date_day) AS DATE) AS month_start,
         CAST(date_trunc('month', date_day) + INTERVAL '1 month' - INTERVAL '1 day' AS DATE) AS month_end
  FROM {{ ref('time_spine') }}
),
eligible_cards AS (
  SELECT member_id, valid_from, valid_until, ended_at
  FROM {{ ref('cards') }}
  WHERE card_type IN ('悦享年卡', '家庭季卡')
    AND valid_from IS NOT NULL
    AND valid_until IS NOT NULL
    AND valid_from < valid_until
    AND (ended_at IS NULL OR (ended_at > valid_from AND ended_at < valid_until))
)
SELECT DISTINCT m.month_start, c.member_id
FROM months AS m
JOIN eligible_cards AS c
  ON c.valid_from <= m.month_end
 AND m.month_end < c.valid_until
 AND (c.ended_at IS NULL OR m.month_end < c.ended_at)