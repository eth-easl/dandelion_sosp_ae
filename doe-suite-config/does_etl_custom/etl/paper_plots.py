import json
from doespy.etl.steps.extractors import Extractor
from doespy.etl.steps.transformers import Transformer
from doespy.etl.steps.loaders import Loader, PlotLoader

import seaborn as sns
import pandas as pd
from typing import Dict, List, Tuple, Match
import matplotlib.pyplot as plt
import matplotlib.ticker
from matplotlib.lines import Line2D
import itertools 
import re 
from numpy import int64,ndarray
from pathlib import PurePath 
import pickle
from .helpers import *
import math
from .general import create_fig 
import os

class LineStyle:
    def __init__(self, name, marker, color, linestyle='solid'):
        self.name = name
        self.marker = marker
        self.color = color
        self.linestyle = linestyle

MOTIVATION_LINE_DICT = {
    ('firecracker', '1.00'): LineStyle('100% hot', 's', 'darkorange'),
    ('firecracker', '0.99'): LineStyle('99% hot', 'o', 'crimson'),
    ('firecracker', '0.97'): LineStyle('97% hot', '^', 'crimson'),
    ('firecracker', '0.95'): LineStyle('95% hot', 'x', 'crimson'),
    ('firecracker_snapshot', '0.99'): LineStyle('Snapshot 99% hot', 'o', 'mediumvioletred'),
    ('firecracker_snapshot', '0.97'): LineStyle('Snapshot 97% hot', '^', 'mediumvioletred'),
    ('firecracker_snapshot', '0.95'): LineStyle('Snapshot 95% hot', 'x', 'mediumvioletred'),
    }

LINE_DICT = {
    'dandelion_cheri': LineStyle('HB cheri', '^', 'lightseagreen'),
    'dandelion_wasm': LineStyle('HB RWasm', 'v', 'darkgreen'),
    'dandelion_process': LineStyle('HB process', '>', 'forestgreen', 'dashdot'),
    'dandelion_process_libc': LineStyle('HB process w/ hlibc', '>', 'darkgreen', 'dotted'),
    'dandelion_kvm': LineStyle('HB KVM', 'o', 'darkcyan'),
    'firecracker': LineStyle('FC', 'D', 'crimson', (5, (10, 3))),
    'firecracker_snapshot': LineStyle('FC w/ snapshot', 's', 'mediumvioletred', 'dashed'),
    'gvisor_kvm': LineStyle('gVisor', 'X', 'blueviolet', 'dashed'),
    'wasmtime': LineStyle('WT', 'P', 'darkorange', 'solid'),
    }

COLD_LINE_DICT = {
    'dandelion_process': LineStyle('HB process', '<', 'yellowgreen'),
    'dandelion_kvm': LineStyle('HB KVM', 's', 'lightskyblue'),
    'firecracker_snapshot': LineStyle('FC w/ snapshot', 'o', 'purple'),
}

def set_fonts():
    SMALL_SIZE = 16
    MEDIUM_SIZE = 28
    BIGGER_SIZE = 28

    plt.rc('font', size=MEDIUM_SIZE)          # controls default text sizes
    plt.rc('axes', titlesize=MEDIUM_SIZE)     # fontsize of the axes title
    plt.rc('axes', labelsize=MEDIUM_SIZE)    # fontsize of the x and y labels
    plt.rc('xtick', labelsize=MEDIUM_SIZE)    # fontsize of the tick labels
    plt.rc('ytick', labelsize=MEDIUM_SIZE)    # fontsize of the tick labels
    plt.rc('legend', fontsize=MEDIUM_SIZE)    # legend fontsize
    plt.rc('figure', titlesize=BIGGER_SIZE)  # fontsize of the figure title

class MotivationLatencyExtractor(Extractor):
    
    def default_file_regex():
        return [r"latencies.*\.csv$"]

    def extract(self, path: str, options: Dict) -> List[Dict]:
        set_fonts()
        log_summary_path = PurePath(path).with_suffix('.pkl')
        try:
            log_summary_file = open(log_summary_path, 'rb')
            return pickle.load(log_summary_file)
        except: 
            pass
        latency_log = open(path)
        end2end_list = []
        total_requests = 0
        total_failures = 0
        path_parser = re.fullmatch("(.*)hot_([0-9]+)_rate\.csv",path)
        # path_parser = re.fullmatch("(.*)hot_([0-9]+)_rps\.csv",path)
        for index, latency_line in enumerate(latency_log.readlines()[1:]):
            current_latency = re.fullmatch("http://[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}:8080/(\w+)/(\w+),([0-9]+),([0-9]+),(\w+),(\w+),([0-9]{1,3})\n", latency_line)
            if current_latency is not None:
                total_requests = total_requests + 1
                # check if timeout or other failure
                if current_latency[5] == "true" or current_latency[6] == "true":
                    total_failures = total_failures + 1
                end2end_list.append(int(current_latency[4])/1000)
            else:
                print(f"could not parse latency line for {path} at line {index + 1}")

        end2end_series = pd.Series(end2end_list)
        span_dict = { "rps" : int(path_parser[2]),
                     "total_requests": total_requests,
                     "total_failures": total_failures} 
        percentiles = [5, 50, 90, 95, 99, 99.5, 99.9]
        if 'percentiles' in options.keys():
            percentiles = options['percentiles'] 
        for percentile in percentiles:
            span_dict[f"latency_p{percentile:3.1f}"] = end2end_series.quantile(percentile/100)
        log_summary_file = open(log_summary_path, 'wb')
        pickle.dump([span_dict],log_summary_file) 
        return [span_dict] 

