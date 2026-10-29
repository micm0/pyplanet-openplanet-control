# Openplanet Control (PyPlanet app)

Kick players who join with Openplanet in a disallowed signature mode.
Uses the detection method from the
[Openplanet docs](https://openplanet.dev/docs/tutorials/detecting-openplanet).

## How it works

To check a player, a hidden ManiaLink is sent to their client. Its
ManiaScript reads `System.ExtraTool_Info` (populated by Openplanet, empty on
vanilla clients) and reports it back once. If the reported signature mode is
not allowed, the player is kicked immediately — the kick reason tells them
which modes are allowed and to switch via the Openplanet menu (F3) and
rejoin. Optionally, an announcement is broadcast in the server chat.

The check runs when a player joins (while enabled) and for everyone online
when the app starts. If a player changes signature mode later, it goes
unnoticed until they rejoin or an admin runs `//opcheck`.

## Install

1. Clone this repo and copy its `openplanet_control` folder into your
   PyPlanet project's `apps/` directory, or anywhere on
   the Python path:

   ```sh
   git clone https://github.com/micm0/pyplanet-openplanet-control.git
   cp -r pyplanet-openplanet-control/openplanet_control /path/to/pyplanet/apps/
   ```
2. Add it to `settings/apps.py`:

   ```python
   APPS = {
       'default': [
           # ... existing apps ...
           'apps.openplanet_control',
       ]
   }
   ```

3. Restart PyPlanet.
4. The check is **off by default**: enable it with `//settings` (`enabled`).

## Configure

Via `//settings` in-game (or the settings backend):

| Setting | Default | Meaning |
|---|---|---|
| `enabled` | `False` | Master switch for the join check |
| `allowed_signature_modes` | `['OFFICIAL']` | Modes Openplanet users may join with. Vanilla clients are always allowed. |
| `kick_announce_message` | (see below) | Chat message broadcast on kick. Placeholders: `{nickname}`, `{login}`, `{mode}`, `{allowed}`. Empty = no announcement. |

Default announcement:

```
$ff0⚠ $<$fff{nickname}$>$ff0 was kicked: Openplanet $<$fff{mode}$>$ff0 mode is not allowed on this server (allowed: $<$fff{allowed}$>$ff0).
```

Any existing signature mode works in `allowed_signature_modes`, e.g.
`OFFICIAL`, `REGULAR`, `SCHOOL`, `DEVMODE` or a competition profile name
(`COMPETITION` for TMWT).

Admin commands:

- `//openplanet` — lists what every online player reported (cached, does not re-run the check).
- `//opcheck` — clears cached reports and re-runs the check (detection **and** enforcement) on all online players.

## Caveats

- A player can pass the check in `OFFICIAL` and switch to `DEVMODE`
  afterwards. This goes unnoticed until they rejoin or an admin runs
  `//opcheck`.

## License

GPL-3.0, the same as PyPlanet. See [LICENSE](LICENSE).
