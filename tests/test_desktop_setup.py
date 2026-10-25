"""Setup evidence is ephemeral, scoped and independent from trade permission."""
from crier.desktop_setup import SetupProgress
import asyncio
import threading
import pytest


def test_restart_has_no_network_or_test_evidence():
    progress = SetupProgress()
    assert 'Connect' in progress.message
    assert not progress.can_publish


def test_saved_destination_can_enable_without_mandatory_test_gate():
    progress = SetupProgress()
    progress.account(('alerts', 'paper', 'account'))
    progress.destination('revision', configured=True, enabled=False, paused=False)
    assert progress.can_publish
    assert 'Preview' in progress.message
    token = progress.token
    progress.preview(token)
    assert 'test' in progress.message.lower()
    progress.test(token, 'uncertain')
    assert progress.can_publish
    assert 'uncertain' in progress.message
    assert 'inspect' in progress.message.lower()


def test_account_destination_or_format_change_invalidates_evidence():
    progress = SetupProgress()
    progress.account(('alerts', 'paper', 'account'))
    progress.destination('original', configured=True, enabled=False, paused=False)
    token = progress.token
    progress.preview(token)
    progress.test(token, 'delivered')
    assert progress.test_state == 'delivered'
    progress.destination('new-format', configured=True, enabled=False, paused=False)
    assert not progress.previewed and progress.test_state == 'not requested'
    progress.preview(token)
    progress.test(token, 'delivered')
    assert not progress.previewed and progress.test_state == 'not requested'
    progress.account(None)
    assert not progress.can_publish
    progress.account(('alerts', 'live', 'account'))
    assert not progress.can_publish


def test_enable_and_paused_status_are_distinct_from_acknowledgement():
    progress = SetupProgress()
    progress.account(('alerts', 'paper', 'account'))
    progress.destination('saved', configured=True, enabled=True, paused=True)
    assert 'paused' in progress.message.lower()
    progress.destination('saved', configured=True, enabled=True, paused=False)
    assert 'enabled' in progress.message.lower()
    assert progress.test_state == 'not requested'


def test_duplicate_status_does_not_invalidate_but_reconnect_does():
    progress = SetupProgress()
    scope = ('alerts', 'paper', 'account')
    progress.account(scope)
    progress.destination('same', configured=True, enabled=False, paused=False)
    token = progress.token
    progress.preview(token)
    progress.account(scope)
    assert progress.previewed
    progress.account(None)
    progress.account(scope)
    progress.destination('same', configured=True, enabled=False, paused=False)
    progress.test(token, 'delivered')
    assert not progress.previewed and progress.test_state == 'not requested'


@pytest.mark.parametrize('cancel', [False, True])
@pytest.mark.parametrize('mutation', ['configure', 'settings'])
def test_test_delivery_holds_profile_until_thread_finishes(tmp_path, cancel, mutation):
    from crier.desktop_runtime import DesktopSession
    async def run():
        session = DesktopSession(tmp_path, start_workers=False)
        session.broker = object()  # Verified synthetic scope, no broker interface.
        started, release = threading.Event(), threading.Event()
        def send(client):
            started.set()
            assert release.wait(10), 'Test failed to release synthetic delivery'
            return {'status':'delivered'}
        session.publisher.test_message = send
        delivery = asyncio.create_task(session.discord_test())
        try:
            assert await asyncio.to_thread(started.wait, 5)
            if cancel:
                delivery.cancel()
            switched = asyncio.Event()
            async def switch_profile():
                if mutation == 'configure':
                    await session.discord_configure('https://discord.com/api/webhooks/123/synthetic', False)
                else:
                    await session.discord_settings({'format':'text'})
                switched.set()
            switching = asyncio.create_task(switch_profile())
            await asyncio.sleep(.02)
            assert not switched.is_set()
            release.set()
            if cancel:
                with pytest.raises(asyncio.CancelledError):
                    await delivery
            else:
                assert (await delivery)['status'] == 'delivered'
            await switching
            assert switched.is_set()
        finally:
            release.set()
            await asyncio.gather(delivery, return_exceptions=True)
    asyncio.run(run())


def test_publisher_revision_tracks_destination_and_format_without_returning_secrets(tmp_path):
    import json
    from crier.discord_settings import DiscordPublisher
    from crier.store import Store
    publisher = DiscordPublisher(tmp_path, Store(tmp_path/'alerts.sqlite3'))
    before = publisher.status()['revision']
    publisher.configure('https://discord.com/api/webhooks/123/private-destination-token', False)
    configured = publisher.status()
    assert configured['revision'] != before
    assert 'private-destination-token' not in json.dumps(configured)
    publisher.configure('', True)
    assert publisher.status()['revision'] == configured['revision']
    publisher.settings(dict(configured['settings'], format='text'))
    assert publisher.status()['revision'] != configured['revision']


def test_disconnected_session_cannot_reconfigure_retained_profile(tmp_path):
    from crier.desktop_runtime import DesktopSession
    async def run():
        session = DesktopSession(tmp_path, start_workers=False)
        with pytest.raises(ValueError, match='Connect'):
            await session.discord_configure('https://discord.com/api/webhooks/123/token', True)
        with pytest.raises(ValueError, match='Connect'):
            await session.discord_settings({'format':'text'})
        with pytest.raises(ValueError, match='Connect'):
            await session.discord_test()
        assert not session.publisher.status()['configured']
    asyncio.run(run())


def test_saved_enabled_destination_needs_explicit_session_permission(tmp_path):
    from crier.desktop_runtime import DesktopSession
    async def run():
        session = DesktopSession(tmp_path, start_workers=False)
        session.publisher.configure('https://discord.com/api/webhooks/123/token', True)
        assert session.discord_status()['saved_enabled']
        assert not session.discord_status()['enabled']
        sent = []
        session.publisher.deliver = lambda client: sent.append('sent')
        session.deliver_alerts(None)
        assert not sent
        session.broker = object()
        await session.discord_configure('', True)
        session.deliver_alerts(None)
        assert sent == ['sent']
        await session.discord_settings(dict(session.publisher.status()['settings'], format='text'))
        session.deliver_alerts(None)
        assert sent == ['sent']
        restarted = DesktopSession(tmp_path, start_workers=False)
        assert restarted.discord_status()['saved_enabled']
        assert not restarted.discord_status()['enabled']
    asyncio.run(run())
