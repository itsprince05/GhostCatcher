import sys
import traceback
import os

print("--- DEBUG RUNNER STARTING ---")
try:
    print("Importing bot.py...")
    import bot
    print("Import successful. Bot should be running.")
except Exception:
    err = traceback.format_exc()
    print("CRASH DETECTED!")
    print(err)
    with open("launcher_crash.txt", "w") as f:
        f.write(err)
    print("Error saved to launcher_crash.txt")
    input("Press Enter to Exit...")
