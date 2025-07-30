from doespy.etl.steps.extractors import Extractor
from doespy.etl.steps.transformers import Transformer
from doespy.etl.steps.loaders import Loader, PlotLoader

import pandas as pd
from typing import Dict, List, Tuple
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import itertools 
import re 
from numpy import int64,ndarray
from pathlib import PurePath 
import pickle
from .helpers import *
import math


class MyExtractor(Extractor):
    def default_file_regex():
        return [r".*\.txt$", r".*\.log$"]

    def extract(self, path: str, options: Dict) -> List[Dict]:
        print("MyExtractor: do nothing")
        return [{}]

class TimestampExtractor(Extractor):

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
        for timestamp_line in timestamp_file:
            event_list = re.findall("parent:([0-9]+), span:([0-9]+), time:([0-9]+), point:(\w+)", timestamp_line)
            event_list = [ (event[2], f"T{index:02}_{event[3]}") for index,event in enumerate(event_list) ]
            span_list = [(p_event, n_event) for (p_event,n_event) in zip(event_list, event_list[1:])]
            span_dict = {p_event[1]: int64(n_event[0])-int64(p_event[0]) for (p_event,n_event) in span_list}
            span_series = pd.Series(span_dict)
            series_list.append(span_series)
            # TODO: validate all spans have the same form 
            # span_dict_list.append(span_dict)
            # if re.search(".*dedicated.*", path) is not None:
            #     print(span_dict) 
        timestamp_frame = pd.DataFrame(series_list)
        span_dict = {'clients': path_parser[2]}
        for column in timestamp_frame.columns:
            column_frame = timestamp_frame[column]
            span_dict[f'{column}_mean'] = column_frame.mean()
            span_dict[f'{column}_med'] = column_frame.median()
            span_dict[f'{column}_q1'] = column_frame.quantile(options['quartiles'][0])
            span_dict[f'{column}_q3'] = column_frame.quantile(options['quartiles'][1])
            span_dict[f'{column}_whislo'] = column_frame.quantile(options['whiskers'][0])
            span_dict[f'{column}_whishi'] = column_frame.quantile(options['whiskers'][1])
            # print(column_frame[column_frame > column_frame.quantile(options['whiskers'][1])])
        # create a summary to load instead of repeating preprocessing
        summary_file = open(summary_path, 'wb')
        pickle.dump(span_dict,summary_file) 
        return [span_dict]

class LatencyExtractor(Extractor):
    
    def default_file_regex():
        return [r"latencies.*\.csv$"]

    def extract(self, path: str, options: Dict) -> List[Dict]:
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
        time_start_us = None
        for index, latency_line in enumerate(latency_log.readlines()[1:]):
            current_latency = re.fullmatch("http://[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}:8080/(\w+)/(\w+),([0-9]+),([0-9]+),(\w+),(\w+),([0-9]{1,3})\n", latency_line)
            if current_latency is not None:
                # skip first 10 seconds
                seconds_skipped = 10
                time_current_us = int(current_latency[3])
                if time_start_us == None:
                    time_start_us = time_current_us
                if (time_current_us - time_start_us) / 1e6 < seconds_skipped:
                    continue
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
        percentiles = [5, 50, 90, 95, 99, 100]
        if 'percentiles' in options.keys():
            percentiles = options['percentiles'] 
        for percentile in percentiles:
            span_dict[f"latency_p{percentile:3.1f}"] = end2end_series.quantile(percentile/100)
        log_summary_file = open(log_summary_path, 'wb')
        pickle.dump([span_dict],log_summary_file) 
        return [span_dict] 

class MyTransformer(Transformer):
    def transform(self, df: pd.DataFrame, options: Dict) -> pd.DataFrame:
        print(f"MyTransformer: do nothing  ({df.info()})")
        return df


class MyLoader(Loader):
    def load(self, df: pd.DataFrame, options: Dict, etl_info: Dict) -> None:
        print(f"MyLoader: do nothing  ({df.info()})")
        # Any result should be stored in:
        # output_dir = self.get_output_dir(etl_info)


class MyPlotLoader(PlotLoader):
    def load(self, df: pd.DataFrame, options: Dict, etl_info: Dict) -> None:
        print(f"MyPlotLoader: do nothing  ({df.info()})")
        if not df.empty:
            fig = self.plot(df)
            output_dir = self.get_output_dir(etl_info)
            self.save_plot(fig, filename="test", output_dir=output_dir)

    def plot(self, df):
        fig = plt.figure()
        return fig
    
