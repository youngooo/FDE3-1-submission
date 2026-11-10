SELECT
  order_id,
  member_id,
  store_id,
  ordered_at,
  status,
  gross_cents,
  paid_cents,
  refund_cents,
  quantity,
  channel,
  CASE WHEN status = 'paid' AND paid_cents - refund_cents > 0 THEN 1 ELSE 0 END AS is_valid_order,
  CASE WHEN status = 'paid' THEN paid_cents - refund_cents ELSE 0 END AS net_sales_cents
FROM {{ ref('orders') }}