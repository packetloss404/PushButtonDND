"""
Configuration management module for PushButtonDND
Handles loading, saving, and validating configuration from /config.json
"""

import json

try:
    import os
except ImportError:
    os = None

CONFIG_PATH = '/config.json'
BACKUP_PATH = '/config.json.backup'
TEMP_PATH = '/config.json.tmp'


def get_default_config():
    """Return default configuration dictionary.

    NOTE: wifi/security values are intentionally blank. Real credentials are
    entered through the on-device AP setup page (see desk.py) and persisted to
    /config.json, which is NOT committed to source control.
    """
    return {
        "version": 1,
        "wifi": {
            "ssid": "",
            "password": ""
        },
        "security": {
            "auth_token": ""
        },
        "mqtt": {
            "enabled": False,
            "broker": "homeassistant.local",
            "port": 1883,
            "username": "",
            "password": "",
            "topic_prefix": "pushbuttondnd",
            "device_name": "DND Light",
            "qos": 1
        },
        "teams": {
            "enabled": False,
            "client_id": "",
            "tenant_id": "",
            "client_secret": "",
            "polling_interval": 300
        },
        "features": {
            "enable_mqtt": False,
            "enable_teams": False
        },
        "desk": {
            "receiver_url": "http://esp-doorlight.local/api/set",
            "source_tag": "desk"
        }
    }


def _merge_config(defaults, loaded):
    """Recursively merge loaded config with defaults (fills missing fields)"""
    result = defaults.copy()

    for key, value in loaded.items():
        if key in result:
            if isinstance(value, dict) and isinstance(result[key], dict):
                result[key] = _merge_config(result[key], value)
            else:
                result[key] = value
        else:
            result[key] = value

    return result


def load_config():
    """
    Load configuration from /config.json
    Returns: (config_dict, error_message)
    If file doesn't exist or is invalid, returns (defaults, error_message)
    """
    defaults = get_default_config()

    try:
        # Check if file exists
        if os and hasattr(os, 'stat'):
            try:
                os.stat(CONFIG_PATH)
            except OSError as error:
                if error.args and error.args[0] == 2:
                    print("[CONFIG] No config file found, using defaults")
                    return (defaults, None)
                raise

        # Read and parse config file
        with open(CONFIG_PATH, 'r') as f:
            loaded = json.load(f)

        # Merge with defaults to ensure all fields exist
        if not isinstance(loaded, dict):
            raise ValueError('Configuration must be an object')
        config = _merge_config(defaults, loaded)
        valid, error = validate_config(config)
        if not valid:
            raise ValueError(error)

        print("[CONFIG] Loaded configuration from /config.json")
        return (config, None)

    except ValueError as e:
        # JSON parsing error
        error_msg = f"Invalid JSON in config file: {e}"
        print(f"[ERROR] {error_msg}")
        return (defaults, error_msg)

    except Exception as e:
        # Other errors
        error_msg = f"Error loading config: {e}"
        print(f"[ERROR] {error_msg}")
        return (defaults, error_msg)


def _replace_file(source, destination):
    """Replace without deleting the last good file before the rename succeeds."""
    if os is None:
        raise OSError('Filesystem unavailable')
    if hasattr(os, 'replace'):
        os.replace(source, destination)
    else:
        # MicroPython littlefs/VFS rename replaces an existing destination.
        os.rename(source, destination)


def save_config(config_dict):
    """
    Atomically save configuration to /config.json
    Writes to temp file first, then renames
    Creates backup of existing config
    Returns: (success, error_message)
    """
    try:
        # Validate before saving
        valid, error = validate_config(config_dict)
        if not valid:
            return (False, f"Validation failed: {error}")

        config_dict = _merge_config(get_default_config(), config_dict)

        # Finish the new file before touching the existing configuration/backup.
        with open(TEMP_PATH, 'w') as f:
            json.dump(config_dict, f)

        # Never replace a valid backup with a corrupt active configuration.
        backup_data = None
        try:
            with open(CONFIG_PATH, 'r') as f:
                previous_text = f.read()
        except OSError as error:
            if not error.args or error.args[0] != 2:
                raise
        else:
            try:
                previous = _merge_config(get_default_config(), json.loads(previous_text))
                previous_valid, _ = validate_config(previous)
                if previous_valid:
                    backup_data = previous_text
            except (ValueError, TypeError, AttributeError):
                pass
        if backup_data is not None:
            with open(BACKUP_PATH + '.tmp', 'w') as f:
                f.write(backup_data)
            _replace_file(BACKUP_PATH + '.tmp', BACKUP_PATH)

        _replace_file(TEMP_PATH, CONFIG_PATH)

        print("[CONFIG] Configuration saved to /config.json")
        return (True, None)

    except Exception as e:
        error_msg = f"Error saving config: {e}"
        print(f"[ERROR] {error_msg}")
        return (False, error_msg)