class TimestampPlotLoader(PlotLoader):

    def load(self, df: pd.DataFrame, options: Dict, etl_info: Dict) -> None:

        if not df.empty:
            functions = df['function'].unique()
            for function in functions:
                output_dir = self.get_output_dir(etl_info)
                fig_unloaded = self.plot(df[df['function'] == function], False)
                self.save_plot(fig_unloaded, filename=f"latency_breakdown_{function}", output_dir=output_dir)

    def plot(self, df, peak):
        sizes = df['size'].unique()
        targets = df['server'].unique()
        targets = targets[1:]
        print(f"{targets}")
        plot_rows=len(sizes)
        plot_cols=len(targets)
        fig,axes = plt.subplots(nrows=plot_rows, ncols=plot_cols, sharey=True, sharex=True, figsize=(16,16))
        # for (size_index,size) in enumerate(sizes):
        #     for (target_index,target) in enumerate(targets):
        #         row_index = size_index 
        #         col_index = target_index
        #         subframe = df[df['size'] == size]
        #         subframe = subframe[subframe['server'] == target]
        #         box_items = ['mean', 'med', 'q1', 'q3', 'whislo', 'whishi'] 
        #         if peak:
        #             clients = subframe['clients'].max()
        #         else: 
        #             clients = subframe['clients'].min()
        #         client_frame = subframe[subframe['clients'] == clients]
        #         stats = []
        #         for label in col_list:
        #             items = {item: client_frame[f'{label}_{item}'] for item in box_items}  
        #             items['label'] = label
        #             items['fliers'] = []
        #             stats.append(items)
        #         axes[row_index,col_index].bxp(stats)
        #         axes[row_index,col_index].tick_params(axis='x', labelrotation=90)
        #         axes[row_index,col_index].set_ylabel('us')
        #         axes[row_index,col_index].set_yscale('log')
        #         # axes[row_index,col_index].set_yticks(])
        #         axes[row_index,col_index].set_title(f"{target} size:{size}")
        # for (target_index,target) in enumerate(targets):
            # col_index = target_index
        target = 'dandelion_process_timestamp'
        subframe = df[df['server'] == target]
        box_items = ['mean', 'med', 'q1', 'q3', 'whislo', 'whishi'] 
        if peak:
            clients = subframe['clients'].max()
        else: 
            clients = subframe['clients'].min()
        client_frame = subframe[subframe['clients'] == clients]
        stats = []
        print(subframe.columns)
        col_list = set()
        for col_name in subframe.columns:
            col_match = re.match("^(T\d+_.*)_.*", col_name)
            if col_match:
                col_list.add(col_match[1])
        # col_list = [col_name for col_name in subframe.columns if re.match("^T\d+", col_name)]
        col_list = list(col_list)
        col_list.sort()
        print(col_list)
        for label in col_list:
            items = {item: client_frame[f'{label}_{item}'] for item in box_items}  
            items['label'] = label
            items['fliers'] = []
            stats.append(items)
        axes.bxp(stats)
        axes.tick_params(axis='x', labelrotation=90)
        axes.set_ylabel('us')
        axes.set_yscale('log')
        # axes[row_index,col_index].set_yticks(])
        axes.set_title(f"{target}")

        fig.tight_layout() 
        return fig 

class LoadLatencyPlotLoader(PlotLoader):

    percentiles: List[int]

    figure_group_bys: List[str] = ['function']

    horizontal_group_bys: List[str] = []

    vertical_group_bys: List[str] = []

    line_group_bys: List[str] = ['server']

    def load(self, df: pd.DataFrame, options: Dict, etl_info: Dict) -> None:
        if not df.empty:
            # group for different plots
            fig_group_list = options['figure_group_bys']
            if len(fig_group_list) == 1:
                fig_group_list = fig_group_list[0]
            fig_groups = df.groupby(fig_group_list)
            for (fig_names, fig_frame) in fig_groups:
                if isinstance(fig_names, tuple):
                    fig_name_list = list(fig_names)
                else:
                    fig_name_list = [fig_names]
                for percentile in options['percentiles']:
                    fig_name = get_group_name(fig_names, fig_group_list)
                    figurename = f"load latency {fig_name.replace('_', ' ')}p{percentile}"
                    plt.rcParams.update({'font.size': 22})
                    fig = create_fig(fig_frame, options, percentile)
                    fig.suptitle(figurename, y=1.04) 
                    output_dir = self.get_output_dir(etl_info)
                    file_name = figurename.replace(' ', '_').replace(":","_")
                    self.save_plot(fig, filename=file_name, output_dir=output_dir)

