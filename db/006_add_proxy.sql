CREATE TABLE proxies (
    proxy_id        SERIAL PRIMARY KEY,
    host            TEXT,
    port            INTEGER,
    country         CHAR(2)
);
