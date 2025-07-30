use lazy_static::lazy_static;
use log::{info, warn};
use rustcracker::{
    components::{
        command_builder::VMMCommandBuilder,
        machine::{Config, Machine, MachineError},
    },
    model::{
        drive::Drive, machine_configuration::MachineConfiguration,
        network_interface::NetworkInterface, snapshot_load_params::SnapshotLoadParams,
    },
    utils::StdioTypes,
};
use std::{path::PathBuf, process::Stdio, time::Duration};
use tokio::sync::Semaphore;

use crate::{
    http_relay,
    network::{
        get_tap_dev, get_tap_ip, get_tap_mac, get_vm_ip, setup_vm_network, teardown_vm_network,
    },
    test_ready, Work, ARGS,
};

const RUN_DIR: &'static str = "/tmp/firecracker/run";
const SNAPSHOT_DIR: &'static str = "/tmp/firecracker/snapshot";

lazy_static! {
    static ref PERMITS: Semaphore = {
        let concurrency = num_cpus::get().div_ceil(2);
        assert!(concurrency >= 1);
        Semaphore::new(concurrency)
    };
}

struct VirtualMachineInfo {
    vmid: String,
    socket_path: PathBuf,
    // log_path: PathBuf,
    ip: String,
    tap_ip: String,
    tap_dev: String,
    tap_mac: String,
}

impl VirtualMachineInfo {
    fn new(id: u32) -> Self {
        let vmid = format!("VM{}", id);
        let run_dir = PathBuf::from(RUN_DIR).join(&vmid);
        std::fs::create_dir_all(&run_dir).unwrap();
        let socket_path = run_dir.join("firecracker.socket");
        // let log_path = run_dir.join("firecracker.log");

        return Self {
            vmid,
            socket_path,
            // log_path,
            ip: get_vm_ip(id),
            tap_ip: get_tap_ip(id),
            tap_dev: get_tap_dev(id),
            tap_mac: get_tap_mac(id),
        };
    }

    fn vmm_config(&self, kernel_path: &PathBuf, rootfs_path: &PathBuf) -> Config {
        let kernel_args = if ARGS.attach_vm {
            "reboot=k panic=1 pci=off nomodule tsc=reliable quiet i8042.noaux ipv6.disable=1 console=ttyS0 random.trust_cpu=on"
        } else {
            "reboot=k panic=1 pci=off nomodule 8250.nr_uarts=0 i8042.noaux i8042.nomux i8042.nopnp i8042.dumbkbd quiet loglevel=1"
        };
        let kernel_args = format!(
            "{} ip={}::{}:255.255.255.252::eth0:off",
            kernel_args, self.ip, self.tap_ip
        );

        return Config {
            socket_path: Some(self.socket_path.clone()),
            // log_path: Some(self.log_path.clone()),
            // log_level: Some(LogLevel::Info),
            kernel_image_path: Some(kernel_path.clone()),
            kernel_args: Some(kernel_args),
            drives: Some(vec![Drive {
                drive_id: "root".to_string(),
                is_root_device: true,
                is_read_only: false,
                path_on_host: rootfs_path.clone(),
                ..Drive::new()
            }]),
            network_interfaces: Some(vec![NetworkInterface {
                guest_mac: Some(self.tap_mac.clone()),
                host_dev_name: self.tap_dev.clone().into(),
                iface_id: "1".to_string(),
                ..Default::default()
            }]),
            machine_cfg: Some(MachineConfiguration {
                mem_size_mib: 128,
                vcpu_count: 1,
                ..Default::default()
            }),
            vmid: Some(self.vmid.clone()),
            // we don't need to setup network namespace, but the library will complain on its absense...
            net_ns: Some(PathBuf::from("")),
            stdin: Some(StdioTypes::Inherit),
            stdout: Some(StdioTypes::Inherit),
            stderr: Some(StdioTypes::Inherit),
            ..Default::default()
        };
    }

    fn new_machine(&self) -> Machine {
        let stdio = if ARGS.attach_vm {
            Stdio::inherit
        } else {
            Stdio::null
        };
        let cmd = VMMCommandBuilder::new()
            .with_bin(&ARGS.firecracker_path)
            .with_socket_path(&self.socket_path)
            .with_stdin(stdio())
            .with_stdout(stdio())
            .with_stderr(stdio())
            .build();

        let config = self.vmm_config(&ARGS.kernel_path, &ARGS.rootfs_path);
        let mut machine = Machine::new(config).unwrap();
        machine.set_command(cmd.into());

        return machine;
    }
}

struct SnapshotInfo {
    mem_file_path: PathBuf,
    snapshot_path: PathBuf,
}