class MotivationLoadLatencyPlotLoader(PlotLoader):

    percentiles: List[int]

    def load(self, df: pd.DataFrame, options: Dict, etl_info: Dict) -> None:
        if not df.empty:
            # df=df[(df['server'] == 'firecracker') | (df['server'] == 'dedicated')]
            df=df[ df['total_failures'] / df['total_requests'] < 0.005]
            for percentile in options['percentiles']:
                figurename = f"firecracker_motivation_hot-vs-cold"
                plt.rcParams.update({'font.size': 22})
                fig = self.create_fig(df, options)
                output_dir = self.get_output_dir(etl_info)
                file_name = figurename.replace(' ', '_').replace(":","_")
                self.save_plot(fig, filename=file_name, output_dir=output_dir)

    def create_fig(self, df, options):
        set_fonts()

        max_x = 4500
        max_y = 1500
        # print([cols for cols in df.columns if 'latency' in cols])
        fig,axis = plt.subplots(figsize=(9.5,7))
        x_col_name = 'rps'
        y_col_name = f'latency_p99.5' 
        grouped = df.groupby(['server', 'hotpercent'])
        for (group_name, group) in grouped:
            group.sort_values(x_col_name, ignore_index=True, inplace=True)
            x_data = group[x_col_name]
            new_x_series = pd.Series(data={x_data.size: x_data.iat[x_data.size-1]+1})
            x_data = pd.concat([x_data, new_x_series])
            y_data = group[y_col_name]
            new_y_series = pd.Series(data={y_data.size: max_y*2})
            y_data = pd.concat([y_data, new_y_series])
            # append datapoint past the last one to give the ultimate knee
            if group_name[0] == 'firecracker_snapshot':
                style = 'dashed'
            else: 
                style = 'solid'
            axis.plot(
                x_data,
                y_data,
                linestyle=style,
                label=MOTIVATION_LINE_DICT[group_name].name,
                marker=MOTIVATION_LINE_DICT[group_name].marker,
                color=MOTIVATION_LINE_DICT[group_name].color, 
                markersize=10,
                markevery=2,
            )
        axis.grid(True)
        # axis.set_title(figure_name)

        # use the first axis as for labels and handles, as they should be the same across all 
        handles,labels = axis.get_legend_handles_labels()
        axis.set_yscale('log')
        axis.set_xlim(left=0, right=max_x)
        axis.set_ylim(bottom=1, top=max_y)
        axis.set_xlabel('RPS')
        axis.set_ylabel(f'p99.5 latency [ms]')
        fig.legend(handles, labels, loc="center left", bbox_to_anchor=(0.96, 0.6))
        fig.tight_layout()
        return fig

class UtilExtractor(Extractor):

    def default_file_regex():
        return [r"util\.csv$"]

    def extract(self, path: str, options: Dict) -> List[Dict]: 
        return []

good_thresholds = [4, 35]
class HotVMsExtractor(Extractor):
    
    def default_file_regex():
        return [r"latencies.*\.csv$"]

    def extract(self, path: str, options: Dict) -> List[Dict]: 
        from collections import defaultdict
        summary_path = PurePath(path).with_suffix('.pkl')
        try:
            summary_file = open(summary_path, 'rb')
            return pickle.load(summary_file)
        except: 
            pass

        latency_log = open(path)
        total_requests = 0
        succussul_requests = 0
        good_requests = defaultdict(int)
        min_timestamp = None
        max_timestamp = None
        path_parser = re.fullmatch("(.*)hot_([0-9]+)_rate\.csv", path)
        rps = int(path_parser[2])
        for index, latency_line in enumerate(latency_log.readlines()[1:]):
            current_entry = re.fullmatch("http://[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}:8080/(\w+)/(\w+),([0-9]+),([0-9]+),(\w+),(\w+),([0-9]{1,3})\n", latency_line)
            current_timestamp = int(current_entry[3])
            if min_timestamp == None:
                min_timestamp = current_timestamp
                max_timestamp = current_timestamp
            else:
                min_timestamp = min(min_timestamp, current_timestamp)
                max_timestamp = max(max_timestamp, current_timestamp)
            if current_entry is not None:
                total_requests += 1
                if current_entry[5] == "false" and current_entry[6] == "false":
                    succussul_requests += 1
                    current_latency_ms = int(current_entry[4]) / 1000
                    for threshold in good_thresholds:
                        if current_latency_ms < threshold:
                            good_requests[threshold] += 1
            else:
                print(f"could not parse latency line for {path} at line {index + 1}")

        duration_sec = (max_timestamp - min_timestamp) / 1000000
        span_dict = {'throughput' : succussul_requests / duration_sec,
                     'model': 'open' if 'open' in path else 'close'}
        for threshold in good_thresholds:
            span_dict[f'goodput(SLO<{threshold}ms)'] = good_requests[threshold] / duration_sec

        summary_file = open(summary_path, 'wb')
        pickle.dump([span_dict],summary_file) 

        return [span_dict] 

