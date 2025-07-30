import sys
from pathlib import Path
from json import dumps
from os import listdir

INPUTS = Path('/responses')
OUTPUT_REQUESTS = Path('/requests')

with open("/servers/server.txt", 'r') as auth_server_file:
    AUTH_SERVER = auth_server_file.readline()

with open(INPUTS / 'Authorization', 'r') as f:
    kind, token = f.read().strip().split(" ")
    assert(kind == "Bearer")
with open(OUTPUT_REQUESTS / 'auth', 'w+') as f:
    f.write(f"POST http://{AUTH_SERVER}/authorize HTTP/1.1 \n")
    f.write("Content-Type: application/json\n")
    f.write("\n")
    f.write(dumps({'token': token}))