impl SnapshotInfo {
    fn new(vmid: &str) -> Self {
        let snapshot_dir = PathBuf::from(SNAPSHOT_DIR).join(vmid);
        std::fs::create_dir_all(&snapshot_dir).unwrap();
        let mem_file_path = snapshot_dir.join("memfile");
        let snapshot_path = snapshot_dir.join("snapfile");
        return Self {
            mem_file_path,
            snapshot_path,
        };
    }
}

enum WorkerType {
    Hot(Machine),
    ColdSnapshot(SnapshotInfo),
    Cold,
}

pub struct VirtualMachineWorker {
    vminfo: VirtualMachineInfo,
    wktype: WorkerType,
    client: reqwest::Client,
}

impl VirtualMachineWorker {
    pub async fn create(id: u32, is_hot: bool) -> Result<Self, MachineError> {
        // limit the number of concurrency to reduce some unclear failures in vm.start()
        let _permit = PERMITS.acquire().await.unwrap();

        let vminfo = VirtualMachineInfo::new(id);
        if vminfo.socket_path.exists() {
            warn!("socket {:?} already exists, deleting", &vminfo.socket_path);
            std::fs::remove_file(&vminfo.socket_path).unwrap();
        }

        setup_vm_network(&vminfo.tap_dev, &vminfo.tap_ip).await;

        let client = reqwest::ClientBuilder::new()
            .no_proxy()
            // have to reset the connection for new (cold) VMs
            .pool_max_idle_per_host(if is_hot { usize::MAX } else { 0 })
            .build()
            .unwrap();

        let wktype = if is_hot {
            let mut vm = vminfo.new_machine();
            vm.start().await?;
            test_ready(&vminfo.ip, &vminfo.vmid, client.clone()).await;
            WorkerType::Hot(vm)
        } else if ARGS.use_snapshots {
            let si = SnapshotInfo::new(&vminfo.vmid);
            let mut vm = vminfo.new_machine();
            vm.start().await?;
            test_ready(&vminfo.ip, &vminfo.vmid, client.clone()).await;
            // wait for the connection termination
            tokio::time::sleep(Duration::from_millis(10)).await;
            vm.pause().await?;
            vm.create_snapshot(&si.mem_file_path, &si.snapshot_path)
                .await?;
            vm.resume().await?;
            vm.stop_vmm().await.unwrap();
            WorkerType::ColdSnapshot(si)
        } else {
            WorkerType::Cold
        };

        return Ok(Self {
            vminfo,
            wktype,
            client,
        });
    }

    pub async fn destroy(self) {
        let _permit = PERMITS.acquire().await.unwrap();
        if let WorkerType::Hot(mut vm) = self.wktype {
            // vm.wait will block until the firecracker process exit itself
            // vm.shutdown().await.unwrap();
            vm.stop_vmm().await.unwrap();
        }
        teardown_vm_network(&self.vminfo.tap_dev).await;
    }

    pub async fn serve(&self, work: Work) {
        info!("Serving request on {}", self.vminfo.vmid);
        match &self.wktype {
            WorkerType::Hot(_vm) => self.relay(work).await,
            WorkerType::ColdSnapshot(si) => {
                let mut vm = self.vminfo.new_machine();
                vm.start_vmm_test().await.unwrap();
                let snapshot_params = SnapshotLoadParams {
                    enable_diff_snapshots: None,
                    mem_file_path: Some(si.mem_file_path.clone()),
                    mem_backend: None,
                    resume_vm: Some(true),
                    snapshot_path: si.snapshot_path.clone(),
                };
                match vm.load_from_snapshot(&snapshot_params).await {
                    Ok(()) => {
                        self.relay(work).await;
                        self.stop_server().await;
                    }
                    Err(err) => {
                        warn!("{:?}", err);
                    }
                }
                // vm.stop_vmm().await.unwrap();
                // this method wait for the vmm process to terminate
                vm.stop_vmm_force().await.unwrap();
            }
            WorkerType::Cold => {
                let mut vm = self.vminfo.new_machine();
                match vm.start().await {
                    Ok(()) => {
                        self.relay(work).await;
                        self.stop_server().await;
                    }
                    Err(err) => {
                        warn!("{:?}", err);
                    }
                }
                vm.stop_vmm_force().await.unwrap();
            }
        }
    }

    async fn relay(&self, work: Work) {
        let Work(req, callback) = work;
        match http_relay(
            req,
            &format!("{}:8080", self.vminfo.ip),
            self.client.clone(),
        )
        .await
        {
            Ok(resp) => {
                if let Err(_r) = callback.send(resp) {
                    warn!("Request cancelled");
                }
            }
            Err(err) => {
                warn!("{:?}", err);
            }
        }
    }

    // stop the dedicated server inside the VM so that all connections with it will be terminated
    async fn stop_server(&self) {
        let url = format!("http://{}:{}/stop", self.vminfo.ip, 8080);
        let _err = self.client.post(url).send().await.unwrap_err();
        // wait for the connection termination
        tokio::time::sleep(Duration::from_millis(1)).await;
    }
}
