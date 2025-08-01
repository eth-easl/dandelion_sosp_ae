mod network;
mod util;
mod vm;

use async_channel::Sender;
use clap::Parser;
use http_body_util::{BodyExt, Full};
use hyper::{
    body::{Bytes, Incoming},
    service::service_fn,
    Request, Response,
};
use hyper_util::rt::TokioIo;
use lazy_static::lazy_static;
use log::{info, warn};
use rustcracker::utils::check_kvm;
use std::{convert::Infallible, net::SocketAddr, path::PathBuf, sync::Arc, time::Duration};
use tokio::{
    net::TcpListener,
    signal::unix::SignalKind,
    sync::{oneshot, Barrier},
};
use tokio_util::{sync::CancellationToken, task::TaskTracker};

use network::{setup_server_network, teardown_server_network};
use vm::VirtualMachineWorker;

// async fn http_get_status(authority: &str, path: &str) -> Result<(), Box<dyn Error>> {
//     let stream: TcpStream = TcpStream::connect(authority).await?;
//     let io = TokioIo::new(stream);
//     let (mut client, con) = hyper::client::conn::http1::handshake(io).await.unwrap();
//     tokio::task::spawn(async move {
//         con.await.unwrap();
//     });

//     let request = Request::builder()
//         .method(Method::GET)
//         .uri(path)
//         .header("Host", authority)
//         .body(Empty::<Bytes>::new())
//         .expect("get request builder");

//     // TODO: Handle status != OK
//     let status = client.send_request(request).await?.status();
//     if !status.is_success() {
//         return Err(format!("{}", status).into());
//     }

//     return Ok(());
// }

// async fn test_ready(ip: &str, vmid: &str) {
//     let authority = format!("{}:{}", ip, 8080);
//     for _i in 0..10 {
//         tokio::time::sleep(Duration::from_millis(100)).await;
//         match http_get_status(&authority, "/").await {
//             Ok(()) => {
//                 info!("{} ready", vmid);
//                 return;
//             }
//             Err(err) => info!("Error sending GET request: {}", err),
//         }
//     }
//     warn!("{} is unreachable!", vmid);
// }

// async fn http_relay(mut req: Request<Incoming>, authority: &str) -> Response<Full<Bytes>> {
//     let stream = TcpStream::connect(authority).await.unwrap();
//     let io = TokioIo::new(stream);
//     let (mut client, con) = hyper::client::conn::http1::handshake(io).await.unwrap();
//     tokio::task::spawn(async move {
//         con.await.unwrap();
//     });

//     // eprintln!("{:#?}", req);
//     let _prev_host = req
//         .headers_mut()
//         .insert("host", authority.parse().unwrap())
//         .unwrap();
//     // eprintln!("{:#?}", req);
//     let response = client
//         .send_request(req)
//         .await
//         .expect("Http storage GET request");

//     return Response::new(Full::new(
//         response
//             .collect()
//             .await
//             .expect("Could not read request body")
//             .to_bytes(),
//     ));
// }

async fn test_ready(ip: &str, vmid: &str, client: reqwest::Client) {
    let url = format!("http://{}:{}", ip, 8080);
    for _i in 0..10 {
        tokio::time::sleep(Duration::from_millis(100)).await;
        match client.get(&url).send().await.map(|r| r.error_for_status()) {
            Ok(Ok(_r)) => {
                info!("{} ready", vmid);
                return;
            }
            Ok(Err(err)) | Err(err) => info!("Error sending GET request: {}", err),
        }
    }
    warn!("{} is unreachable!", vmid);
}

async fn http_relay(
    req: Request<Incoming>,
    authority: &str,
    client: reqwest::Client,
) -> Result<Response<Full<Bytes>>, Box<dyn std::error::Error>> {
    assert!(req.uri().authority().is_none());
    assert!(req.uri().path().starts_with("/"));
    let method = req.method().clone();
    let url = format!("http://{}{}", authority, req.uri());
    let headers = req.headers().clone();
    let body = req.collect().await?.to_bytes();
    let resp = client
        .request(method, url)
        .headers(headers)
        .body(body)
        .send()
        .await?;
    // let resp = loop {
    //     match client
    //         .request(method.clone(), url.clone())
    //         .headers(headers.clone())
    //         .body(body.clone())
    //         .send()
    //         .await
    //     {
    //         Ok(r) => break r,
    //         Err(err) if err.is_connect() => {
    //             warn!("{:?}", err);
    //             tokio::time::sleep(Duration::from_millis(100)).await
    //         }
    //         Err(err) => panic!("{:?}", err),
    //     }
    // };
    let body = resp.bytes().await.unwrap();
    return Ok(Response::new(Full::<Bytes>::new(body)));
}

struct Work(Request<Incoming>, oneshot::Sender<Response<Full<Bytes>>>);

async fn handle_work(
    req: Request<Incoming>,
    work_queue: Sender<Work>,
) -> Result<Response<Full<Bytes>>, Infallible> {
    let (resp_tx, resp_rx) = oneshot::channel();
    work_queue.send(Work(req, resp_tx)).await.unwrap();
    let response = resp_rx.await.unwrap_or_else(|e| {
        Response::builder()
            .status(500)
            .body(format!("{:?}", e).into())
            .unwrap()
    });
    return Ok(response);
}

async fn handle_function(
    req: Request<Incoming>,
    hot_work_queue: Sender<Work>,
    cold_work_queue: Sender<Work>,
) -> Result<Response<Full<Bytes>>, Infallible> {
    match req.uri().path() {
        path if path.starts_with("/hot") => handle_work(req, hot_work_queue).await,
        path if path.starts_with("/cold") => handle_work(req, cold_work_queue).await,
        _ => Ok(Response::new(format!("Server Alive\n").into())),
    }
}

