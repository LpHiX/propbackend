from datetime import datetime, timezone



print(datetime.now().astimezone().timestamp() * 1000)
print(datetime.now(tz=timezone.utc).timestamp() * 1000)