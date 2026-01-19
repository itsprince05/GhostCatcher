import py_compile
try:
    py_compile.compile('user_handler.py', doraise=True)
    print("user_handler.py: OK")
except Exception as e:
    print(f"user_handler.py: ERROR - {e}")

try:
    py_compile.compile('bot.py', doraise=True)
    print("bot.py: OK")
except Exception as e:
    print(f"bot.py: ERROR - {e}")
