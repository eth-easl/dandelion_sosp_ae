import socket

from jinja2.runtime import Undefined


def get_ip_for_hosttype(hostlist, host_type):
    # if hostlist is defined
    # return the ipv4 for the host name
    if isinstance(hostlist, Undefined):
        print("get_ip_for_hostname: hostlist not defined or host_type not unique")
        return "0.0.0.0"
    host = [host for host in hostlist if host['host_type'] == host_type]
    if len(host) == 1:
        # check if it has a custom IP defined
        if 'private_dns_name' in host[0]:
            return socket.gethostbyname(host[0]['private_dns_name'])
        return socket.gethostbyname(host[0]['public_dns_name'])
    # if hostlistnot defined or hostname not unique return default value


def get_workloadpath_for_target(hostlist, target, requestformat):
    host = [host for host in hostlist if host['host_type'] == 'worker']
    arch = host[0]['hostvars']['ansible_architecture']

    if target == "hyperlight" and requestformat != "matmul":
        print(f"hyperlight workload not supported for requestformat: {requestformat}")
        return "."

    suffix = ""
    if requestformat == "matmul" or requestformat == "matmul-storage":
        suffix += "matmul"
    elif requestformat == "io-scale" or requestformat == "compute" or requestformat == "chain-scaling" or requestformat == "chain-scaling-dedicated":
        suffix += "busy"
    elif requestformat == "middleware-app":
        if "dandelion-process" in target:
            return "/machine_interface/tests/data/middleware_app"
        else:
            print(f"middleware-app not supported for target: {target}")
    elif requestformat == "middleware-app-hybrid":
        if "dandelion-process" in target:
            return "/machine_interface/tests/data/middleware_app_hybrid_mmu_x86_64"
        else:
            print(f"middleware-app not supported for target: {target}")
    elif requestformat == "compression-app":
        suffix += "compression"

    if "dandelion-process" in target:
        return f"/machine_interface/tests/data/test_elf_mmu_{arch}_" + suffix
    elif "dandelion-kvm" in target:
        return f"/machine_interface/tests/data/test_elf_kvm_{arch}_" + suffix
    elif "dandelion-rwasm" in target:
        return f"/machine_interface/tests/data/test_sysld_wasm_{arch}_" + suffix
    elif "dandelion-cheri" in target:
        return "/machine_interface/tests/data/test_elf_cheri_" + suffix
    else:
        return "."


class FilterModule(object):
    '''jinja2 filters'''

    def filters(self):
        return {
            'get_ip_for_hosttype': get_ip_for_hosttype,
            'get_workloadpath_for_target': get_workloadpath_for_target,
        }
