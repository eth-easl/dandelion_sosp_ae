import sys
from pathlib import Path
import glob
import json
from jinja2 import Template

TEMPLATE = Template('''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Logs</title>
</head>
<body>
    <table>
        <tr>
            <th>Timestamp</th>
            <th>Server ID</th>
            <th>Event Type</th>
            <th>Details</th>
        </tr>
        {% for event in events %}
        <tr>
            <td>{{ event['timestamp'] }}</td>
            <td>{{ event['server_id'] }}</td>
            <td>{{ event['type'] }}</td>
            <td>{{ event['details'] }}</td>
        </tr>
        {% endfor %}
    </table>
</body>
''')


out_file = open('/requests/log.txt', 'w+')
log_files = glob.glob('/responses/*')
all_events = []
for file in log_files:
    with open(file, 'r') as log_file:
        log_buffer = log_file.read()
        log_dict = json.loads(log_buffer)
        all_events.extend(log_dict['events'])
all_events.sort(key=lambda x: x['timestamp'])
reponse_str = TEMPLATE.render(events=all_events)
out_file.write(reponse_str)