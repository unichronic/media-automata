# Media Automata

WhatsApp-controlled automation for publishing to LinkedIn, X/Twitter, and Instagram.

The production deployment path is container-first:

- Build `ghcr.io/unichronic/media-automata:v1` from this repo.
- Deploy API, worker, monitor jobs, and ReDroid through the PointBlank infra repo.
- Use the standalone OpenWA app from `ghcr.io/unichronic/openwa:v1`.

## Image

```bash
docker build -t ghcr.io/unichronic/media-automata:v1 .
docker push ghcr.io/unichronic/media-automata:v1
```

## Required Runtime Config

Use Kubernetes secrets/config in the infra repo for production. For local one-off checks, create `.env` from `.env.example`.

Required secrets:

```text
MISTRAL_API_KEY or MISTRAL_API_KEYS
OPENWA_API_KEY
OPENWA_SESSION_ID
LINKEDIN_EMAIL
LINKEDIN_PASSWORD
X_LOGIN_IDENTIFIER
X_PASSWORD
INSTAGRAM_USERNAME
INSTAGRAM_PASSWORD
```

`OPENWA_SESSION_ID` can be either the OpenWA session UUID or the human session name, for example `main`.
The first session still needs to be created and paired once through OpenWA.

Production OpenWA URL:

```text
OPENWA_BASE_URL=http://openwa-api.openwa.svc.cluster.local:2785/api
```

## Commands

```bash
python -m media_automata.cli migrate
python -m media_automata.cli worker --loop
python -m media_automata.cli monitor-once
python -m media_automata.cli production-check --recover-openwa --deep-instagram
```

API entrypoint:

```bash
uvicorn media_automata.api:app --host 0.0.0.0 --port 8080
```

## Local Full Stack

With OpenWA checked out at `/home/unichronic/OpenWA` and both projects configured:

```bash
./scripts/stack.sh start
./scripts/stack.sh status
./scripts/stack.sh logs worker
./scripts/stack.sh stop
```

The script starts the persistent OpenWA API and dashboard, Media Automata API and worker,
and an available local Android runtime. Override paths or ports with `OPENWA_DIR`,
`MEDIA_AUTOMATA_PORT`, and `ANDROID_AVD_NAME`.

## WhatsApp Command Example

```text
/post this on all 3 platforms
Instagram caption - launch post
Twitter - launch post
LinkedIn - launch post
```

Scheduling, quoted WhatsApp media, text-only X/LinkedIn posts, Instagram feed posts, direct Stories, and feed-post-to-Story flows are handled by the worker path.
