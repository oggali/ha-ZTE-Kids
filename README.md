# ZTE Kids

Home Assistant integration for ZTE Kids watches. It signs in with the same parent account as the ZTE Kids phone app and exposes each linked watch as a device tracker.

Traffic goes to the international parent API at `https://care-api.nubia.com/`.

## Requirements

`manifest.json` leaves `requirements` empty on purpose. The integration uses only the Python standard library and packages Home Assistant already installs:

| Package | Used for |
| --- | --- |
| `aiohttp` | Signed HTTP calls to the parent API |
| `cryptography` | AES-GCM password encryption, matching the Android app |
| `voluptuous` | Config-flow form schema |

Listing those in `requirements` makes Home Assistant reject the manifest.

The app's `APP_KEY`, `APP_SECRET`, and password AES key live in `custom_components/zte_kids/const.py`. They come from the international app build. You do not enter them during setup.

## Install

Copy `custom_components/zte_kids` into your Home Assistant config directory and restart:

```text
config/custom_components/zte_kids/
```

In HACS, add `https://github.com/oggali/ha-ZTE-Kids` as a custom integration repository, install ZTE Kids, and restart.

The version in `manifest.json` is `Year.Month.Day`. Pushing a new version to `master` tags `v<version>` and publishes a GitHub release.

## Setup

Add the **ZTE Kids** integration and sign in with the phone number and password from the ZTE Kids app.

- Login uses the password once. The config entry keeps the access token, openid, display name, and the list of watches.
- When the server asks for a verification code, a second step requests a text message and asks you to enter it.
- Setup stops if the account has no watches.
- One entry per parent account. The openid is the unique id.
- A rejected session starts reauthentication. Enter the password again; the entry is updated in place.

## Location updates

Scheduled polling and a manual refresh are different API calls.

| | History poll | Refresh location |
| --- | --- | --- |
| When | Every 5 minutes | `zte_kids.refresh_location` |
| Endpoint | `api/device/querylocation` | `getway/devices/{imei}/location/last` |
| Effect on the watch | Reads points the server already stored for today | Can ask the watch for a new fix |
| Limit | The update interval | Once a minute per watch |

The history call uses today's date in the Home Assistant time zone. A refresh that returns no point falls back to that same history.

`zte_kids.refresh_location` takes a device target. With no target, every configured watch is included. A watch still inside the one-minute window is skipped. The service fails when every targeted watch was skipped, or when no targeted device belongs to this integration.

## Entities

Each watch is a GPS `device_tracker`. The entity is named from the device name plus **Watch**.

State attributes:

- `imei`
- `address`
- `location_type`
- `gps_timestamp`

The device registry identifier is `(zte_kids, <imei>)`. Positions of `0,0` are ignored. Some API payloads spell longitude `lot`; that field is accepted.
