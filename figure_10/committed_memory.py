import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

from statistics import mean
from tqdm import tqdm

NUMBER_OF_BUCKETS = 100  # per second
GRANULARITY = (1000 / NUMBER_OF_BUCKETS)

matplotlib.rcParams['pdf.fonttype'] = 42
matplotlib.rcParams['ps.fonttype'] = 42
matplotlib.rcParams.update({'font.size': 15})

def getMinTime(path):
    data = pd.read_csv(path)

    return data['startTime'].min() * 1000

def common_preprocessing(df):
    # extract function name
    df = df.apply(lambda x: x.replace({'^t': ""}, regex=True))
    df = df.apply(lambda x: x.replace({'-[0-9]+$': ""}, regex=True))

    # convert to milliseconds
    TIME_OFFSET = df['start_time'].min()

    df['start_time'] -= TIME_OFFSET
    df['start_time'] /= 1_000_000  # to ms
    df = df.dropna()
    df['start_time'] = df['start_time'].astype(int)

    df['end_time'] -= TIME_OFFSET
    df['end_time'] /= 1_000_000  # to ms
    df['end_time'] = df['end_time'].astype(int)

    # drop first 10 minutes
    # ts = df['start_time'].min() + (df['start_time'].max() - df['start_time'].min()) / 3
    # df = df[df['start_time'] > ts]

    # split invocations into groups
    df['group_start'] = df['start_time'] / GRANULARITY
    df['group_start'] = df['group_start'].astype(int)
    df['group_end'] = df['end_time'] / GRANULARITY
    df['group_end'] = df['group_end'].astype(int)

    return df


def install_memory_usage(df, small_hash, memory_trace_path):
    memory_trace = pd.read_csv(memory_trace_path)

    if small_hash:
        memory_trace['HashFunction'] = memory_trace.apply(lambda x: x['HashFunction'][0:18], axis=1)

    def apply_complex_function(x):
        return memory_trace[memory_trace['HashFunction'] == x['service_name']].iloc[0]['AverageAllocatedMb']

    df['memory'] = df.apply(apply_complex_function, axis=1)

    return df


def prepare_for_plotting(df, granularity):
    groups = {}

    for index, row in tqdm(df.iterrows(), total=df.shape[0]):
        for g in range(row['group_start'], row['group_end'] + 1):
            if g in groups:
                groups[g] += row['memory']
            else:
                groups[g] = row['memory']

    ts = list(groups.keys())
    ram = list(groups.values())

    ts = [x * granularity for x in ts]  # granularity
    ts = [x / 1_000 for x in ts]

    return ts, ram


def process_fc_and_dnd(path, memory_trace_path, fc_min):
    data = pd.read_csv(path)

    def preprocess_data_loader(df):
        df['end_time'] = (df["startTime"] + df['responseTime']) * 1000  # to ns
        df['startTime'] *= 1000  # to ns

        # rename columns
        df = df.rename(columns={
            'startTime': 'start_time',
            'instance': 'service_name'
        })

        # drop out failed invocations
        df = df[(df['connectionTimeout'] == False) & (df['functionTimeout'] == False)]

        # drop out all irrelevant columns
        df = df[['service_name', 'start_time', 'end_time']]

        return df

    def preprocess_proxy_trace(df):
        df = df[df['time'] > fc_min]
        df['start_time'] = df['time'] - (df['proxying'] * 1000)  # end_time => ns; proxying => μs
        df = df[~df['service_name'].str.startswith('warm-function')]

        # rename columns
        df = df.rename(columns={
            'time': 'end_time',
        })

        # drop out all irrelevant columns
        df = df[['service_name', 'start_time', 'end_time']]

        return df

    data = preprocess_proxy_trace(data)
    data = common_preprocessing(data)
    data = install_memory_usage(data, True, memory_trace_path)
    return prepare_for_plotting(data, GRANULARITY)


def process_dandelion(path, memory_trace_path, d_min):
    data = pd.read_csv(path)

    def preprocess_data(df):
        df = df[df['time'] > d_min]
        # calculate end time (start_time already in ns; rest in μs)
        df['end_time'] = df['start_time'] + (df['get_metadata'] + df['add_deployment'] + df['cold_start'] +
                                             df['load_balancing'] + df['cc_throttling'] + df['proxying'] +
                                             df['serialization'] + df['persistence_layer'] + df['other']) * 1000

        # drop out all irrelevant columns
        df = df[['service_name', 'start_time', 'end_time']]

        return df

    data = preprocess_data(data)
    data = common_preprocessing(data)
    data = install_memory_usage(data, True, memory_trace_path)
    return prepare_for_plotting(data, GRANULARITY)


def process_firecracker(path, memory_trace_path, fc_min):
    data = pd.read_csv(path)

    def preprocess_data(df):
        df = df[df['time'] > fc_min]
        df = df[df.service_name.str.contains('^t', regex=True, na=False)]
        df = df[df['success'] == True]
        df = df[['time', 'service_name', 'container_id', 'event']]  # time in ns

        start_events = df[df['event'] == 'CREATE']
        end_events = df[df['event'] == 'DELETE']

        # print(f"START DIFF: {(start_events['time'].max() - start_events['time'].min()) / 60_000_000}")
        # print(f"END DIFF: {(end_events['time'].max() - end_events['time'].min()) / 60_000_000}")

        merged = pd.merge(start_events, end_events, on=["service_name", "container_id"], how='outer')
        merged = merged[['time_x', 'time_y', 'service_name']]
        merged = merged.rename(columns={'time_x': 'start_time', 'time_y': 'end_time'})

        return merged

    data = preprocess_data(data)
    data = common_preprocessing(data)
    data = install_memory_usage(data, True, memory_trace_path)
    return prepare_for_plotting(data, GRANULARITY)


