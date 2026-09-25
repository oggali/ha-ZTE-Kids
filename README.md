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

Add the **ZTE Kids** integration and sign in with the email and password from the ZTE Kids app. The international app accepts an email address, and that address is sent as `loginName`.

- Login uses the password once. The config entry keeps the access token, openid, display name, and the list of watches.
- When the server asks for a verification code, a second step requests a text message and asks you to enter it.
- Setup stops if the account has no watches.
- One entry per parent account. The openid is the unique id.
- A rejected session starts reauthentication. Enter the password again; the entry is updated in place.

## Updates

Scheduled polling reads data the server already stored. A manual refresh is the only call that can wake the watch.

| | History poll | Refresh location |
| --- | --- | --- |
| When | Every 5 minutes | `zte_kids.refresh_location` |
| Location | `api/device/querylocation` | `getway/devices/{imei}/location/last` |
| Other state | Battery, steps, zones, contacts, and the rest of the table below | Not requested |
| Effect on the watch | Reads stored data | Can ask the watch for a new fix |
| Limit | The update interval | Once a minute per watch |

The history call uses today's date in the Home Assistant time zone. A refresh that returns no point falls back to that same history. If one of the extra status calls fails, the last good value for that sensor stays and location still updates. A rejected session still starts reauthentication.

`zte_kids.refresh_location` takes a device target. With no target, every configured watch is included. A watch still inside the one-minute window is skipped. The service fails when every targeted watch was skipped, or when no targeted device belongs to this integration.

## Entities

Each watch is one device, `(zte_kids, <imei>)`. Entity names are the device name plus the name in the table.

| Entity | State | Attributes |
| --- | --- | --- |
| Watch (`device_tracker`) | GPS position | `imei`, `address`, `location_type`, `gps_timestamp` |
| Online | Connected or not | `model`, `phone` |
| Long life mode, low battery alert, call whitelist, position reports, SMS filter, auto answer, scheduled power off, app install | On or off, as last stored. These are not changed from Home Assistant | |
| Sports | Switch. Turns step counting on or off | |
| Do not disturb | Switch. Turns quiet hours on or off | |
| Location mode | Mode 1, 2, or 3 | |
| Find watch | Button. Asks the watch to ring | |
| Battery | Percent | `updated`, `low_battery_alert`, `long_life_mode`, `location_mode` |
| Steps | Steps today | `goal`, `week_steps`, `week_distance`, `week_calories` |
| Distance | Kilometres today | |
| Calories | kcal today | |
| Heart rate | bpm, when the server has one | `updated` |
| Temperature | °C, when the server has one | `updated` |
| Wi-Fi networks | How many are stored | `wifi` (`ssid`, `signal`) |
| Safe zones | How many rules | `safe_zones` (`name`, `enabled`) |
| Places | How many saved places | `places` (`name`, `detail`, `range`) |
| Reminders | How many for today | `reminders` (`content`, `label`, `time`, `date`) |
| SOS numbers | How many | `sos` |
| Contacts | How many | `contacts` (`name`, `phone`) |
| Calls | How many on the first page | `calls` (`name`, `phone`, `time`, `direction`) |
| Messages | How many on the first page | `messages` (`content`, `phone`, `time`) |

Positions of `0,0` are ignored. Some API payloads spell longitude `lot`; that field is accepted. Heart rate and temperature stay unknown until a payload includes them. Calls and messages are the first page of history the server has stored, not a live download from the watch.

Status endpoints used by the 5-minute poll:

| Data | Endpoint |
| --- | --- |
| Online, model, heart rate, temperature | `getway/devices/{imei}` |
| Battery, location mode, SOS, and the on/off flags | `api/device/query/systemconfig` |
| Change a setting or ring the watch | `api/device/save/systemconfig` |
| Steps, distance, calories | `api/sport/query/daily` and `api/sport/query/week` |
| Wi-Fi | `api/device/wifilist` |
| Places | `api/addr/query` |
| Safe zones | `api/guardrule/query` |
| Reminders | `api/scheduleReminder/queryByWeek` |
| Contacts | `api/device/query/contact` |
| Calls | `api/message/calllog/query` |
| Messages | `api/message/sms/query` |
