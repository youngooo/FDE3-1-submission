SELECT o.*, s.valid_seq
FROM {{ ref('order_facts') }} AS o
LEFT JOIN {{ ref('order_sequence') }} AS s
  ON o.order_id = s.order_id