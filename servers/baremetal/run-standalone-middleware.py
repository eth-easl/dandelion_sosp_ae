# run, then make http requests as follows:
# curl --header "Authorization: Bearer fapw84ypf3984viuhsvpoi843ypoghvejkfld" --request GET localhost:8080

import subprocess, os
from urllib import request

handle = subprocess.Popen(["cargo", "run"], cwd='../../http_storage')

while True:
    try:
        req = request.Request('http://localhost:8000')
        resp = request.urlopen(req)
        assert resp.status == 200
        break
    except:
        pass

if handle.returncode is not None:
    raise Exception("Failed to start the server")

try:
    main = subprocess.Popen(
        ["cargo", "run", "--features", "middleware"],
        env=dict(os.environ, STORAGE_HOST="127.0.0.1:8000"),
    )
    main.wait()
finally:
    handle.kill()
