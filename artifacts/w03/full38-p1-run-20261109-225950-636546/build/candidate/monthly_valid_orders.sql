WITH valid_orders AS (
    SELECT
        member_id,
        CAST(date_trunc('month', ordered_at) AS DATE) AS month_date,
        COUNT(*) AS valid_order_count
    FROM {{ ref('orders') }}
    WHERE status = 'paid'
      AND paid_cents - refund_cents > 0
    GROUP BY member_id, CAST(date_trunc('month', ordered_at) AS DATE)
)
SELECT
    member_id,
    month_date,
    valid_order_count,
    1 AS is_buyer,
    CASE WHEN valid_order_count >= 2 THEN 1 ELSE 0 END AS is_repeat_buyer,
    member_id || '|' || strftime(month_date, '%Y-%m') AS member_month_key
FROM valid_orders