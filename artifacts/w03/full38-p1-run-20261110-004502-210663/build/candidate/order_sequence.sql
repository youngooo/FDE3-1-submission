SELECT order_id,
       ROW_NUMBER() OVER (PARTITION BY member_id ORDER BY ordered_at, order_id) AS valid_seq
FROM {{ ref('order_facts') }}
WHERE status = 'paid'
  AND paid_cents - refund_cents > 0