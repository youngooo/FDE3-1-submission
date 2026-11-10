SELECT o.*, m.home_store_id
FROM {{ ref('orders') }} o
LEFT JOIN {{ ref('members') }} m
  ON o.member_id = m.member_id