############################################################
############################################################
############################################################

function_count = [100]
iter_mul = [100_000]

for fc in function_count:
    for im in iter_mul:
        print(f"Function count: {fc}")
        print(f"Iteration multiplier: {im}")

        def plotFigure1():
            dandelion_min = 0
            fc_min = getMinTime(f'firecracker_{fc}_{im}/experiment_duration_30.csv')

            #dandelion_path = f'dandelion_{fc}_{im}/proxy_trace.csv'
            firecracker_path = f'firecracker_{fc}_{im}/cold_start_trace.csv'
            fc_and_dnd_path = f'firecracker_{fc}_{im}/proxy_trace.csv'
            memory_trace_path = 'azure_150_memory.csv'

            fc_as_dnd_ts, fc_as_dnd_ram = process_fc_and_dnd(fc_and_dnd_path, memory_trace_path, fc_min)
            firecracker_ts, firecracker_ram = process_firecracker(firecracker_path, memory_trace_path, fc_min)
            #dandelion_ts, dandelion_ram = process_dandelion(dandelion_path, memory_trace_path)

            ############################################################
            ############################################################
            ############################################################

            plt.figure(figsize=(8, 4))

            # Figure 1 - motivation
            plt.plot(fc_as_dnd_ts, fc_as_dnd_ram, label='VMs actively serving requests', color='tab:blue')
            plt.axhline(y=mean(fc_as_dnd_ram), label=None, color='darkblue', linestyle='--') # 'No keep-alive - average'
            print(f'Firecracker (no keep-alive) average: {mean(fc_as_dnd_ram)} MB')

            # Common for Figure 1 (Hot VMs with Knative autoscaling) and Figure 10 (Firecracker w/ Knative autoscaling)
            plt.plot(firecracker_ts, firecracker_ram, label='Firecracker w/ Knative autoscaling', color='purple')
            plt.axhline(y=mean(firecracker_ram), label=None, color='darkmagenta', linestyle='--') # 'Knative autoscaling - average'
            print(f'Firecracker (Knative autoscaling) average: {mean(firecracker_ram)} MB')

            # Figure 10
            #plt.plot(dandelion_ts, dandelion_ram, label='Hummingbird', color='tab:green')
            #plt.axhline(y=mean(dandelion_ram), label=None, color='darkgreen', linestyle='--')
            #print(f'Dandelion average: {mean(dandelion_ram)} MB')

            plt.xlabel('Time [s]')
            plt.ylabel('Committed Memory [MB]')
            plt.xlim([600, 1800])
            plt.ylim([0, 5000])

            # plt.title(f'Azure {fc} - Iteration Multiplier = {im}')
            plt.legend()
            plt.grid()

            # plt.show()
            plt.tight_layout()
            plt.savefig(f'figure1_{fc}_{im}.png')


        def plotFigure10():
            dandelion_min = getMinTime(f'dandelion_{fc}_{im}/experiment_duration_30.csv')
            fc_min = getMinTime(f'firecracker_{fc}_{im}/experiment_duration_30.csv')

            dandelion_path = f'dandelion_{fc}_{im}/proxy_trace.csv'
            firecracker_path = f'firecracker_{fc}_{im}/cold_start_trace.csv'
            fc_and_dnd_path = f'firecracker_{fc}_{im}/proxy_trace.csv'
            memory_trace_path = 'azure_150_memory.csv'

            # fc_as_dnd_ts, fc_as_dnd_ram = process_fc_and_dnd(fc_and_dnd_path, memory_trace_path, fc_min)
            dandelion_ts, dandelion_ram = process_dandelion(dandelion_path, memory_trace_path, dandelion_min)
            firecracker_ts, firecracker_ram = process_firecracker(firecracker_path, memory_trace_path, fc_min)

            ############################################################
            ############################################################
            ############################################################

            plt.figure(figsize=(8, 4))

            #plt.plot(fc_as_dnd_ts, fc_as_dnd_ram, label='VMs actively serving requests', color='tab:blue')
            #plt.axhline(y=mean(fc_as_dnd_ram), label=None, color='darkblue', linestyle='--')  # 'No keep-alive - average'
            #print(f'Firecracker (no keep-alive) average: {mean(fc_as_dnd_ram)} MB')

            # Common for Figure 1 (Hot VMs with Knative autoscaling) and Figure 14 (Firecracker w/ Knative autoscaling)
            plt.plot(firecracker_ts, firecracker_ram, label='Firecracker w/ Knative autoscaling', color='purple')
            plt.axhline(y=mean(firecracker_ram), label=None, color='darkmagenta',
                        linestyle='--')  # 'Knative autoscaling - average'
            print(f'Firecracker (Knative autoscaling) average: {mean(firecracker_ram)} MB')

            # Figure 10
            plt.plot(dandelion_ts, dandelion_ram, label='Hummingbird', color='tab:green')
            plt.axhline(y=mean(dandelion_ram), label=None, color='darkgreen', linestyle='--')
            print(f'Dandelion average: {mean(dandelion_ram)} MB')

            plt.xlabel('Time [s]')
            plt.ylabel('Committed Memory [MB]')
            plt.xlim([600, 1800])
            plt.ylim([0, 5000])

            # plt.title(f'Azure {fc} - Iteration Multiplier = {im}')
            plt.legend()
            plt.grid()

            # plt.show()
            plt.tight_layout()
            plt.savefig(f'figure10_{fc}_{im}.png')

        #plotFigure1()
        plotFigure10()
