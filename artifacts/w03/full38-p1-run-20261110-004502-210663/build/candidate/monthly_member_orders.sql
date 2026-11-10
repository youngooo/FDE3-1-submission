SELECT member_id,
       month_start,
       member_id || '|' || strftime(month_start, '%Y-%m') AS monthly_account_key,
       valid_order_count,
       net_sales_cents
FROM (
  SELECT member_id,
         CAST(date_trunc('month', ordered_at) AS DATE) AS month_start,
         COUNT(*) AS valid_order_count,
         SUM(paid_cents - refund_cents) AS net_sales_cents
  FROM {{ ref('orders') }}
  WHERE status = 'paid'
    AND paid_cents - refund_cents > 0
  GROUP BY member_id, CAST(date_trunc('month', ordered_at) AS DATE)
) AS t