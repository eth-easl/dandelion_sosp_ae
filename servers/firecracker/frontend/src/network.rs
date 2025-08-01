use log::debug;

use crate::util::{sudo, sudo_unchecked};

pub fn get_vm_ip(id: u32) -> String {
    return format!(
        "169.254.{}.{}",
        ((id * 4 + 2) / 256) % 256,
        (id * 4 + 2) % 256
    );
}

pub fn get_tap_ip(id: u32) -> String {
    return format!(
        "169.254.{}.{}",
        ((id * 4 + 1) / 256) % 256,
        (id * 4 + 1) % 256
    );
}

pub fn get_tap_mac(id: u32) -> String {
    return format!("02:FC:00:00:{:02X}:{:02X}", ((id / 256) % 256), id % 256);
}

pub fn get_tap_dev(id: u32) -> String {
    return format!("fc-{}-tap0", id);
}

pub async fn setup_vm_network(host_dev: &str, dev: &str, ip: &str) {
    teardown_vm_network(host_dev, dev).await;
    debug!("setup vm network");
    sudo(["ip", "tuntap", "add", "dev", &dev, "mode", "tap"]).await;
    // sudo(["sysctl", &format!("-w net.ipv4.conf.{}.proxy_arp=1", dev)]).await;
    // sudo([
    //     "sysctl",
    //     &format!("-w net.ipv6.conf.{}.disable_ipv6=1", dev),
    // ])
    // .await;
    sudo(["ip", "addr", "add", &format!("{}/30", ip), "dev", &dev]).await;
    sudo(["ip", "link", "set", "dev", &dev, "up"]).await;
    sudo([
        "iptables",
        "--wait",
        "--append",
        "FORWARD",
        "--in-interface",
        &dev,
        "--out-interface",
        host_dev,
        "--jump",
        "ACCEPT",
    ])
    .await;
}

pub async fn teardown_vm_network(host_dev: &str, dev: &str) {
    debug!("teardown vm network");
    sudo_unchecked(["ip", "link", "del", dev]).await;
    sudo_unchecked([
        "iptables",
        "--wait",
        "--delete",
        "FORWARD",
        "--in-interface",
        &dev,
        "--out-interface",
        &host_dev,
        "--jump",
        "ACCEPT",
    ])
    .await;
}

pub async fn setup_server_network(host_dev: &str) {
    teardown_server_network(host_dev).await;
    debug!("setup server network");
    sudo(["sysctl", "-w", "net.ipv4.ip_forward=1"]).await;
    sudo([
        "iptables",
        "--wait",
        "--table",
        "nat",
        "--append",
        "POSTROUTING",
        "--out-interface",
        &host_dev,
        "--jump",
        "MASQUERADE",
    ])
    .await;
    sudo([
        "iptables",
        "--wait",
        "--append",
        "FORWARD",
        "--match",
        "conntrack",
        "--ctstate",
        "RELATED,ESTABLISHED",
        "--jump",
        "ACCEPT",
    ])
    .await;
}

pub async fn teardown_server_network(host_dev: &str) {
    debug!("teardown server network");
    sudo_unchecked(["sysctl", "-w", "net.ipv4.ip_forward=0"]).await;
    sudo_unchecked([
        "iptables",
        "--wait",
        "--table",
        "nat",
        "--delete",
        "POSTROUTING",
        "--out-interface",
        &host_dev,
        "--jump",
        "MASQUERADE",
    ])
    .await;
    sudo_unchecked([
        "iptables",
        "--wait",
        "--delete",
        "FORWARD",
        "--match",
        "conntrack",
        "--ctstate",
        "RELATED,ESTABLISHED",
        "--jump",
        "ACCEPT",
    ])
    .await;
}
