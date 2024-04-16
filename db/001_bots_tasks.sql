CREATE TABLE bots (
    bot_id          SERIAL PRIMARY KEY,
    tracker_id      INT REFERENCES trackers(tracker_id),
    status          status,
    state           TEXT,
    failing_spree   INT,
    next_execution  DATE,
    country         TEXT
);

CREATE TABLE tasks (
    task_id         SERIAL PRIMARY KEY,
    bot_id          INT REFERENCES bots(bot_id),
    status          status,
    report_time     DATE,
    results         TEXT,
    logs            TEXT
);