class HotVMsPlotLoader(PlotLoader):

    def load(self, df: pd.DataFrame, options: Dict, etl_info: Dict) -> None:
        if not df.empty:
            figurename = f"MotivationVMthroughput"
            # plt.rcParams.update({'font.size': 22})
            fig = self.create_fig(df, options)
            output_dir = self.get_output_dir(etl_info)
            file_name = figurename.replace(' ', '_').replace(":","_")
            self.save_plot(fig, filename=file_name, output_dir=output_dir)

    def create_fig(self, df, options):
        set_fonts()

        fig,axis = plt.subplots(figsize=(15, 7))

        x_col_name = 'hot_vms'
        axis.grid(True, which='major')
        # axis.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
        # axis.get_xaxis().set_tick_params(which='minor', size=0)
        # axis.get_xaxis().set_tick_params(which='minor', width=0)
        # axis.set_xticks([4, 6, 8, 12, 16, 24, 32, 48, 64])
        axis.set_xticks([0, 1, 2, 3, 4, 6, 8, 12, 16])
        axis.set_xlabel('# of sandboxes concurrently executing per core')
        axis.set_ylabel('RPS')
        axis.minorticks_on()


        y_col_names = ['throughput']
        for threshold in good_thresholds:
            y_col_names.append(f'goodput(SLO<{threshold}ms)')

        df = df.groupby(['function', x_col_name])[y_col_names].max().reset_index()
        grouped = df.groupby('function')
        for (group_name, group) in grouped:
            group.sort_values(x_col_name, ignore_index=True, inplace=True)
            x_data = group[x_col_name] / 16
            for y_col_name in y_col_names:
                if group_name == 'matmul' and str(good_thresholds[1]) in y_col_name:
                    continue
                if group_name == 'io-scale' and str(good_thresholds[0]) in y_col_name:
                    continue
                y_data = group[y_col_name]
                # y_data = y_data / max(y_data)
                if 'SLO' in y_col_name:
                    line_style = "dashed"
                    marker = '^'
                    color = "blue" if "matmul" in group_name else "orange"
                else:
                    line_style = "solid" 
                    marker = 'o'
                    color = "darkblue" if "matmul" in group_name else "darkorange"
                if group_name == 'io-scale':
                    label = f'io-chain {y_col_name}'
                else:
                    label = f'{group_name} {y_col_name}'
                axis.plot(
                    x_data,
                    y_data,
                    linestyle=line_style,
                    linewidth=3,
                    color=color, 
                    label=label,
                    marker=marker,
                    markersize=12,
                )

        handles,labels = axis.get_legend_handles_labels()
        axis.set_ylim(bottom=0)
        fig.legend(handles, labels, loc="lower center", ncols=2, bbox_to_anchor=(0.5, -0.2))
        fig.tight_layout()
        return fig