def validate_config(config_dict):
    """Reject malformed types and values before they reach hardware/network code."""
    if not isinstance(config_dict, dict):
        return (False, "Configuration must be an object")
    for key in ('version', 'wifi', 'security', 'mqtt', 'teams', 'features'):
        if key not in config_dict:
            return (False, "Missing required key: " + key)
    if type(config_dict['version']) is not int or config_dict['version'] != 1:
        return (False, "Unsupported configuration version")
    defaults = get_default_config()
    for section in ('wifi', 'security', 'mqtt', 'teams', 'features', 'desk'):
        if section in config_dict and not isinstance(config_dict[section], dict):
            return (False, section + " must be an object")
    for key in ('ssid', 'password'):
        if key not in config_dict['wifi']:
            return (False, "Missing wifi." + key)
    for section, fields in defaults.items():
        if not isinstance(fields, dict):
            continue
        supplied = config_dict.get(section, {})
        for key, default in fields.items():
            if key not in supplied:
                continue
            value = supplied[key]
            if type(default) is str and not isinstance(value, str):
                return (False, section + "." + key + " must be a string")
            if type(default) is bool and type(value) is not bool:
                return (False, section + "." + key + " must be a boolean")
            if type(default) is int and type(value) is not int:
                return (False, section + "." + key + " must be an integer")
    merged = _merge_config(defaults, config_dict)
    if len(merged['wifi']['ssid'].encode('utf-8')) > 32:
        return (False, "wifi.ssid must be at most 32 UTF-8 bytes")
    mqtt = merged['mqtt']
    if not 1 <= mqtt['port'] <= 65535:
        return (False, "mqtt.port must be between 1 and 65535")
    if mqtt['qos'] not in (0, 1):
        return (False, "mqtt.qos must be 0 or 1 (umqtt.simple does not support QoS 2)")
    if not mqtt['topic_prefix'] or any(c in mqtt['topic_prefix'] for c in ('#', '+', '\x00')):
        return (False, "mqtt.topic_prefix must be nonempty without MQTT wildcards")
    if mqtt['enabled'] and not mqtt['broker'].strip():
        return (False, "mqtt.broker is required when MQTT is enabled")
    if merged['teams']['polling_interval'] < 1:
        return (False, "teams.polling_interval must be positive")
    url = merged['desk']['receiver_url']
    # The desk sends a GET to an explicit HTTP endpoint; fragment and userinfo
    # would be interpreted differently by clients and are not supported.
    if not url.startswith('http://') or not url[7:].split('/', 1)[0] or any(c in url for c in ('#', '@', ' ', '\r', '\n')):
        return (False, "desk.receiver_url must be an http:// URL without credentials or fragments")
    if any(c in merged['security']['auth_token'] for c in ('\r', '\n', '\x00')):
        return (False, "security.auth_token must not contain control characters")
    return (True, None)


def reset_config():
    """Delete the active configuration; retain a backup for explicit recovery."""
    if os is None:
        return (False, "Filesystem unavailable")
    try:
        os.stat(CONFIG_PATH)
    except OSError as error:
        if error.args and error.args[0] == 2:
            return (True, None)
        return (False, str(error))
    try:
        os.remove(CONFIG_PATH)
        return (True, None)
    except OSError as error:
        return (False, str(error))


def factory_reset():
    """Delete the active config and reboot, including when already unconfigured."""
    success, error = reset_config()
    if not success:
        return (False, error)
    import machine
    machine.reset()
    return (True, None)


def restore_backup():
    """Validate and atomically restore backup without overwriting that backup."""
    try:
        with open(BACKUP_PATH, 'r') as f:
            backup_config = _merge_config(get_default_config(), json.load(f))
        valid, error = validate_config(backup_config)
        if not valid:
            return (False, "Backup validation failed: " + error)
        with open(TEMP_PATH, 'w') as f:
            json.dump(backup_config, f)
        _replace_file(TEMP_PATH, CONFIG_PATH)
        return (True, None)
    except Exception as error:
        return (False, "Error restoring backup: " + str(error))
