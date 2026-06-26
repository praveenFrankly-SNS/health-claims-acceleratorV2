import os
import configparser

cfg_path = os.path.expanduser("~/.databrickscfg")
print(f"Checking for .databrickscfg at: {cfg_path}")

if os.path.exists(cfg_path):
    print("OK: File exists.")
    try:
        config = configparser.ConfigParser()
        config.read(cfg_path)
        print("\nAvailable profiles:")
        for section in config.sections():
            host = config.get(section, "host", fallback="Not set")
            print(f"  Profile: [{section}] - Host: {host}")
    except Exception as e:
        print(f"Error parsing .databrickscfg: {e}")
else:
    print("FAIL: File does not exist.")
