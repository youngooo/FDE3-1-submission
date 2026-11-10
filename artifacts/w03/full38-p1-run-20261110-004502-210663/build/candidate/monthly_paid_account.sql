SELECT e.month_start,
       e.member_id,
       e.member_id || '|' || strftime(e.month_start, '%Y-%m') AS monthly_paid_account_key,
       COALESCE(o.valid_order_count, 0) AS valid_order_count,
       COALESCE(o.net_sales_cents, 0) AS net_sales_cents
FROM {{ ref('monthly_paid_eligibility') }} AS e
LEFT JOIN (
  SELECT member_id,
         CAST(date_trunc('month', ordered_at) AS DATE) AS month_start,
         COUNT(*) AS valid_order_count,
         SUM(paid_cents - refund_cents) AS net_sales_cents
  FROM {{ ref('orders') }}
  WHERE status = 'paid'
    AND paid_cents - refund_cents > 0
  GROUP BY member_id, CAST(date_trunc('month', ordered_at) AS DATE)
) AS o
  ON e.member_id = o.member_id
 AND e.month_start = o.month_start