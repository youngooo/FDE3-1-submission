WITH months AS (
  SELECT DISTINCT DATE_TRUNC('month', date_day)::DATE AS month_start
  FROM {{ ref('time_spine') }}
),
month_ends AS (
  SELECT
    month_start,
    (month_start + INTERVAL '1 month' - INTERVAL '1 day')::DATE AS month_end
  FROM months
),
cards_scoped AS (
  SELECT
    c.*,
    CASE
      WHEN c.valid_from IS NOT NULL
       AND c.valid_until IS NOT NULL
       AND c.valid_from < c.valid_until
       AND (c.ended_at IS NULL OR (c.ended_at > c.valid_from AND c.ended_at < c.valid_until))
      THEN TRUE
      ELSE FALSE
    END AS p1_precheck_ok
  FROM {{ ref('cards') }} c
  WHERE c.card_type IN ('悦享年卡', '家庭季卡')
),
eligible AS (
  SELECT
    me.month_start,
    c.member_id
  FROM month_ends me
  JOIN cards_scoped c
    ON c.p1_precheck_ok
   AND c.valid_from <= me.month_end
   AND me.month_end < c.valid_until
   AND (c.ended_at IS NULL OR me.month_end < c.ended_at)
  GROUP BY me.month_start, c.member_id
),
pending AS (
  SELECT DISTINCT me.month_start
  FROM month_ends me
  WHERE EXISTS (
    SELECT 1
    FROM cards_scoped c
    WHERE c.p1_precheck_ok = FALSE
  )
),
valid_orders AS (
  SELECT
    member_id,
    DATE_TRUNC('month', ordered_at)::DATE AS month_start,
    COUNT(*) AS valid_order_count,
    SUM(paid_cents - refund_cents) AS net_sales_cents
  FROM {{ ref('orders') }}
  WHERE status = 'paid' AND paid_cents - refund_cents > 0
  GROUP BY member_id, DATE_TRUNC('month', ordered_at)::DATE
),
monthly_accounts AS (
  SELECT
    me.month_start,
    e.member_id,
    COALESCE(o.valid_order_count, 0) AS valid_order_count,
    COALESCE(o.net_sales_cents, 0) AS net_sales_cents
  FROM month_ends me
  LEFT JOIN eligible e
    ON e.month_start = me.month_start
  LEFT JOIN valid_orders o
    ON o.month_start = e.month_start
   AND o.member_id = e.member_id
),
summary AS (
  SELECT
    month_start,
    COUNT(*) FILTER (WHERE member_id IS NOT NULL AND valid_order_count >= 1) AS buyer_count,
    SUM(CASE WHEN member_id IS NOT NULL THEN valid_order_count ELSE 0 END) AS order_count,
    SUM(CASE WHEN member_id IS NOT NULL THEN net_sales_cents ELSE 0 END) AS sales_cents,
    COUNT(*) FILTER (WHERE member_id IS NOT NULL AND valid_order_count >= 2) AS repeat_buyer_count
  FROM monthly_accounts
  GROUP BY month_start
)
SELECT
  s.month_start,
  CASE WHEN p.month_start IS NULL THEN s.buyer_count ELSE NULL END AS buyer_count,
  CASE WHEN p.month_start IS NULL THEN s.order_count ELSE NULL END AS order_count,
  CASE WHEN p.month_start IS NULL THEN s.sales_cents ELSE NULL END AS sales_cents,
  CASE WHEN p.month_start IS NULL THEN s.repeat_buyer_count ELSE NULL END AS repeat_buyer_count
FROM summary s
LEFT JOIN pending p
  ON s.month_start = p.month_start