#[derive(Parser, Debug)]
struct Args {
    /// Number of hot machines to use
    #[arg(short, long)]
    hot: u32,

    /// Maximum number of cold machines to use
    #[arg(short, long)]
    cold: u32,

    /// Use snapshotting to speed up cold starts
    #[arg(long, action = clap::ArgAction::Set)]
    use_snapshots: bool,

    /// Path to kernel image
    #[arg(short, long)]
    kernel_path: PathBuf,

    /// Path to rootfs archive
    #[arg(short, long)]
    rootfs_path: PathBuf,

    /// Path to firecracker binary
    #[arg(short, long)]
    firecracker_path: PathBuf,

    /// Attach to the serial console of the VM
    #[arg(long, default_value_t = false)]
    attach_vm: bool,

    /// Which network device to attach the taps to
    #[arg(long, default_value_t = String::from("lo"))]
    nic_ip: String,
}

lazy_static! {
    static ref ARGS: Args = Args::parse();
}

#[tokio::main]
async fn main() {
    env_logger::init();

    // parse arguments here
    println!("arguments: {:#?}", *ARGS);
    info!("Launching");
    check_kvm().unwrap();
 
    let mut ip_address = std::process::Command::new("ip");
    ip_address.arg("address");
    ip_address.stdout(std::process::Stdio::piped());
    let mut ip_address_com = ip_address.spawn().expect("Failed to run `ip address`");
    let network_string = String::from_utf8(
        std::process::Command::new("grep")
        .arg(&ARGS.nic_ip)
        .stdin(ip_address_com.stdout.take().expect("Failed to take `ip address` stdout"))
        .output()
        .expect("Should get output from grepping for IP in `ip address`")
        .stdout
    ).unwrap();
    let network_device: &str = Box::leak(network_string.split(' ').nth_back(0).unwrap().trim().to_string().into_boxed_str()); 

    println!("have network device: {:?}", &network_device);
    
    setup_server_network(&network_device).await;

    let ready = Arc::new(Barrier::new((ARGS.hot + ARGS.cold + 1) as usize));
    let token = CancellationToken::new();
    let tracker = TaskTracker::new();
    let (hot_work_queue_tx, hot_work_queue_rx) = async_channel::unbounded::<Work>();
    let (cold_work_queue_tx, cold_work_queue_rx) = async_channel::unbounded::<Work>();

    for id in 0..ARGS.hot {
        let ready = ready.clone();
        let token = token.clone();
        let hot_work_queue_rx = hot_work_queue_rx.clone();
        tracker.spawn(async move {
            let worker = loop {
                match VirtualMachineWorker::create(id, true, &network_device).await {
                    Ok(worker) => break worker,
                    Err(err) => warn!("{:?}", err),
                }
            };
            ready.wait().await;
            loop {
                tokio::select! {
                    work = hot_work_queue_rx.recv() => {
                        worker.serve(work.unwrap()).await;
                    },
                    _ = token.cancelled() => break,
                }
            }
            worker.destroy().await;
        });
    }

    for id in ARGS.hot..ARGS.hot + ARGS.cold {
        let ready = ready.clone();
        let token = token.clone();
        let cold_work_queue_rx = cold_work_queue_rx.clone();
        tracker.spawn(async move {
            let worker = loop {
                match VirtualMachineWorker::create(id, false, &network_device).await {
                    Ok(worker) => break worker,
                    Err(err) => warn!("{:?}", err),
                }
            };
            ready.wait().await;
            loop {
                tokio::select! {
                    work = cold_work_queue_rx.recv() => {
                        worker.serve(work.unwrap()).await;
                    },
                    _ = token.cancelled() => break,
                }
            }
            worker.destroy().await;
        });
    }

    let addr = SocketAddr::from(([0, 0, 0, 0], 8080));
    let listener = TcpListener::bind(addr).await.unwrap();

    let mut sigterm_stream = tokio::signal::unix::signal(SignalKind::terminate()).unwrap();
    let mut sigint_stream = tokio::signal::unix::signal(SignalKind::interrupt()).unwrap();
    let mut sigquit_stream = tokio::signal::unix::signal(SignalKind::quit()).unwrap();

    ready.wait().await;
    println!("Server ready");

    loop {
        let hot_work_queue_tx = hot_work_queue_tx.clone();
        let cold_work_queue_tx = cold_work_queue_tx.clone();
        tokio::select! {
            connection_pair = listener.accept() => {
                if let Err(err) = connection_pair {
                    warn!("Error accepting connection: {}", err);
                    continue;
                }
                let (stream, _) = connection_pair.unwrap();
                let io = TokioIo::new(stream);
                tokio::task::spawn(async move {
                    if let Err(err) = hyper::server::conn::http1::Builder::new()
                        .serve_connection(io, service_fn(|req| handle_function(req, hot_work_queue_tx.clone(), cold_work_queue_tx.clone())))
                        .await
                    {
                        warn!("Error serving connection: {}", err);
                    }
                });
                // let (client, _) = connection_pair.unwrap();
                // let server = TcpStream::connect("169.254.0.2:8080").await.unwrap();
                // let (mut eread, mut ewrite) = client.into_split();
                // let (mut oread, mut owrite) = server.into_split();
                // let e2o = tokio::spawn(async move { tokio::io::copy(&mut eread, &mut owrite).await });
                // let o2e = tokio::spawn(async move { tokio::io::copy(&mut oread, &mut ewrite).await });
            }
            _ = sigterm_stream.recv() => break,
            _ = sigint_stream.recv() => break,
            _ = sigquit_stream.recv() => break,
        }
    }

    println!("");
    info!("Stopping");

    token.cancel();
    tracker.close();
    tracker.wait().await;

    teardown_server_network(&network_device).await;
}
