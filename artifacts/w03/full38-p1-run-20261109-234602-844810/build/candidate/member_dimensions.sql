SELECT
  member_id,
  registered_at,
  home_store_id,
  tier
FROM {{ ref('members') }}