"""
Openplanet Control — PyPlanet app.

To check a player, a hidden ManiaLink is sent to their client. Its
ManiaScript reads System.ExtraTool_Info (populated by Openplanet, empty on
vanilla clients) and reports it back once via TriggerPageAction. If the
player runs Openplanet in a signature mode that is not in the allowed list,
they are kicked immediately and (optionally) an announcement is posted in
the server chat.

The check runs when a player joins (while enabled) and for everyone online
when the app starts. If a player changes signature mode later, it goes
unnoticed until they rejoin or an admin runs //opcheck.

Settings (//settings):
  * enabled: master switch. Default: False.
  * allowed_signature_modes: modes Openplanet users may join with.
    Default: ['OFFICIAL']. Players without Openplanet are always allowed.
    Any existing signature mode works, e.g. OFFICIAL, REGULAR, SCHOOL,
    DEVMODE or a competition profile name.
  * kick_announce_message: chat message broadcast to the server when a
    player is kicked. Placeholders: {nickname}, {login}, {mode}, {allowed}.
    Set empty to disable the announcement.

Admin commands:
  * //openplanet: lists what every online player reported (cached, does not
    re-run the check).
  * //opcheck: clears cached reports and re-runs the check (detection and
    enforcement) on all online players, e.g. mid-round.
"""
import logging
import re

from pyplanet.apps.config import AppConfig
from pyplanet.apps.core.maniaplanet import callbacks as mp_signals
from pyplanet.contrib.command import Command
from pyplanet.contrib.setting import Setting
from pyplanet.views import View

logger = logging.getLogger(__name__)

# "Openplanet 1.26.30 (Next, official, 2026-05-01) [OFFICIAL]"
# No bracketed suffix means the default mode -> REGULAR.
OPENPLANET_RE = re.compile(r'^Openplanet (\S+)')
SIG_MODE_RE = re.compile(r' \[([A-Z_]+)\]$')

REPORT_ACTION = 'op_report'

# Single-shot ManiaScript probe: reports System.ExtraTool_Info once on load.
# Placeholders replaced with .replace() because ManiaScript uses braces.
PROBE_BODY = """
<script><![CDATA[
main() {
	TriggerPageAction("__ML_ID____" ^ "__ACTION__|" ^ System.ExtraTool_Info);
}
]]></script>
"""


class OpenplanetProbeView(View):
	"""Hidden manialink carrying the detection script."""

	def __init__(self, app):
		super().__init__(manager=app.context.ui)
		self.app = app
		self.id = 'pyplanet__openplanet_probe'
		self.body = (
			PROBE_BODY
			.replace('__ML_ID__', self.id)
			.replace('__ACTION__', REPORT_ACTION)
		)

	async def handle_catch_all(self, player, action, values, **kwargs):
		# `action` arrives with the view id + '__' already stripped.
		prefix = REPORT_ACTION + '|'
		if not action.startswith(prefix):
			return
		await self.app.on_report(player, action[len(prefix):])