class MorelloTimestampExtractor(Extractor):

    quartiles: Tuple[float,float] = (0.25,0.75)
    whiskers: Tuple[int,int] = (0.05,0.95)

    def default_file_regex():
        return [r"timestamps.*\.csv$"]

    def extract(self, path: str, options: Dict) -> List[Dict]:
        summary_path = PurePath(path).with_suffix('.pkl')
        try:
            summary_file = open(summary_path, 'rb')
            return [pickle.load(summary_file)]
        except: 
            pass
        timestamp_file = open(path)
        path_parser = re.fullmatch("(.*)hot_([0-9]+)_rate\.csv",path)
        series_list = []
        next(timestamp_file)
        for timestamp_line in timestamp_file:
 
            event_list = re.findall("parent:([0-9]+), span:([0-9]+), time:([0-9]+), point:(\w+)", timestamp_line)
            # pairs that we are looking for
            # Load start / end
            def findEvent(evt_list, name):
                evt_candidate = [event for event in evt_list if event[3] == name]
                if len(evt_candidate) < 1:
                    raise ValueError("did not find event candidate for f{name} in f{evt_list}") 
                elif len(evt_candidate) > 1: 
                    raise ValueError("did find more than one event candidate for f{name} in f{evt_list}") 
                return evt_candidate[0]
            arrival_start = findEvent(event_list, "Arrival")
            arrival_end = findEvent(event_list, "PrepareEnvQueue")
            arrival_time = int(arrival_end[2]) - int(arrival_start[2])

            parse_start = findEvent(event_list, "ParsingStart")
            parse_end = findEvent(event_list, "ParsingEnd")
            parse_time = int(parse_end[2]) - int(parse_start[2])

            load_start = findEvent(event_list, "LoadStart")
            load_end = findEvent(event_list, "LoadEnd")
            load_time = int(load_end[2]) - int(load_start[2])
            load_time = parse_time + load_time

            transfer_start = findEvent(event_list, "TransferStart")
            transfer_end = findEvent(event_list, "TransferEnd")
            transfer_time = int(transfer_end[2]) - int(transfer_start[2])

            engine_start = findEvent(event_list, "EngineStart")
            engine_end = findEvent(event_list, "EngineEnd")
            engine_time = int(engine_end[2]) - int(engine_start[2])

            departure_start = findEvent(event_list, "FutureReturn")
            departure_end = findEvent(event_list, "EndService")
            departure_time = int(departure_end[2]) - int(departure_start[2])

            total_time = int(departure_end[2]) - int(arrival_start[2])

            span_dict = {
                "Arrival": arrival_time,
                "Loading": load_time,
                "Transfer": transfer_time,
                "Engine": engine_time,
                "Departure": departure_time,
                "Others": total_time - arrival_time - load_time - transfer_time - engine_time - departure_time,
                "Total": total_time,
                }
            # span_list = [(p_event, n_event) for (p_event,n_event) in zip(event_list, event_list[1:])]
            # span_dict = {p_event[1]: int64(n_event[0])-int64(p_event[0]) for (p_event,n_event) in span_list}
            span_series = pd.Series(span_dict)
            series_list.append(span_series) 
        timestamp_frame = pd.DataFrame(series_list)
        # span_dict = {'clients': path_parser[2]}
        span_dict = {}
        for column in timestamp_frame.columns:
            column_frame = timestamp_frame[column]
            span_dict[f'{column}_mean'] = column_frame.mean()
            span_dict[f'{column}_med'] = column_frame.median()
            span_dict[f'{column}_q1'] = column_frame.quantile(options['quartiles'][0])
            span_dict[f'{column}_q3'] = column_frame.quantile(options['quartiles'][1])
            span_dict[f'{column}_whislo'] = column_frame.quantile(options['whiskers'][0])
            span_dict[f'{column}_whishi'] = column_frame.quantile(options['whiskers'][1])
            # print(column_frame[column_frame > column_frame.quantile(options['whiskers'][1])])
        print(span_dict)
        # create a summary to load instead of repeating preprocessing
        summary_file = open(summary_path, 'wb')
        pickle.dump(span_dict,summary_file) 
        return [span_dict]

class MorelloLatencyBreakdownLoader(PlotLoader):

    def load(self, df: pd.DataFrame, options: Dict, etl_info: Dict) -> None:

        if not df.empty:
            output_dir = self.get_output_dir(etl_info)
            self.table(df,output_dir)
            # self.save_plot(fig_unloaded, filename=f"latency_breakdown_{function}", output_dir=output_dir)

    def table(self, df, output_dir):
        targets = df['server'].unique()
        # drop hot request 
        # df = df[df['hotpercent'] == '0.0']
        # columns = [col_name for col_name in df.columns if )]
        # print(columns)
        server_grouped = df.groupby(['server','hotpercent'])
        for (server, server_frame) in server_grouped:
            # server_frame = server_frame[columns]
            server_frame =server_frame.T
            server_frame.to_csv(f"{output_dir}/{server[0]}_{server[1]}.csv", mode='w') 

class MorelloLoadLatencyPlotLoader(PlotLoader):

    percentiles: List[int]

    def load(self, df: pd.DataFrame, options: Dict, etl_info: Dict) -> None:
        if not df.empty:
            df=df[ df['total_failures'] / df['total_requests'] < 0.005]
            for percentile in options['percentiles']:
                figurename = f"matmul 1x1 load latency P{percentile}"
                plt.rcParams.update({'font.size': 22})
                fig = self.create_fig(df, options, percentile, figurename)
                output_dir = self.get_output_dir(etl_info)
                file_name = figurename.replace(' ', '_').replace(":","_")
                self.save_plot(fig, filename=file_name, output_dir=output_dir)

    def create_fig(self, df, options, percentile, figure_name):
        set_fonts()

        max_x = 11000
        max_y = 500

        fig,axis = plt.subplots(figsize=(13,7))
        x_col_name = 'rps'
        y_col_name = f'latency_p{percentile:3.1f}' 
        grouped = df.groupby('server')
        for (group_name, group) in grouped:
            group.sort_values(x_col_name, ignore_index=True, inplace=True)
            x_data = group[x_col_name]
            new_x_series = pd.Series(data={x_data.size: x_data.iat[x_data.size-1]+1})
            x_data = pd.concat([x_data, new_x_series])
            y_data = group[y_col_name]
            new_y_series = pd.Series(data={y_data.size: max_y*2})
            y_data = pd.concat([y_data, new_y_series])
            # append datapoint past the last one to give the ultimate knee
            # print(group_name)
            # print(x_data)
            # print(y_data)
            axis.plot(
                x_data,
                y_data,
                linestyle="dashed",
                label=LINE_DICT[group_name].name,
                marker=LINE_DICT[group_name].marker,
                color=LINE_DICT[group_name].color, 
                markersize=15,
            )
        axis.grid(True)
        # axis.set_title(figure_name)

        # use the first axis as for labels and handles, as they should be the same across all 
        handles,labels = axis.get_legend_handles_labels()
        axis.set_yscale('log')
        axis.set_xlim(left=0, right=max_x)
        axis.set_ylim(bottom=0.1, top=max_y)
        axis.set_xlabel('RPS')
        axis.set_ylabel(f'p{percentile} latency [ms]')
        fig.legend(handles, labels, loc="lower center", ncols=3, bbox_to_anchor=(0.55, 0.95))
        fig.tight_layout()
        return fig

