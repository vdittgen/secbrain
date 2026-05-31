/*
    Today mart — primary data source for the Daily Dashboard.

    Combines today's calendar events, recent messages, and notes created
    today into a single feed. Includes a placeholder coaching_phrase column
    to be populated by the LLM agent.

    Column Sensitivity Tiers:
        item_type:        tier 1
        id:               tier 1
        title:            tier 2
        detail:           tier 3
        occurred_at:      tier 2
        category:         tier 1
        duration_minutes: tier 1
        sensitivity_tier: tier 1
        event_origin:     tier 1
        coaching_phrase:  tier 2
        _loaded_at:       tier 1
*/

SELECT
    'event'                                 AS item_type,
    e.id,
    e.title,
    e.description                           AS detail,
    e.start_time                            AS occurred_at,
    e.event_category                        AS category,
    e.duration_minutes,
    e.sensitivity_tier,
    e.event_origin                          AS event_origin,
    CAST(NULL AS TEXT)                      AS coaching_phrase,
    datetime('now')                         AS _loaded_at
FROM int_events_enriched e
WHERE DATE(e.start_time) = DATE('now')

UNION ALL

SELECT
    'message'                               AS item_type,
    m.id,
    m.sender || ': ' || SUBSTR(m.content, 1, 80) AS title,
    m.content                               AS detail,
    m.timestamp                             AS occurred_at,
    m.message_category                      AS category,
    CAST(NULL AS INTEGER)                   AS duration_minutes,
    m.sensitivity_tier,
    CAST(NULL AS TEXT)                      AS event_origin,
    CAST(NULL AS TEXT)                      AS coaching_phrase,
    datetime('now')                         AS _loaded_at
FROM int_personal_enriched m
WHERE DATE(m.timestamp) = DATE('now')

UNION ALL

SELECT
    'note'                                  AS item_type,
    n.id,
    n.title,
    n.content                               AS detail,
    n.created_at                            AS occurred_at,
    'note'                                  AS category,
    CAST(NULL AS INTEGER)                   AS duration_minutes,
    n.sensitivity_tier,
    CAST(NULL AS TEXT)                      AS event_origin,
    CAST(NULL AS TEXT)                      AS coaching_phrase,
    datetime('now')                         AS _loaded_at
FROM stg_notes n
WHERE DATE(n.created_at) = DATE('now')

UNION ALL

SELECT
    'email'                                 AS item_type,
    e.id,
    e.subject                               AS title,
    e.body_preview                          AS detail,
    e.date                                  AS occurred_at,
    CASE
        WHEN e.from_address LIKE '%@company.com'
        THEN 'work'
        ELSE 'other'
    END                                     AS category,
    CAST(NULL AS INTEGER)                   AS duration_minutes,
    e.sensitivity_tier,
    CAST(NULL AS TEXT)                      AS event_origin,
    CAST(NULL AS TEXT)                      AS coaching_phrase,
    datetime('now')                         AS _loaded_at
FROM stg_emails e
WHERE DATE(e.date) = DATE('now')

UNION ALL

SELECT
    'reminder'                              AS item_type,
    r.id,
    r.title,
    r.notes                                 AS detail,
    COALESCE(r.due_date, datetime('now'))   AS occurred_at,
    COALESCE(r.list_name, 'default')        AS category,
    CAST(NULL AS INTEGER)                   AS duration_minutes,
    r.sensitivity_tier,
    CAST(NULL AS TEXT)                      AS event_origin,
    CAST(NULL AS TEXT)                      AS coaching_phrase,
    datetime('now')                         AS _loaded_at
FROM stg_reminders r
WHERE (DATE(r.due_date) = DATE('now')
       OR r.due_date IS NULL)
  AND (r.completed IS NULL OR r.completed = 0)
