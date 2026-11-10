WITH months AS (
  SELECT DISTINCT DATE_TRUNC('month', date_day)::DATE AS month_start
  FROM {{ ref('time_spine') }}
),
member_month AS (
  SELECT
    member_id,
    DATE_TRUNC('month', ordered_at)::DATE AS month_start,
    COUNT(*) AS valid_order_count
  FROM {{ ref('orders') }}
  WHERE status = 'paid' AND paid_cents - refund_cents > 0
  GROUP BY member_id, DATE_TRUNC('month', ordered_at)::DATE
),
monthly AS (
  SELECT
    month_start,
    COUNT(*) FILTER (WHERE valid_order_count >= 1) AS buyer_count,
    COUNT(*) FILTER (WHERE valid_order_count >= 2) AS repeat_buyer_count
  FROM member_month
  GROUP BY month_start
)
SELECT
  m.month_start,
  COALESCE(monthly.buyer_count, 0) AS buyer_count,
  COALESCE(monthly.repeat_buyer_count, 0) AS repeat_buyer_count
FROM months m
LEFT JOIN monthly
  ON m.month_start = monthly.month_start