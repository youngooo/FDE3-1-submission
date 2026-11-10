WITH valid_ranked AS (
  SELECT
    order_id,
    ROW_NUMBER() OVER (PARTITION BY member_id ORDER BY ordered_at, order_id) AS valid_seq
  FROM {{ ref('orders') }}
  WHERE status = 'paid' AND paid_cents - refund_cents > 0
),
base AS (
  SELECT
    o.order_id,
    o.member_id,
    o.store_id,
    o.ordered_at,
    o.status,
    o.gross_cents,
    o.paid_cents,
    o.refund_cents,
    o.quantity,
    o.channel,
    m.home_store_id,
    COALESCE(r.valid_seq, 0) AS valid_seq
  FROM {{ ref('orders') }} o
  LEFT JOIN {{ ref('members') }} m
    ON o.member_id = m.member_id
  LEFT JOIN valid_ranked r
    ON o.order_id = r.order_id
)
SELECT * FROM base