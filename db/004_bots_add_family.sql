ALTER TABLE bots ADD COLUMN family TEXT;
UPDATE bots b SET family = (SELECT family FROM trackers t WHERE b.tracker_id=t.tracker_id);