class MatmulHotLoadLatencyPlotLoader(PlotLoader):

    percentiles: List[int]

    def load(self, df: pd.DataFrame, options: Dict, etl_info: Dict) -> None:
        if not df.empty:
            df = df[df['hotpercent'] == '1']
            df=df[ df['total_failures'] / df['total_requests'] < 0.005]
            figurename = f"matmul 128x128 load latency"
            plt.rcParams.update({'font.size': 22})
            fig = self.create_fig(df, options)
            output_dir = self.get_output_dir(etl_info)
            file_name = figurename.replace(' ', '_').replace(":","_")
            self.save_plot(fig, filename=file_name, output_dir=output_dir)

    def create_fig(self, df, options):
        set_fonts() 

        max_x = 8000
        max_y = 10

        fig,axis = plt.subplots(figsize=(12,5.5))
        x_col_name = 'rps'
        grouped = df.groupby('server')
        for (group_name, group) in grouped:
            group.sort_values(x_col_name, ignore_index=True, inplace=True)
            x_data = group[x_col_name]
            new_x_series = pd.Series(data={x_data.size: x_data.iat[x_data.size-1]+1})
            x_data = pd.concat([x_data, new_x_series])
            # y_data = pd.group['latency_p 50']
            # new_y_series = pd.Series(data={y_data.size: max_y*2})
            # y_data = pd.concat([y_data, new_y_series])
            y_data= pd.concat([group['latency_p 50'], pd.Series(data={group['latency_p 50'].size: max_y})])
            y_err_low= pd.concat([group['latency_p 50'] - group['latency_p  5'], pd.Series(data={group['latency_p  5'].size: 0})])
            y_err_high= pd.concat([group['latency_p 95'] - group['latency_p 50'], pd.Series(data={group['latency_p 95'].size: 0})])
            # append datapoint past the last one to give the ultimate knee
            axis.errorbar(
                        x_data,
                        y_data,
                        yerr=(y_err_low,y_err_high),
                        capsize=0,
                        capthick=0,
                        elinewidth=0.9,
                        label=LINE_DICT[group_name].name,
                        marker=LINE_DICT[group_name].marker,
                        color=LINE_DICT[group_name].color, 
                        barsabove=True,
                        markersize=15,
                        markevery=2,
                    )
        axis.grid(True)

        # use the first axis as for labels and handles, as they should be the same across all 
        handles,labels = axis.get_legend_handles_labels()
        # axis.set_yscale('log')
        axis.set_xlim(left=0, right=max_x)
        axis.set_ylim(bottom=0, top=max_y)
        axis.set_xlabel('RPS')
        axis.set_ylabel(f'latency [ms]')
        fig.legend(handles, labels)
        fig.tight_layout()
        return fig

