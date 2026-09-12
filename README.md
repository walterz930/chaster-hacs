# Chaster for Home Assistant

A HACS custom integration for the [Chaster Public API](https://docs.chaster.app/api/public-api/endpoints/).

## Installation

### HACS

1. Open **HACS → Integrations**.
2. Search for **Chaster**.
3. Install the integration.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add Integration → Chaster**.

If you are installing this repository before it is published to the HACS default repository, add `https://github.com/walterz930/chaster-hacs` as a custom HACS repository with category **Integration**.

## Authentication

Chaster uses a **developer token** directly. OAuth, browser login, client IDs, client secrets, and OAuth callbacks are not required.

### Get a developer token

1. Open the [Chaster developer area](https://chaster.app/developers).
2. Request API access if you have not already been approved.
3. Open the **Developer interface**.
4. Create or open an application.
5. Select **Tokens** in the left sidebar.
6. Click **Generate a developer token** and copy the token.
7. Enter the token when adding the Chaster integration in Home Assistant.

Keep the token private. Never post it in an issue, forum, Discord message, or repository.

Official documentation: [Getting started](https://docs.chaster.app/api/basics/getting-started/) · [Developer tokens](https://docs.chaster.app/api/public-api/developer-token/) · [Public API](https://docs.chaster.app/api/public-api/endpoints/) · [Scopes](https://docs.chaster.app/api/reference/scopes/)

## Features

- Developer-token authentication with Home Assistant config flow and reauthentication.
- Automatic role detection with **Auto**, **Wearer**, **Keyholder**, and **Both** modes.
- Current-lock entity that follows the active lock instead of requiring a manually selected historical lock.
- Historical wearer and keyholder lock sensors.
- Shared-lock support when the account has the required API access.
- Messaging data and a generic message service.
- Current-lock history diagnostics.
- Current-lock controls for refresh, freeze, unfreeze, unlock, emergency unlock, and archive.
- Explicit `chaster.add_time` and `chaster.remove_time` services.
- Generic `chaster.api_request` and `chaster.lock_action` services for documented API operations that do not yet have dedicated entities.

## Role and permission model

Chaster remains authoritative for permissions. The integration does not attempt to bypass the Public API permission contract; unsupported or unauthorized actions are rejected by Chaster.

The integration exposes the API's permission information on lock entities where available, including time changes, freezing, minimum/maximum dates, timer/history visibility, extensions, and safety settings.

## Services

### `chaster.add_time`

```yaml
lock_id: LOCK_ID
seconds: 3600
```

### `chaster.remove_time`

```yaml
lock_id: LOCK_ID
seconds: 600
```

### `chaster.api_request`

```yaml
method: GET
path: /permissions/definitions
params: {}
body: {}
```

### `chaster.lock_action`

```yaml
lock_id: LOCK_ID
path: /locks/{lock_id}/...
method: POST
body: {}
```

### `chaster.send_message`

```yaml
path: /conversations/CONVERSATION_ID
body:
  # documented Chaster message payload
```

The generic services are intentionally retained because the Chaster Public API is evolving. Use the official Chaster API documentation as the source of truth for endpoint paths, payloads, and permissions.

## Existing installations

The integration stores the developer token as `token`. Existing installations that already use the developer-token configuration can continue to use their stored token. Older OAuth-based configurations should be removed and added again using a developer token.

## Development

The repository contains the Home Assistant integration under `custom_components/chaster`.

Validation is provided by GitHub Actions using Home Assistant **hassfest**, the HACS validation action, and Python bytecode compilation.

## License

MIT License. See [LICENSE](LICENSE).
