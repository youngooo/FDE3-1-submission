SELECT o.*, m.home_store_id
FROM {{ ref('orders') }} AS o
LEFT JOIN {{ ref('members') }} AS m
  ON o.member_id = m.member_id