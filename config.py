"""
Configuration management module for PushButtonDND
Handles loading, saving, and validating configuration from /config.json
"""

import json

try:
    import os
except ImportError:
    os = None


def get_default_config():
    """Return default configuration dictionary"""
    return {
        "version": 1,
        "wifi": {
            "ssid": "***REMOVED***",
            "password": "***REMOVED***"
        },
        "security": {
            "auth_token": "SECRET123"
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
                os.stat('/config.json')
            except OSError:
                # File doesn't exist, return defaults
                print("[CONFIG] No config file found, using defaults")
                return (defaults, None)

        # Read and parse config file
        with open('/config.json', 'r') as f:
            loaded = json.load(f)

        # Merge with defaults to ensure all fields exist
        config = _merge_config(defaults, loaded)

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

        # Create backup of existing config if it exists
        if os and hasattr(os, 'stat'):
            try:
                os.stat('/config.json')
                # File exists, create backup
                try:
                    # Read existing config
                    with open('/config.json', 'r') as f:
                        backup_data = f.read()
                    # Write backup
                    with open('/config.json.backup', 'w') as f:
                        f.write(backup_data)
                    print("[CONFIG] Created backup: /config.json.backup")
                except Exception as e:
                    print(f"[WARN] Could not create backup: {e}")
            except OSError:
                # File doesn't exist, no backup needed
                pass

        # Write to temporary file first (atomic write)
        with open('/config.json.tmp', 'w') as f:
            json.dump(config_dict, f)

        # Rename temp file to actual config
        if os and hasattr(os, 'rename'):
            try:
                os.remove('/config.json')
            except OSError:
                pass  # File might not exist
            os.rename('/config.json.tmp', '/config.json')
        else:
            # Fallback for systems without os.rename
            with open('/config.json.tmp', 'r') as f:
                data = f.read()
            with open('/config.json', 'w') as f:
                f.write(data)

        print("[CONFIG] Configuration saved to /config.json")
        return (True, None)

    except Exception as e:
        error_msg = f"Error saving config: {e}"
        print(f"[ERROR] {error_msg}")
        return (False, error_msg)


def validate_config(config_dict):
    """
    Validate configuration structure and values
    Returns: (valid, error_message)
    """
    try:
        # Check required top-level keys
        required_keys = ['version', 'wifi', 'security', 'mqtt', 'teams', 'features']
        for key in required_keys:
            if key not in config_dict:
                return (False, f"Missing required key: {key}")

        # Validate wifi section
        if 'ssid' not in config_dict['wifi']:
            return (False, "Missing wifi.ssid")
        if 'password' not in config_dict['wifi']:
            return (False, "Missing wifi.password")

        # Validate MQTT port is integer
        if 'port' in config_dict['mqtt']:
            try:
                int(config_dict['mqtt']['port'])
            except (ValueError, TypeError):
                return (False, "mqtt.port must be an integer")

        # Validate MQTT QoS is 0, 1, or 2
        if 'qos' in config_dict['mqtt']:
            qos = config_dict['mqtt']['qos']
            if qos not in [0, 1, 2]:
                return (False, "mqtt.qos must be 0, 1, or 2")

        # Validate Teams polling interval is positive integer
        if 'polling_interval' in config_dict['teams']:
            try:
                interval = int(config_dict['teams']['polling_interval'])
                if interval < 1:
                    return (False, "teams.polling_interval must be positive")
            except (ValueError, TypeError):
                return (False, "teams.polling_interval must be an integer")

        # Validate desk section (optional, only present on desk units)
        if 'desk' in config_dict:
            desk = config_dict['desk']
            if 'receiver_url' in desk:
                if not isinstance(desk['receiver_url'], str):
                    return (False, "desk.receiver_url must be a string")
                if desk['receiver_url'] and not desk['receiver_url'].startswith("http"):
                    return (False, "desk.receiver_url must start with http")

        return (True, None)

    except Exception as e:
        return (False, f"Validation error: {e}")


def factory_reset():
    """
    Delete config file and reboot to defaults
    Use with caution!
    """
    try:
        if os and hasattr(os, 'remove'):
            os.remove('/config.json')
            print("[CONFIG] Factory reset: config.json deleted")

        # Reboot
        import machine
        print("[CONFIG] Rebooting...")
        machine.reset()
    except Exception as e:
        print(f"[ERROR] Factory reset failed: {e}")


def restore_backup():
    """
    Restore configuration from backup file
    Returns: (success, error_message)
    """
    try:
        # Check if backup exists
        if os and hasattr(os, 'stat'):
            try:
                os.stat('/config.json.backup')
            except OSError:
                return (False, "No backup file found")

        # Read backup
        with open('/config.json.backup', 'r') as f:
            backup_data = f.read()

        # Parse to validate
        backup_config = json.loads(backup_data)

        # Validate
        valid, error = validate_config(backup_config)
        if not valid:
            return (False, f"Backup validation failed: {error}")

        # Write to config
        with open('/config.json', 'w') as f:
            f.write(backup_data)

        print("[CONFIG] Restored from backup")
        return (True, None)

    except Exception as e:
        error_msg = f"Error restoring backup: {e}"
        print(f"[ERROR] {error_msg}")
        return (False, error_msg)
