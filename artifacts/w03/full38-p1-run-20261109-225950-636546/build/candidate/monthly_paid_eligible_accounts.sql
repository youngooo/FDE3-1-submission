WITH months AS (
    SELECT DISTINCT CAST(date_trunc('month', date_day) AS DATE) AS month_date
    FROM {{ ref('time_spine') }}
),
month_bounds AS (
    SELECT month_date, CAST(last_day(month_date) AS DATE) AS month_end_date
    FROM months
),
member_months AS (
    SELECT m.member_id, mb.month_date, mb.month_end_date
    FROM {{ ref('members') }} m
    CROSS JOIN month_bounds mb
),
eligible_cards AS (
    SELECT
        mm.member_id,
        mm.month_date,
        MAX(CASE WHEN
            c.card_type IN ('悦享年卡', '家庭季卡')
            AND c.valid_from IS NOT NULL
            AND c.valid_until IS NOT NULL
            AND c.valid_from < c.valid_until
            AND (c.ended_at IS NULL OR (c.ended_at > c.valid_from AND c.ended_at < c.valid_until))
            AND c.valid_from <= mm.month_end_date
            AND mm.month_end_date < c.valid_until
            AND (c.ended_at IS NULL OR mm.month_end_date < c.ended_at)
        THEN 1 ELSE 0 END) AS is_eligible,
        MAX(CASE WHEN
            c.card_type IN ('悦享年卡', '家庭季卡')
            AND (
                c.valid_from IS NULL
                OR c.valid_until IS NULL
                OR c.valid_from >= c.valid_until
                OR (c.ended_at IS NOT NULL AND (c.ended_at <= c.valid_from OR c.ended_at >= c.valid_until))
            )
        THEN 1 ELSE 0 END) AS has_date_anomaly
    FROM member_months mm
    LEFT JOIN {{ ref('cards') }} c
      ON mm.member_id = c.member_id
    GROUP BY mm.member_id, mm.month_date
),
valid_orders AS (
    SELECT
        member_id,
        CAST(date_trunc('month', ordered_at) AS DATE) AS month_date,
        COUNT(*) AS valid_order_count,
        SUM(paid_cents - refund_cents) AS net_sales_cents
    FROM {{ ref('orders') }}
    WHERE status = 'paid'
      AND paid_cents - refund_cents > 0
    GROUP BY member_id, CAST(date_trunc('month', ordered_at) AS DATE)
)
SELECT
    mm.member_id,
    mm.month_date,
    mm.month_end_date,
    COALESCE(ec.is_eligible, 0) AS is_eligible,
    COALESCE(ec.has_date_anomaly, 0) AS has_date_anomaly,
    COALESCE(vo.valid_order_count, 0) AS valid_order_count,
    COALESCE(vo.net_sales_cents, 0) AS net_sales_cents,
    mm.member_id || '|' || strftime(mm.month_date, '%Y-%m') AS member_month_key
FROM member_months mm
LEFT JOIN eligible_cards ec
  ON mm.member_id = ec.member_id
 AND mm.month_date = ec.month_date
LEFT JOIN valid_orders vo
  ON mm.member_id = vo.member_id
 AND mm.month_date = vo.month_date