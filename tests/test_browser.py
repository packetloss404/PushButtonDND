"""Real browsers execute the real firmware HTML, JS, and socket routes."""
import json
import os
import re
from pathlib import Path
from urllib.parse import quote

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.support import FirmwareServer

pytestmark = pytest.mark.browser
BROWSERS = os.environ.get('BROWSER_ENGINES', 'chromium,firefox,webkit').split(',')


@pytest.fixture(scope='module', params=BROWSERS)
def browser(request):
    with sync_playwright() as playwright:
        runtime = getattr(playwright, request.param).launch()
        yield runtime
        runtime.close()


@pytest.fixture
def page(browser, request):
    context = browser.new_context(viewport={'width': 1100, 'height': 900})
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    page.set_default_timeout(7000)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    yield page
    folder = Path('test-results') / re.sub(r'[^a-zA-Z0-9_.-]', '_', request.node.nodeid)
    folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder / 'page.png'), full_page=True)
    context.tracing.stop(path=str(folder / 'trace.zip'))
    context.close()
    assert errors == [], errors


@pytest.fixture
def door(tmp_path):
    with FirmwareServer(tmp_path) as server:
        yield server


def config_url(door):
    return door.url + '/config?token=' + quote(door.token, safe='')


def accept_dialogs(page):
    messages = []
    def accept(dialog):
        messages.append(dialog.message)
        dialog.accept()
    page.on('dialog', accept)
    return messages


def test_controls_polling_theme_and_auth(page, door):
    page.goto(door.url)
    expect(page.locator('#glow')).to_have_text('OFF')
    expect(page.locator('#mqttStatus')).to_have_text('MQTT: Disabled')
    # The public page must never disclose the configured secret.
    assert door.token not in page.content()
    page.get_by_role('button', name='ON', exact=True).click()
    expect(page.locator('#control_error')).to_have_text('Invalid API token')
    assert not door.firmware.led_pin.value()
    page.locator('#control_token').fill(door.token)
    page.get_by_role('button', name='ON', exact=True).click()
    expect(page.locator('#glow')).to_have_text('ON')
    assert door.firmware.led_pin.value()
    page.get_by_role('button', name='OFF', exact=True).click()
    expect(page.locator('#glow')).to_have_text('OFF')
    assert not door.firmware.led_pin.value()
    page.locator('#themeToggle').click()
    expect(page.locator('body')).to_have_class('light')
    page.locator('#themeToggle').click()
    expect(page.locator('body')).not_to_have_class('light')
    # Changes made by a desk/API client are picked up by the one-second poll.
    response = page.request.get(door.url + '/api/set', params={'on': '1', 'token': door.token, 'source': 'desk'})
    assert response.ok
    expect(page.locator('#glow')).to_have_text('ON')
    assert page.request.get(door.url + '/api/log').json()[-1]['detail'] == 'ON via desk'
    door.firmware.MQTT_ENABLED = True
    door.firmware.mqtt = type('Status', (), {'connected': True})()
    expect(page.locator('#mqttStatus')).to_have_text('MQTT: Connected')
    door.firmware.mqtt.connected = False
    expect(page.locator('#mqttStatus')).to_have_text('MQTT: Disconnected')
    page.get_by_role('link', name='Settings').click()
    expect(page.get_by_role('heading', name='Configuration')).to_be_visible()


def test_settings_tabs_validation_save_and_reboot_persistence(page, door):
    messages = accept_dialogs(page)
    page.goto(config_url(door))
    page.locator('#wifi_password').fill('WiFi <&" café')
    page.get_by_role('button', name='Show', exact=True).first.click()
    expect(page.locator('#wifi_password')).to_have_attribute('type', 'text')
    page.get_by_role('button', name='Hide', exact=True).click()
    page.get_by_role('button', name='Teams', exact=True).click()
    expect(page.get_by_text('Coming Soon', exact=True)).to_be_visible()
    expect(page.locator('#teams_enabled')).to_be_disabled()
    expect(page.locator('#teams_client_id')).to_be_disabled()
    page.get_by_role('button', name='MQTT', exact=True).click()
    page.locator('#mqtt_port').fill('0')
    page.get_by_role('button', name='Save & Reboot', exact=True).click()
    assert any('MQTT port' in message for message in messages)
    assert door.reboots == 0
    page.locator('#mqtt_port').fill('1883')
    page.locator('#mqtt_enabled').check()
    page.locator('#mqtt_broker').fill('broker.test')
    # Long credentials reproduce the original recv(1024) truncation.
    mqtt_password = 'secreté' * 200
    page.locator('#mqtt_password').fill(mqtt_password)
    page.locator('#mqtt_device_name').fill('DND <&" café')
    page.get_by_role('button', name='Security', exact=True).click()
    new_token = "new'&= +é</script>"
    page.locator('#auth_token').fill(new_token)
    with page.expect_response(lambda r: '/api/config?' in r.url and r.request.method == 'POST') as response:
        page.get_by_role('button', name='Save & Reboot', exact=True).click()
    assert response.value.json()['success'] is True
    page.wait_for_url(door.url + '/', timeout=7000)
    assert door.reboots == 1
    saved, error = door.config.load_config()
    assert error is None
    assert saved['mqtt']['password'] == mqtt_password
    assert saved['wifi']['password'] == 'WiFi <&" café'
    assert saved['security']['auth_token'] == new_token
    page.goto(door.url + '/config?token=' + quote(new_token, safe=''))
    expect(page.locator('#wifi_password')).to_have_value('WiFi <&" café')
    page.get_by_role('button', name='MQTT', exact=True).click()
    expect(page.locator('#mqtt_device_name')).to_have_value('DND <&" café')
    expect(page.locator('#mqtt_password')).to_have_value(mqtt_password)


