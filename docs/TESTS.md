# Testing the API

There are no unit tests, or any tests really, so I'll just list the API endpoints that *should* be tested before a release. Try curling them and make sure there are no server errors?

```sh
MTRACKER=mtracker_url
TRACKER=valid_tracker_di
TASK=valid_task_id
BOT=valid_bot_id

curl "${MTRACKER}/varz"
# POST /api/trackers
# POST /track/dhash
curl "${MTRACKER}/api/tasks/${TASK}/log"
curl "${MTRACKER}/api/results/?start=0&count=1"
curl "${MTRACKER}/api/tasks/?start=0&count=1"
curl "${MTRACKER}/api/tasks/${TASK}/results"
curl "${MTRACKER}/api/tasks/${TASK}"
# POST /api/trackers/
# POST /api/trackers/${TRACKER}
curl "${MTRACKER}/api/trackers/${TRACKER}/bots?start=0&count=1"
curl "${MTRACKER}/api/trackers/${TRACKER}"
curl "${MTRACKER}/api/trackers/${TRACKER}/results?start=0&count=1"
curl "${MTRACKER}/api/bots/?start=0&count=1"
curl "${MTRACKER}/api/bots/${BOT}"
curl "${MTRACKER}/api/bots/${BOT}/results?start=0&count=1"
# POST /api/bots/${BOT}
# POST /bots/${BOT}
curl "${MTRACKER}/api/bots/${BOT}/tasks?start=0&count=1"
curl "${MTRACKER}/api/bots/${BOT}/log"
curl "${MTRACKER}/api/proxies/"
# POST /api/proxies/update
curl "${MTRACKER}/api/heartbeat/"
# POST /proxies/update
curl "${MTRACKER}/results"
curl "${MTRACKER}/tasks"
curl "${MTRACKER}/tasks/${TASK}"
curl "${MTRACKER}/bots"
curl "${MTRACKER}/bots/${BOT}"
curl "${MTRACKER}/trackers"
curl "${MTRACKER}/trackers/${TRACKER}"
curl "${MTRACKER}/"
```