class OpenplanetControl(AppConfig):
	game_dependencies = ['trackmania_next', 'trackmania']
	app_dependencies = ['core.maniaplanet']

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

		self.probe = OpenplanetProbeView(self)
		self.reports = dict()  # login -> dict(raw, has_op, version, mode)

		self.setting_enabled = Setting(
			'enabled', 'Enable Openplanet check', Setting.CAT_BEHAVIOUR, type=bool,
			description='Check Openplanet signature mode when a player joins, and kick if not allowed.',
			default=False,
		)
		self.setting_allowed_modes = Setting(
			'allowed_signature_modes', 'Allowed signature modes', Setting.CAT_BEHAVIOUR, type=list,
			description="Signature modes Openplanet users may join with. Players without Openplanet "
						"are always allowed. Any existing signature mode works, e.g. OFFICIAL, REGULAR, "
						"SCHOOL, DEVMODE or a competition profile name.",
			default=['OFFICIAL'],
		)
		self.setting_announce = Setting(
			'kick_announce_message', 'Kick announcement message', Setting.CAT_BEHAVIOUR, type=str,
			description='Chat message broadcast when a player is kicked. '
						'Placeholders: {nickname}, {login}, {mode}, {allowed}. Empty = no announcement.',
			default='$ff0⚠ $<$fff{nickname}$>$ff0 was kicked: Openplanet $<$fff{mode}$>$ff0 mode '
					'is not allowed on this server (allowed: $<$fff{allowed}$>$ff0).',
		)

	async def on_start(self):
		await self.context.setting.register(
			self.setting_enabled, self.setting_allowed_modes, self.setting_announce,
		)

		await self.instance.permission_manager.register(
			'manage', 'View Openplanet detection status', app=self, min_level=2,
		)
		await self.instance.command_manager.register(
			Command(command='openplanet', target=self.command_status,
					perms='openplanet_control:manage', admin=True,
					description='Show Openplanet status of online players.'),
			Command(command='opcheck', target=self.command_recheck,
					perms='openplanet_control:manage', admin=True,
					description='Re-run the Openplanet check on all online players.'),
		)

		self.context.signals.listen(mp_signals.player.player_connect, self.on_connect)
		self.context.signals.listen(mp_signals.player.player_disconnect, self.on_disconnect)

		# Also probe players already online when the app (re)starts.
		for player in self.instance.player_manager.online:
			await self.probe.display(player_logins=[player.login])

	async def on_stop(self):
		try:
			await self.probe.hide()
		except Exception:
			pass

	# == Signals ==============================================================

	async def on_connect(self, player, **kwargs):
		if not await self.setting_enabled.get_value():
			return
		await self.probe.display(player_logins=[player.login])

	async def on_disconnect(self, player, **kwargs):
		self.reports.pop(player.login, None)

	# == Detection ============================================================

	@staticmethod
	def parse_info(raw):
		"""Parse a System.ExtraTool_Info string. Empty string = vanilla client."""
		match = OPENPLANET_RE.match(raw)
		if not match:
			return dict(raw=raw, has_op=False, version=None, mode=None)
		mode_match = SIG_MODE_RE.search(raw)
		return dict(
			raw=raw,
			has_op=True,
			version=match.group(1),
			mode=mode_match.group(1) if mode_match else 'REGULAR',
		)

	async def on_report(self, player, raw):
		# Only act on the first report per session (join-time check).
		if player.login in self.reports:
			return
		report = self.parse_info(raw)
		self.reports[player.login] = report
		logger.debug('Openplanet report from %s: %r', player.login, raw)

		if not await self.setting_enabled.get_value():
			return
		if not report['has_op']:
			return

		allowed = [str(m).upper() for m in (await self.setting_allowed_modes.get_value() or [])]
		if report['mode'] in allowed:
			return

		allowed_text = ', '.join(allowed) if allowed else '(none)'
		logger.info(
			'Kicking %s: Openplanet mode %s not allowed (version %s).',
			player.login, report['mode'], report['version'],
		)
		try:
			await self.instance.gbx(
				'Kick', player.login,
				'Openplanet signature mode {} is not allowed on this server. '
				'Allowed: {}. Switch via the Openplanet menu (F3) and rejoin.'.format(
					report['mode'], allowed_text),
			)
		except Exception as exc:
			# Player may have left already.
			logger.debug('Kick of %s failed: %s', player.login, exc)
			return

		announce = str(await self.setting_announce.get_value() or '').strip()
		if announce:
			try:
				await self.instance.chat(announce.format(
					nickname=player.nickname, login=player.login,
					mode=report['mode'], allowed=allowed_text,
				))
			except (KeyError, IndexError, ValueError) as exc:
				logger.warning('Invalid kick_announce_message template: %s', exc)

	# == Commands =============================================================

	async def command_recheck(self, player, data, **kwargs):
		"""Clear cached reports and re-probe everyone online (also re-enforces)."""
		online = list(self.instance.player_manager.online)
		self.reports.clear()
		for target in online:
			await self.probe.display(player_logins=[target.login])
		await self.instance.chat(
			'$09fRe-running Openplanet check on $<$fff{}$> online player(s)...'.format(len(online)),
			player,
		)

	async def command_status(self, player, data, **kwargs):
		lines = ['$09fOpenplanet status of online players:']
		for online in self.instance.player_manager.online:
			report = self.reports.get(online.login)
			if report is None:
				status = '$888no report (yet)'
			elif not report['has_op']:
				status = '$0f0vanilla'
			else:
				status = '$ff0Openplanet {} $fff[{}]'.format(report['version'], report['mode'])
			lines.append('$fff{} $z$s— {}'.format(online.nickname, status))
		await self.instance.chat('\n'.join(lines), player)