class MatmulMixedLoadLatencyPlotLoader(PlotLoader):

    percentiles: List[int]

    def load(self, df: pd.DataFrame, options: Dict, etl_info: Dict) -> None:
        if not df.empty:
            cold_rate = '0.97' 
            size = "128"
            # df1=df[df['server'] == 'wasmtime']
            df=df[df['hotpercent'] == cold_rate]
            # df = pd.concat([df1,df2])
            df=df[(df['size'] == size)]
            df=df[ df['total_failures'] / df['total_requests'] < 0.005]
            figurename = f"matmul {size}x{size} with {int(float(cold_rate)*100)} hot requests load latency"
            # figurename = f"middleware with {int(float(cold_rate)*100)} hot requests load latency"
            # figurename = f"compression with {int(float(cold_rate)*100)} hot requests load latency"
            plt.rcParams.update({'font.size': 22})
            fig = self.create_fig(df, options)
            output_dir = self.get_output_dir(etl_info)
            file_name = figurename.replace(' ', '_').replace(":","_")
            self.save_plot(fig, filename=file_name, output_dir=output_dir)

    def create_fig(self, df, options):
        set_fonts() 
        max_x = 5000
        max_y = 100

        fig,axis = plt.subplots(figsize=(13,7))
        # use the first axis as for labels and handles, as they should be the same across all 
        # handles,labels = axis.get_legend_handles_labels()
        axis.set_yscale('log')
        axis.set_xlim(left=0, right=max_x)
        axis.set_ylim(bottom=1, top=max_y)
        axis.set_xlabel('RPS')
        axis.set_ylabel(f'latency [ms]')

        x_col_name = 'rps'
        grouped = df.groupby('server')
        for (group_name, group) in grouped:
            group.sort_values(x_col_name, ignore_index=True, inplace=True)
            x_data = group[x_col_name]
            new_x_series = pd.Series(data={x_data.size: x_data.iat[x_data.size-1]+1})
            x_data = pd.concat([x_data, new_x_series])
            # append datapoint past the last one to give the ultimate knee
            p50_col_name = f"latency_p{50:3.1f}"
            p5_col_name = f"latency_p{5:3.1f}"
            p95_col_name = f"latency_p{95:3.1f}"
            y_data= pd.concat([group[p50_col_name], pd.Series(data={group[p50_col_name].size: 2*max_y})])
            y_err_low= pd.concat([group[p50_col_name] - group[p5_col_name], pd.Series(data={group[p5_col_name].size: 0})])
            y_err_high= pd.concat([group[p95_col_name] - group[p50_col_name], pd.Series(data={group[p95_col_name].size: 0})])
            label = LINE_DICT[group_name].name
            if group_name == "firecracker" or group_name == "firecracker_snapshot":
                label += " (97% hot)"
            axis.errorbar(
                        x_data,
                        y_data,
                        yerr=(y_err_low,y_err_high),
                        capsize=0,
                        capthick=0,
                        elinewidth=0.9,
                        label=label,
                        marker=LINE_DICT[group_name].marker,
                        color=LINE_DICT[group_name].color, 
                        barsabove=True,
                        markersize=15,
                        markevery=3 ,
                    )
        axis.grid(True)

        handles,labels = axis.get_legend_handles_labels()

        fig.legend(handles, labels,  loc="lower center", ncols=2, bbox_to_anchor=(0.53, 0.92))
        fig.tight_layout()
        return fig


class IoScaleLoadLatencyPlotLoader(PlotLoader):

    percentiles: List[int]

    def load(self, df: pd.DataFrame, options: Dict, etl_info: Dict) -> None:
        if not df.empty:
            figurename = f"ioscale load latency"
            plt.rcParams.update({'font.size': 22})
            fig = self.create_fig(df, options)
            output_dir = self.get_output_dir(etl_info)
            file_name = figurename.replace(' ', '_').replace(":","_")
            self.save_plot(fig, filename=file_name, output_dir=output_dir)

    def create_fig(self, df, options):
        set_fonts()

        # axis matrix is accessed as axes[row][col]
        fig,axes = plt.subplots(figsize=(25,6), ncols=3, sharey=True)
        x_col_name = 'rps'
        y_col_name = f'latency_p 50' 
        # filter out failures
        df=df[ df['total_failures'] / df['total_requests'] < 0.005]
        # ignore wasm
        df=df[df['server'] != 'dandelion_wasm']
        # ignore 512KiB and 4MiB
        df=df[df['size'] != 524288]
        df=df[df['size'] != 4194304]
        iterations = 200_000_000
        df=df[df['iterations'] == iterations]

        letter_list = ['a','b','c']
        size_dict = {65536: '64KiB', 262144: '256KiB', 1048576: '1MiB'}
        max_y = 300
        io_grouped = df.groupby('size')
        for(column, (size, size_group)) in enumerate(io_grouped):
            grouped = size_group.groupby(['server', 'io_cores', 'hotpercent'])
            axis = axes[column]
            for (group_name, group) in grouped:
                if 'dandelion' in group_name[0] and group_name[1] != 1:
                    continue
                group.sort_values(x_col_name, ignore_index=True, inplace=True)

                x_data = group[x_col_name]
                new_x_series = pd.Series(data={x_data.size: x_data.iat[x_data.size-1]+1})
                x_data = pd.concat([x_data, new_x_series])
                # append datapoint past the last one to give the ultimate knee
                y_data= pd.concat([group['latency_p 50'], pd.Series(data={group['latency_p 50'].size: 2*max_y})])
                y_err_low= pd.concat([group['latency_p 50'] - group['latency_p  5'], pd.Series(data={group['latency_p  5'].size: 0})])
                y_err_high= pd.concat([group['latency_p 90'] - group['latency_p 50'], pd.Series(data={group['latency_p 90'].size: 0})])
                
                axis.errorbar(
                        x_data,
                        y_data,
                        yerr=(y_err_low,y_err_high),
                        capsize=0,
                        capthick=0,
                        elinewidth=0.9,
                        label=LINE_DICT[group_name[0]].name,
                        marker=LINE_DICT[group_name[0]].marker,
                        color=LINE_DICT[group_name[0]].color, 
                        barsabove=True,
                    )
            axis.grid(True)
            axis.set_title(f"{letter_list[column]}) size: {size_dict[size]}")

            # use the first axis as for labels and handles, as they should be the same across all 
            handles,labels = axis.get_legend_handles_labels()
            axis.set_xlim(left=0)
            axis.set_ylim(bottom=0, top=max_y)
            axis.set_xlabel('RPS')
            axis.set_ylabel(f'latency [ms]')
        fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0), ncols=3)
        fig.tight_layout()
        return fig

