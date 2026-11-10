WITH valid_orders AS (
    SELECT
        o.order_id,
        o.member_id,
        o.store_id,
        o.ordered_at,
        o.channel,
        o.status,
        o.paid_cents - o.refund_cents AS net_sales_cents
    FROM {{ ref('orders') }} o
    WHERE o.status = 'paid'
      AND o.paid_cents - o.refund_cents > 0
),
ranked AS (
    SELECT
        v.*,
        ROW_NUMBER() OVER (PARTITION BY v.member_id ORDER BY v.ordered_at, v.order_id) AS rn
    FROM valid_orders v
)
SELECT
    r.order_id,
    r.member_id,
    r.store_id,
    m.home_store_id,
    r.ordered_at,
    r.channel,
    r.status,
    r.net_sales_cents
FROM ranked r
LEFT JOIN {{ ref('members') }} m
  ON r.member_id = m.member_id
WHERE r.rn > 1