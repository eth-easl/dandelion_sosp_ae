use clap::Parser;
use core::slice;
use http_body_util::{BodyExt, Full};
use hyper::{
    body::{Buf, Bytes, Incoming},
    service::service_fn,
    Request, Response,
};
use log::{debug, error};
use serde_json::Value;
use std::{convert::Infallible, net::SocketAddr};
use tokio::{net::TcpListener, signal::unix::SignalKind, time::Duration};

static IO_VALUES: [i8; 16] = [
    -53, 32, 60, -29, 113, 109, -113, 89, -112, 0, -114, -120, 84, -50, 94, 98,
];
async fn handle(req: Request<Incoming>, args: Args) -> Result<Response<Full<Bytes>>, Infallible> {
    let uri = req.uri().path().to_string();
    let method = req.method().clone();
    let mut request_body = req
        .collect()
        .await
        .expect("Should be able to collect packets from incomming request")
        .to_bytes();
    let mut path_iterator: std::iter::Skip<std::str::Split<&str>> = uri.split("/").skip(1);
    let first_folder = path_iterator.next();
    debug!("Got request for {:?}", first_folder);
    let response_body: Bytes = match (&method, first_folder) {
        (&hyper::Method::GET, Some("io")) | (&hyper::Method::POST, Some("io")) => {
            if let &hyper::Method::POST = &method {
                // check that the posted checksum is correct
                let sum = request_body.get_i64_le();
                let min = request_body.get_i64_le();
                let max = request_body.get_i64_le();
                debug!("Post on io post got sum {}, min {}, max {}", sum, min, max);
            }
            let iteration = usize::try_from(
                path_iterator
                    .next()
                    .and_then(|value| value.parse::<u64>().ok())
                    .unwrap_or(1u64),
            )
            .unwrap();
            let byte_count = path_iterator
                .next()
                .and_then(|value| value.parse::<usize>().ok())
                .unwrap_or(8usize);
            debug!(
                "Sending out io response with {} iterations and {} bytes",
                iteration, byte_count
            );

            let mut output_vec = Vec::with_capacity(8 + iteration * IO_VALUES.len());
            output_vec.extend_from_slice(&iteration.to_le_bytes());
            // need to subtract 8 for the iteration count, then add 15 to round up
            let mut number_of_chunks = (byte_count - 8 + 15) / 16;
            // need to make sure there is at least one chunck
            if number_of_chunks == 0 {
                number_of_chunks = 1;
            }
            for _ in 0..number_of_chunks {
                // only way to cast a slice
                let u8_slice = unsafe {
                    slice::from_raw_parts(IO_VALUES.as_ptr() as *const u8, IO_VALUES.len())
                };
                output_vec.extend_from_slice(u8_slice);
            }
            Bytes::from(output_vec)
        }
        (&hyper::Method::GET, Some("matrix")) => {
            let size = path_iterator
                .next()
                .and_then(|value| value.parse::<i64>().ok())
                .unwrap();
            let mut matrix = Vec::with_capacity((size * size) as usize + 1);
            matrix.extend_from_slice(&size.to_le_bytes());
            for i in 0..size * size {
                matrix.extend_from_slice(&(i as i64 + 1).to_le_bytes());
            }
            Bytes::from(matrix)
        }
        (&hyper::Method::POST, Some("post")) | (&hyper::Method::POST, Some("mirror")) => {
            debug!("mirroring {} bytes", request_body.len());
            Bytes::from(request_body)
        }
        (&hyper::Method::POST, Some("authorize")) => {
            fn mk_failure() -> Response<Full<Bytes>> {
                Response::builder()
                    .status(400)
                    .body(Full::new(Bytes::from("invalid request\n")))
                    .unwrap()
            }
            let Ok(content) = serde_json::from_slice::<Value>(&request_body) else {
                debug!(
                    "authorize: could not deserialize json from body {:?}",
                    &request_body
                );
                return Ok(mk_failure());
            };
            let Some(token) = content.get("token") else {
                debug!("authorize: no token in json");
                return Ok(mk_failure());
            };

            Bytes::from(
                serde_json::json!({
                    "authorized": "myusername",
                    "token": token,
                })
                .to_string(),
            )
        }
        (&hyper::Method::GET, Some("logs")) => {
            let Some(id): Option<usize> = path_iterator.next().and_then(|x| x.parse().ok()) else {
                return Ok(Response::builder()
                    .status(400)
                    .body(Full::new(Bytes::from("invalid request\n")))
                    .unwrap());
            };
            const EVENT_COUNT: usize = 20;
            let duration = std::time::Duration::from_secs(60 * 60 * 4);
            let now = chrono::Utc::now();
            let mut cur_timestamp = now - duration;
            let mut make_event = |id: usize, started: bool| -> serde_json::Value {
                let duration_left: std::time::Duration = (now - cur_timestamp).to_std().unwrap();
                let step_seconds = rand::Rng::gen_range(&mut rand::thread_rng(), 0f64..1f64)
                    * duration_left.as_secs_f64();
                cur_timestamp += std::time::Duration::from_secs_f64(step_seconds);
                let timestamp_str = cur_timestamp.to_rfc3339();
                serde_json::json!({
                    "timestamp": timestamp_str,
                    "event_type": (if started { "Server_Started" } else { "Server_Stopped" }),
                    "server_id": (format!("server{id:03}")),
                    "details": (format!("Server with ID server{id:03} {} successfully.", if started { "started" } else { "stopped" })),
                })
            };
            let events = (0..EVENT_COUNT)
                .map(|i| make_event(id + (i % 4), (i % 4) % 2 == 0))
                .collect::<Vec<serde_json::Value>>();
            let res_json = serde_json::json!({
                "events": events,
                "next_id": id + 20,
            });
            log::trace!("{}", res_json.to_string());
            Bytes::from(res_json.to_string())
        }
        _ => Bytes::from("Hello World\n".to_string()),
    };
    if let Some(delay) = args.delay {
        tokio::time::sleep(Duration::from_micros(delay)).await;
    }

    return Ok(Response::new(Full::new(response_body)));
}

#[derive(clap::Parser, Clone, Copy)]
struct Args {
    /// Delay added to requests in us
    #[arg(short, long)]
    delay: Option<u64>,
}

#[tokio::main]
async fn main() {
    // initialize logger
    env_logger::init();
    let args = Args::parse();

    // Construct our SocketAddr to listen on...
    let addr = SocketAddr::from(([0, 0, 0, 0], 8000));

    // construct listener
    let listener = TcpListener::bind(addr).await.unwrap();
    // signal handlers for gracefull shutdown
    let mut sigterm_stream = tokio::signal::unix::signal(SignalKind::terminate()).unwrap();
    let mut sigint_stream = tokio::signal::unix::signal(SignalKind::interrupt()).unwrap();
    let mut sigquit_stream = tokio::signal::unix::signal(SignalKind::quit()).unwrap();
    loop {
        tokio::select! {
            connection_pair = listener.accept() => {
                let (stream,_) = connection_pair.unwrap();
                let io = hyper_util::rt::TokioIo::new(stream);
                tokio::task::spawn(async move {
                    if let Err(err) = hyper_util::server::conn::auto::Builder::new(hyper_util::rt::TokioExecutor::new())
                        .serve_connection_with_upgrades(
                            io,
                            service_fn(move |req| handle(req, args)),
                        )
                        .await
                    {
                        error!("Request serving failed with error: {:?}", err);
                    }
                });
            }
            _ = sigterm_stream.recv() => return,
            _ = sigint_stream.recv() => return,
            _ = sigquit_stream.recv() => return,
        }
    }
}
