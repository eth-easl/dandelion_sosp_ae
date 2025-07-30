import sys
from pathlib import Path
import json

RESPONSES = Path('/responses')
REQUESTS = Path('/requests')

with open("/servers/server.txt", 'r') as server_file:
    server_address = [server_file.readline()]

LOG_SERVERS = server_address * 10

# read the response
with open(RESPONSES / 'auth') as f:
    buffer = f.read()
    auth_dict = json.loads(buffer)

for server_index,server_address in enumerate(LOG_SERVERS):
    with open(REQUESTS / f'server_{server_index}', 'w+') as request_file:
        id = server_index * 20
        request_file.write(f"GET http://{server_address}/logs/{id:02} HTTP/1.1\n")
        request_file.write("\n")
        request_file.write(json.dumps({
            "username": auth_dict['authorized']
        }))
