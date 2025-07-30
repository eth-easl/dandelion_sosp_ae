def get_group_name(line_tuple, line_list):
    if not isinstance(line_tuple, list):
        if isinstance(line_tuple, tuple):
            line_tuple = list(line_tuple)
        elif isinstance(line_tuple, str) or isinstance(line_tuple, int):
            line_tuple = [line_tuple]
        else:
            raise ValueError(f"do not know how to convert to list {list}")
    name_string = ""
    for (name,value) in zip(line_list, line_tuple):
        name_string = name_string + f"{name}:{value} "
    return name_string

def get_groupby_len(df, list):
    list_len = len(list)
    if list_len == 0:
        return 1
    elif list_len == 1:
        return len(df[list[0]].unique())
    else:
        total = 1
        for item in list:
            total = total * len(df[item].unique())
        return total