import datetime
import re
import os
import sys
import pandas as pd
import matplotlib.pyplot as plt

output_path = "/home/bgoranov/workplace/dandelionExperiments/figures/latency_dist_800"


def read_tcpdump(path):
    with open(path) as f:
        data = pd.Series(f.readlines()[:-1])

    def read_time(x):
        return x.split(' ')[0]

    def read_src_ip(x):
        return x.split(' ')[2][:x.split(' ')[2].rfind('.')]

    def read_src_port(x):
        return x.split(' ')[2][x.split(' ')[2].rfind('.')+1:]

    def read_dst_ip(x):
        return x.split(' ')[4][:x.split(' ')[4].rfind('.')]

    def read_dst_port(x):
        return x.split(' ')[4][x.split(' ')[4].rfind('.')+1:]

    def read_rest(x):
        return ' '.join(x.split(' ')[7:])

    df = pd.DataFrame(columns=['time', 'src_ip', 'src_port', 'dst_ip', 'dst_port', 'content'])
    df['time'] =        data.apply(read_time)
    df['src_ip'] =      data.apply(read_src_ip)
    df['src_port'] =    data.apply(read_src_port)
    df['dst_ip'] =      data.apply(read_dst_ip)
    df['dst_port'] =    data.apply(read_dst_port)
    df['content'] =     data.apply(read_rest)

    def convert_time(t):
        dt = datetime.datetime.strptime('2024-02-11 ' + t, '%Y-%m-%d %H:%M:%S.%f')
        dt = dt + datetime.timedelta(hours=1)
        return int(dt.timestamp() * 1e6)

    df['time_μs'] = df['time'].apply(convert_time)

    requests = df[df['content'].str.contains('HTTP') & df['content'].str.contains('POST')]
    responses = df[df['content'].str.contains('HTTP') & ~df['content'].str.contains('POST')]

    return requests, responses


def print_statistics(name, s: pd.Series):
    print(f'[{name}] len={len(s)}, min={s.min()}, max={s.max()}, mean={s.mean()}')


assert len(sys.argv) == 2
file_path = sys.argv[1]

# Read the CSV file
df = pd.read_csv(file_path)
df = df.sort_values(by='startTime')

# Reset start time to zero
min_start_time = df['startTime'][0]
df['startTime'] = df['startTime'] - min_start_time
df = df[1:-1]

# Convert 'startTime' from microseconds to seconds
start_second = (df['startTime'] / 1e6).astype('int')

# Group by 'startTime' and count the number of requests per second
requests_per_second = start_second.groupby(start_second).size()

iat = df['startTime'].diff()
print_statistics('loader_iat', iat)

# Read the tcpdump file
match = re.search('(.*)-loader.csv', file_path)
if match:
    prefix = match.group(1)
    client_requests, _ = read_tcpdump(prefix + '-tcpdump-client.txt')
    server_requests, _ = read_tcpdump(prefix + '-tcpdump-server.txt')
    client_request_time = client_requests['time_μs'].sort_values() - min_start_time
    server_request_time = server_requests['time_μs'].sort_values() - min_start_time
    client_request_time = client_request_time[len(client_request_time)-len(df):]
    server_request_time = server_request_time[len(server_request_time)-len(df):]
    client_iat = client_request_time.diff()
    server_iat = server_request_time.diff()

    print_statistics('client_iat', client_iat)
    print_statistics('server_iat', server_iat)

# Plot
fig, ax = plt.subplots(4, figsize=(10, 8))
ax[0].plot(requests_per_second)
ax[0].set_ylabel('RPS (sent)')
ax[1].scatter(df['startTime'] / 1e6, iat, s=3)
ax[1].set_ylabel('Loader IAT [us]')
if match:
    ax[2].scatter(client_request_time / 1e6, client_request_time.values - df['startTime'], s=3, label='client')
    ax[2].scatter(server_request_time / 1e6, server_request_time.values - df['startTime'], s=3, label='server')
    ax[2].set_ylabel('Loader TS Diff [us]')
    ax[2].legend()
ax[3].scatter(df['startTime'] / 1e6, df['responseTime'], s=3)
ax[3].set_ylabel('Latency [us]')
plt.xlabel('Exp. Time [s]')

if not os.path.exists(output_path):
    os.makedirs(output_path)

plt.savefig(output_path + '/latency_over_time.png')