def create_fig(df, options, percentile):
    # decide on grid size
    horizontal_groups = get_groupby_len(df, options['horizontal_group_bys'])
    vertical_groups = get_groupby_len(df, options['vertical_group_bys'])
    # fig,axes = plt.subplots(nrows=horizontal_groups, ncols=vertical_groups, figsize=(20,20), sharex=True, sharey=True)
    fig,axes = plt.subplots(nrows=horizontal_groups, ncols=vertical_groups, figsize=(20,20))
    options['horizontal_groups'] = horizontal_groups
    options['vertical_groups'] = vertical_groups
    x_col_name = 'rps'
    y_col_name = f'latency_p{percentile:3.1f}' 
    max_x = df[x_col_name].max() * 1.05
    max_y = df[y_col_name].max() * 1.05
    add_horizontal_figures(axes, df, options, x_col_name, y_col_name) 
    # check if array, is so check if nested
    if isinstance(axes,ndarray):
        # for two dimensional scaling
        if len(axes) > 0 and isinstance(axes[0], ndarray):
            axis_list = [inner_axis for outer_list in axes for inner_axis in outer_list]
        # for one dimensional scaling
        else: 
            axis_list = axes 
    # for single figure
    else:
        axis_list = [axes]
    # use the first axis as for labels and handles, as they should be the same across all 
    handles,labels = axis_list[0].get_legend_handles_labels()
    for axis in axis_list:
        # axis.set_yscale('log')
        # axis.set_ylim(top=max_y)
        axis.set_ylim(bottom=0)
        axis.set_ylabel(f'p{percentile} latency [ms]')
        axis.set_xlabel('rps')
        # axis.set_xlim(left=0,right=max_x)
        axis.set_xlim(left=0)
    fig.legend(handles, labels, loc="center left", bbox_to_anchor=(1.04,0.5))
    fig.tight_layout()
    return fig
    
def add_horizontal_figures(axes, df, options, x_col_name, y_col_name):   
    horizontal_group_list = options['horizontal_group_bys']
    if options['horizontal_groups'] < 2:
        return add_vertical_figures(axes, df, options, x_col_name, y_col_name, "")
    if len(horizontal_group_list) == 1:
        horizontal_group_bys = horizontal_group_list[0]
    else:
        horizontal_group_bys = horizontal_group_list
    grouped = df.groupby(horizontal_group_bys) 
    max_x_val = df[x_col_name].max()*1.05
    # round max value up to next log scale tick
    max_y_val = 10**(int(math.log10(df[y_col_name].max())) + 1)
    for (index,(group_name, group)) in enumerate(grouped):
        axis = axes[index]
        title_prefix = get_group_name(horizontal_group_list, group_name)
        add_vertical_figures(axis, group, options, x_col_name, y_col_name, title_prefix)

def add_vertical_figures(axes, df, options, x_col_name, y_col_name, title):
    vertical_group_list = options['vertical_group_bys']
    if options['vertical_groups'] < 2:
        add_lines(axes, df, options, x_col_name, y_col_name, title)
        return
    elif len(vertical_group_list) == 1:
        vertical_groups = vertical_group_list[0]
    else:
        vertical_groups = vertical_group_list
    grouped = df.groupby(vertical_groups) 
    for (index, (group_name, group)) in enumerate(grouped):
        axis = axes[index]
        subtitle = get_group_name(group_name, vertical_group_list)
        subgraph_title = f"{title} {get_group_name(group_name, vertical_group_list)}"
        add_lines(axis, group, options, x_col_name, y_col_name, subgraph_title)


def add_lines(axis, df, options, x_col_name, y_col_name, title):
    line_group_list = options['line_group_bys']
    if len(line_group_list) == 1:
        line_group_bys = line_group_list[0]
    else:
        line_group_bys = line_group_list
    marker_cycle = itertools.cycle(Line2D.markers.keys())
    grouped = df.groupby(line_group_bys)
    for (group_name, group) in grouped:
        group.sort_values(x_col_name, ignore_index=True, inplace=True)
        # axis.errorbar(target_frame['rps'], target_frame['latency_p50'], yerr=(target_frame['latency_p5'], target_frame['latency_p95']), label=target)
        axis.plot(
            group[x_col_name],
            group[y_col_name],
            label=get_group_name(group_name,line_group_list),
            linestyle="dashed",
            marker=next(marker_cycle),
        )
        axis.grid(True)
        axis.set_title(title)