class ChainScaleLatencyPlotLoader(PlotLoader):

    def load(self, df: pd.DataFrame, options: Dict, etl_info: Dict) -> None:
        if not df.empty:
            figurename = f"unloaded latency for varying chain length"
            plt.rcParams.update({'font.size': 22})
            fig = self.create_fig(df, options)
            output_dir = self.get_output_dir(etl_info)
            file_name = figurename.replace(' ', '_').replace(":","_")
            self.save_plot(fig, filename=file_name, output_dir=output_dir)

    def create_fig(self, df, options):
        set_fonts()

        # axis matrix is accessed as axes[row][col]
        fig,axis = plt.subplots(figsize=(13,7))
        df=df[ df['total_failures'] / df['total_requests'] < 0.005]
        df=df[df['server'] != 'dandelion_wasm']

        # have data for sizes: 65536, 262144, 1048576 and iterations: 2_000_000 and 200_000_000
        # results for 2M iterations and 64KiB Bytes
        # df = df[(df['io_cores'] == 2) | (df['io_cores'] == 0)]
        df = df[df['size'] == 65536]
        df = df[df['iterations'] == 10_000]

        x_col_name = 'chain_layers'
        # use the first axis as for labels and handles, as they should be the same across all 
        axis.grid(True)
        # axis.set_xscale('log')
        # axis.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
        # axis.get_xaxis().set_tick_params(which='minor', size=0)
        # axis.get_xaxis().set_tick_params(which='minor', width=0)
        axis.set_xticks([2,4,8,16], labels=[2,4,8,16])
        axis.set_xlim(left=0, right=17)
        axis.set_ylim(bottom=0, top=70)
        axis.set_xlabel('Number of data fetch/process/send iteration')
        axis.set_ylabel(f'unloaded latency [ms]')

        grouped = df.groupby(['server', 'hotpercent'])
        for (group_name, group) in grouped:
            print(group_name)
            if group_name[0] == 'dedicated' and group_name[1] == '0.0':
                continue
            group.sort_values(x_col_name, ignore_index=True, inplace=True)
            if(group_name[1] == '0.0'):
                line_dict = COLD_LINE_DICT
            else:
                line_dict = LINE_DICT
            x_data = group[x_col_name]
            # append datapoint past the last one to give the ultimate knee
            y_data= group['latency_p 50']
            y_err_low= group['latency_p 50'] - group['latency_p  5']
            y_err_high= group['latency_p 95'] - group['latency_p 50']
            if group_name[0] == 'dedicated':
                label = f"{line_dict[group_name[0]].name}"
            elif group_name[1] == '1.0' and group_name[0] == 'firecracker':
                label = f"{line_dict[group_name[0]].name} hot"
            elif group_name[1] == '0.0' and group_name[0] == 'firecracker_snapshot':
                label = f"{line_dict[group_name[0]].name} cold"
            elif group_name[1] == '1.0' and (group_name[0] == 'dandelion_process' or group_name[0] == 'dandelion_kvm'):
                label = f"{line_dict[group_name[0]].name} cached"
            elif group_name[1] == '0.0' and (group_name[0] == 'dandelion_process' or group_name[0] == 'dandelion_kvm'):
                label = f"{line_dict[group_name[0]].name} uncached"
            elif group_name[1] == '1.0' and group_name[0] == 'wasmtime':
                label = f"{line_dict[group_name[0]].name}"
            elif group_name[1] == '1.0' and group_name[0] == 'wasmtime_ondemand':
                label = f"{line_dict[group_name[0]].name}"
            else:
                print(f"could not find label for {group_name}")
            # if group_name[0] == "firecracker_snapshot" or group_name[0] == "firecracker":
            #     print(x_data)
            #     print(y_data)
            axis.errorbar(
                x_data,
                y_data,
                elinewidth=0.9,
                yerr=(y_err_low, y_err_high),
                label=label,
                marker=line_dict[group_name[0]].marker,
                color=line_dict[group_name[0]].color,
            )
    
        handles,labels = axis.get_legend_handles_labels()
        # axis.set_yscale('log')
        # fig.legend(handles, labels, loc="lower center", ncols=3, bbox_to_anchor=(0.5, 1.05))
        fig.legend(handles, labels, loc="lower center", ncols=2, bbox_to_anchor=(0.53, 0.95))
        # fig.legend(handles, labels, loc="center left", bbox_to_anchor=(0.95, 0.55))
        fig.tight_layout()
        return fig