def test_reset_confirm_cancel_and_blank_auth(page, door):
    page.goto(config_url(door))
    page.once('dialog', lambda dialog: dialog.dismiss())
    page.get_by_role('button', name='Reset to Defaults', exact=True).click()
    assert door.reboots == 0
    messages = accept_dialogs(page)
    with page.expect_response(lambda r: '/api/config/reset' in r.url) as response:
        page.get_by_role('button', name='Reset to Defaults', exact=True).click()
    assert response.value.json()['success']
    page.wait_for_url(door.url + '/')
    assert door.reboots == 1
    assert not Path(door.config.CONFIG_PATH).exists()
    page.get_by_role('button', name='ON', exact=True).click()
    expect(page.locator('#glow')).to_have_text('ON')
    page.get_by_role('link', name='Settings').click()
    expect(page.locator('#ssid')).to_have_value('')


def test_config_theme_validation_cancel_and_flash_failure(page, door):
    messages = accept_dialogs(page)
    page.goto(config_url(door))
    page.locator('#themeToggle').click()
    expect(page.locator('body')).to_have_class('light')
    page.locator('#themeToggle').click()
    expect(page.locator('body')).not_to_have_class('light')
    page.locator('#ssid').fill('')
    page.get_by_role('button', name='Save & Reboot', exact=True).click()
    assert any('WiFi SSID is required' in message for message in messages)
    assert door.reboots == 0
    page.locator('#ssid').fill('Test WiFi')
    # Inject a flash boundary failure; the real API and JS must surface it.
    door.config.save_config = lambda settings: (False, 'Flash write failed')
    with page.expect_event('dialog', predicate=lambda d: 'Flash write failed' in d.message):
        with page.expect_response(lambda r: '/api/config?' in r.url) as response:
            page.get_by_role('button', name='Save & Reboot', exact=True).click()
    assert response.value.status == 500
    assert any('Flash write failed' in message for message in messages)
    assert door.reboots == 0
    page.get_by_role('link', name='Cancel').click()
    expect(page.locator('#glow')).to_have_text('OFF')


def test_mobile_pages_fit_viewport(page, door):
    page.set_viewport_size({'width': 375, 'height': 812})
    for url in (door.url, config_url(door)):
        page.goto(url)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.get_by_role('button', name='MQTT', exact=True).click()
    expect(page.locator('#mqtt_broker')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')


def test_bad_api_requests_do_not_take_server_down(page, door):
    page.goto(door.url)
    assert page.request.get(door.url + '/config').status == 403
    assert page.request.get(door.url + '/api/set').status == 403
    assert page.request.get(door.url + '/api/set', params={'on': '1', 'not_token': door.token}).status == 403
    assert page.request.get(door.url + '/api/set', params={'on': '1', 'token': door.token + 'suffix'}).status == 403
    assert page.request.post(door.url + '/api/config', headers={'Authorization': 'Bearer ' + door.token}, data='{bad').status == 400
    assert page.request.get(door.url + '/api/set/extra?on=1').status == 404
    assert page.request.get(door.url + '/api/config/reset').status == 405
    assert page.request.get(door.url + '/api/set', params={'on': 'invalid', 'token': door.token}).status == 400
    assert page.request.get(door.url + '/api/state').json()['on'] is False


def test_desk_first_boot_setup_form(page, tmp_path):
    with FirmwareServer(tmp_path, kind='desk') as desk:
        page.goto(desk.url)
        expect(page.get_by_role('heading', name='DND Desk Setup')).to_be_visible()
        expect(page.locator('#token')).to_have_value('')
        page.locator('#ssid').fill('Lab café + &')
        page.locator('#password').fill('password +&=é')
        page.locator('#url').fill('http://door.test/api/set?room=office')
        page.locator('#token').fill("token'&=é+")
        page.get_by_role('button', name='Save & Reboot', exact=True).click()
        expect(page.get_by_role('heading', name='Saved!')).to_be_visible()
        settings, error = desk.config.load_config()
        assert error is None
        assert settings['wifi'] == {'ssid': 'Lab café + &', 'password': 'password +&=é'}
        assert settings['security']['auth_token'] == "token'&=é+"
        assert settings['desk']['receiver_url'] == 'http://door.test/api/set?room=office'
        assert desk.reboots == 1
