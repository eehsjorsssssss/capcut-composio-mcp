# CapCut → Composio Custom MCP Bridge

This project exposes a small remote MCP server that Composio can register as a `CUSTOM_*` toolkit.

## Important

CapCut's current public site describes an AI Video Editor API, but I did not find a complete public official endpoint reference. This bridge therefore separates the MCP layer from the actual CapCut-compatible REST API through environment-configurable paths.

A practical test backend is the community `CapCutAPI` project, which documents endpoints/tools such as `create_draft`, `add_video`, `add_text`, `add_video_keyframe`, and `save_draft`. Do not describe that project as an official CapCut API.

## Tools exposed to Composio

- `capcut_health`
- `capcut_create_draft`
- `capcut_add_video`
- `capcut_add_text`
- `capcut_add_keyframe`
- `capcut_save_draft`
- `capcut_request`
- `capcut_create_ranking_draft`

## Run locally

```bash
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env
python server.py
```

The MCP endpoint is:

`http://localhost:8000/mcp`

For Composio, the server must be deployed at a public HTTPS URL.

## Deploy

Any host that can run Docker and expose HTTPS works. The included `Dockerfile` can be deployed to Render, Railway, Fly.io, a VPS, etc.

If the CapCut-compatible REST API is also hosted remotely, set:

```text
CAPCUT_BASE_URL=https://your-capcut-api.example.com
```

If the REST API only runs on your Windows PC at `127.0.0.1:9001`, a cloud-hosted MCP server cannot reach it. In that case, host both services on the same machine/network or deploy the CapCut API alongside the MCP bridge.

## Register in Composio

Composio's current Custom MCP lifecycle is:

1. Deploy the server at a public HTTPS URL.
2. Register the URL with `POST /api/v3.1/custom/toolkits/upsert`.
3. Sync the toolkit with `POST /api/v3.1/custom/toolkits/sync` if needed.
4. Use the returned `CUSTOM_*` toolkit in a Composio session.

Example registration with no authentication:

```bash
curl --request POST \
  --url https://backend.composio.dev/api/v3.1/custom/toolkits/upsert \
  --header "x-api-key: $COMPOSIO_API_KEY" \
  --header "Content-Type: application/json" \
  --data '{
    "slug": "CAPCUT",
    "toolkit_config": {
      "name": "CapCut",
      "app_url": "https://YOUR-DOMAIN.example/mcp",
      "auth_schemes": [{"mode": "NO_AUTH"}]
    }
  }'
```

For production, prefer an API-key auth scheme rather than exposing a no-auth editing server.

Example API-key scheme:

```json
{
  "slug": "CAPCUT",
  "toolkit_config": {
    "name": "CapCut",
    "app_url": "https://YOUR-DOMAIN.example/mcp",
    "auth_schemes": [
      {
        "mode": "API_KEY",
        "headers": {
          "Authorization": "Bearer {{generic_api_key}}"
        }
      }
    ]
  }
}
```

The exact Custom MCP auth connection flow is controlled by Composio; see their current Custom MCP documentation before registering an authenticated server.

## Ranking video example

After the toolkit is synced, an agent can call `capcut_create_ranking_draft` with ordered clips:

```json
{
  "title": "TOP 5 STREAMER MOMENTS",
  "width": 1080,
  "height": 1920,
  "clips": [
    {"video_url": "https://example.com/clip5.mp4", "duration": 5, "label": "#5"},
    {"video_url": "https://example.com/clip4.mp4", "duration": 5, "label": "#4"},
    {"video_url": "https://example.com/clip3.mp4", "duration": 5, "label": "#3"},
    {"video_url": "https://example.com/clip2.mp4", "duration": 5, "label": "#2"},
    {"video_url": "https://example.com/clip1.mp4", "duration": 5, "label": "#1"}
  ]
}
```

The current composite tool creates/saves the draft. Actual final MP4 rendering depends on what the underlying CapCut-compatible API exposes.
