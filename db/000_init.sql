CREATE TYPE status AS ENUM ('crashed', 'inprogress', 'working', 'failing', 'new', 'archived');

CREATE TABLE trackers (
    tracker_id      SERIAL PRIMARY KEY,
    config_hash     CHAR(64),
    config          TEXT,
    family          TEXT,
    status          status
);