class MixedWorkloadExtractor(Extractor):

    def default_file_regex():
        return [r"latencies.*\.csv$"]

    def extract(self, path: str, options: Dict) -> List[Dict]:
        summary_path = PurePath(path).with_suffix('.pkl')
        try:
            log_summary_file = open(summary_path, 'rb')
            return pickle.load(summary_file)
        except: 
            pass 
        latency_log = open(path)
        path_parser = re.fullmatch(r".*latencies_.(.*)_open-loop_(.*)_.*_.*hot_1_rate\.csv", path)
        if not path_parser:
            print(f"Skipping invalid file name: {path}")
            return []
        process_type = path_parser[1]
        function_name = path_parser[2]
        df = pd.read_csv(path)
        df = df.sort_values(by="startTime")
        # normalize start time
        min_start_time = df["startTime"][0]
        df["startTime"] = df["startTime"] - min_start_time
        df = df[1:-1]
        
        start_second = (df["startTime"] / 1e6).astype("int")
        # for every entry create a dics with start time, response time, status and failure 
        dict_list = []
        for index, row in df.iterrows():
            row_dict = {"function": function_name,  
                        "startTime": row[1],
                        "responseTime": row[2],
                        "failure": row[3] or row[4],
                        "statusCode": row[5]}
            dict_list.append(row_dict)
        # memoize to avoid recompuatation
        summary_file = open(summary_path, 'wb')
        pickle.dump(dict_list,summary_file)
        return dict_list

APP_DICT = {
    "compression-app": ("blue", "img compression"),
    "middleware-app": ("orange", "log processing")
}

class MixedWorkloadLoader(PlotLoader):

    def load(self, df: pd.DataFrame, options: Dict, etl_info: Dict) -> None:
        # if not df.empty:
            figurename = f'mixed_load_timeplot'
            # drop firecracker data
            df = df[df['server'] != 'firecracker']

            fig = self.create_fig(df, options)
            output_dir = self.get_output_dir(etl_info)
            self.save_plot(fig, filename=figurename, output_dir=output_dir)

    def create_fig(self, df, options):
        set_fonts()
        fig, axes = plt.subplots(4, figsize=(15, 18), sharex=True, gridspec_kw={'hspace':0.05})

        title_hight = 0.82

        # loader rps
        load_df = df[df['server'] == 'wasmtime']
        load_group = load_df.groupby('function')
        for load_name, load in load_group:
            # Filter out first second of data
            load = load[load['startTime'] >= 1_000_000]
            start_second = (load["startTime"] / 1e6).astype("int") 
            requests_per_second = start_second.groupby(start_second).size() 
            
            axes[0].plot(
                requests_per_second,
                color=APP_DICT[load_name][0],
                linewidth=4,
                label=APP_DICT[load_name][1]
                )
        axes[0].set_ylim(bottom=0, top=600)
        axes[0].set_title(f"Load Pattern", y=0.85)
        axes[0].set_yticks([0, 250, 500])
        axes[0].set_ylabel("RPS")
        axes[0].legend(loc="upper right", bbox_to_anchor=(1, 0.95), framealpha=0)

        server_function_grouped = df.groupby(['server', 'function'])
        for index,(server_function_name, server_function_group) in enumerate(server_function_grouped):
            axis_index = int(index / 2 + 1)
            axis = axes[axis_index]
            server = server_function_name[0]
            function = server_function_name[1]
            # Filter out first second of data
            server_function_group = server_function_group[server_function_group['startTime'] >= 1_000_000]
            # usec until we classify a request as failure
            server_function_group = server_function_group[server_function_group["failure"] == False]
            print(server_function_name) 
            average = (server_function_group['responseTime']/1e3).mean()
            variance =(server_function_group['responseTime']/1e3).var()
            print(f"average {average}, variance {variance}, percentage {100*variance/average}")
            failure_threshold = 65000
            success_data = server_function_group[server_function_group["responseTime"] < failure_threshold]
            failure_data = server_function_group[server_function_group["responseTime"] >= failure_threshold]
            success_data_x = success_data["startTime"] / 1e6
            success_data_y = success_data["responseTime"] / 1e3
            failure_data_x = failure_data["startTime"] / 1e6
            failure_data_y = failure_data["responseTime"].clip(upper=failure_threshold) / 1e3
            axis.scatter(
                success_data_x,
                success_data_y, 
                color=APP_DICT[function][0], 
            )
            axis.scatter(
                failure_data_x,
                failure_data_y, 
                color="red", 
            )
            axis.set_title(f"{LINE_DICT[server].name}", y=title_hight)
            axis.set_ylabel('latency [ms]')
            axis.set_ylim(bottom=0, top=70)


        # axis.grid(True)
        # axis.set_xscale('log')
        # axis.set_yscale('close_to_one')
        # axis.set_ylim((0, 0.999))

        axes[3].set_xlabel('time [s]')
        # axis.set_ylabel('CDF')
    
        # handles,labels = axis.get_legend_handles_labels()
        # fig.legend(handles, labels, loc="upper left", bbox_to_anchor=(0.96, 0.9))
        fig.tight_layout(rect=[0, 0, 0.98, 0.95])
        return fig