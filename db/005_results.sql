CREATE TYPE result_type AS ENUM ('config', 'blob', 'binary');

CREATE TABLE results (
    result_id       SERIAL PRIMARY KEY,
    task_id         INT REFERENCES tasks(task_id),
    type            result_type,
    name            TEXT,
    sha256          CHAR(64),
    tags            TEXT [],
    upload_time     TIMESTAMP
);

ALTER TABLE tasks DROP COLUMN results;
