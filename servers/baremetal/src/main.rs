use http::StatusCode;
use http_body_util::{BodyExt, Collected, Either, Empty, Full};
use hyper::{
    body::{Bytes, Incoming},
    service::service_fn,
    Method, Request, Response,
};
use hyper_util::rt::TokioIo;
use libc::size_t;
use serde::{Deserialize, Serialize};
use std::{convert::Infallible, mem::size_of, net::SocketAddr, vec};
use tokio::{
    net::{TcpListener, TcpStream},
    task,
};

#[cfg(feature = "timestamp")]
use std::{sync::Arc, sync::Mutex, time::Instant};

#[cfg(feature = "middleware")]
#[macro_use]
extern crate lazy_static;

#[cfg(feature = "middleware")]
mod middleware;

#[link(name = "matmul")]
extern "C" {
    fn matmul(in_mat: *const i64, out_mat: *mut i64, rows: size_t, cols: size_t) -> ();
}

#[link(name = "busy")]
extern "C" {
    fn busy(
        iterations: u64,
        max_index: usize,
        data_items: *const i8,
        sum: *mut i64,
        min: *mut i64,
        max: *mut i64
    ) -> ();
}

#[link(name = "compress")]
extern "C" {
    fn compress(
       in_qoi: *const u8,
       qoi_size: i32,
       out_png: *mut *const u8, 
    ) -> i32;
}

#[cfg(feature = "timestamp")]
struct Record {
    timestamps: [Instant; 4],
}

fn matmul_service(data: &[u8]) -> Vec<u8> {
    assert_eq!(0, data.len() % size_of::<i64>());
    let rows = i64::from_le_bytes(data[0..8].try_into().unwrap()) as usize;
    let cols = (data.len() - 8) / size_of::<i64>() / rows;
    let mut out_mat: Vec<u8> = vec![0; (rows * cols + 1) * size_of::<i64>()];

    unsafe {
        matmul(
            (data.as_ptr() as *const i64).add(1),
            (out_mat.as_mut_ptr() as *mut i64).add(1),
            rows,
            cols,
        )
    }

    out_mat[0..8].copy_from_slice(&data[0..8]);

    return out_mat;
}

#[allow(unused)]
async fn http_request(
    uri: String,
    method: Method,
    body: Option<Full<Bytes>>,
    headers: &[(&str, &str)],
) -> Collected<hyper::body::Bytes> {
    let url = uri.parse::<hyper::Uri>().unwrap();
    let stream = TcpStream::connect(format!(
        "{}:{}",
        url.host().unwrap(),
        url.port_u16().unwrap()
    ))
    .await
    .unwrap();
    let io = TokioIo::new(stream);
    // Issue GET
    let (mut client, con) = hyper::client::conn::http1::handshake(io).await.unwrap();
    task::spawn(async move {
        con.await.unwrap();
    });

    let either_body = body
        .and_then(|bytes| Some(Either::Left(bytes)))
        .unwrap_or_else(|| Either::Right(Empty::<Bytes>::new()));

    // "Host" is mandatory in HTTP 1.1
    let mut request = Request::builder()
        .method(method)
        .uri(url.path_and_query().unwrap().as_str())
        .header("Host", url.authority().unwrap().as_str());

    for (key, value) in headers {
        request = request.header(*key, *value);
    }

    let request = request.body(either_body).expect("get request builder");

    // TODO: Handle status != OK
    let result = client
        .send_request(request)
        .await
        .expect("Http storage GET request");

    return result.collect().await.expect("Could not read request body");
}

async fn io_service(client: reqwest::Client, get_uri: String, post_uri: String) -> Vec<u8> {
    // Issue GET
    let mut get_request_buf = client
        .get(&get_uri)
        .send()
        .await
        .unwrap()
        .bytes()
        .await
        .unwrap()
        .to_vec();

    let iterations = u64::from_le_bytes(get_request_buf[0..8].try_into().unwrap());
    // Check response
    let mut sum: i64 = 7;
    let mut min = 0;
    let mut max = 0;
    let data_items = &mut get_request_buf[8..];
    assert_eq!(0, data_items.len() % 16);
    let max_index = data_items.len() / 16;
    unsafe { busy(iterations, max_index, data_items.as_ptr() as *const i8, &mut sum, &mut min, &mut max) }

    let mut response_buffer = Vec::with_capacity(3*size_of::<i64>());
    response_buffer.extend_from_slice(&sum.to_le_bytes());
    response_buffer.extend_from_slice(&min.to_le_bytes());
    response_buffer.extend_from_slice(&max.to_le_bytes());

    let post_response = client
        .post(post_uri)
        .body(response_buffer)
        .send()
        .await
        .unwrap()
        .bytes()
        .await
        .unwrap()
        .to_vec();

    let mut response_vec = b"\n\n".to_vec();
    response_vec.extend_from_slice(&post_response);

    return response_vec;
}

#[derive(Deserialize)]
#[allow(dead_code)]
struct LoaderRequest<'data> {
    name: String,
    #[serde(borrow)]
    sets: Vec<DataSet<'data>>,
}

#[derive(Serialize)]
#[allow(dead_code)]
struct LoaderResponse<'data> {
    #[serde(borrow)]
    sets: Vec<DataSet<'data>>,
}

#[derive(Deserialize, Serialize)]
#[allow(dead_code)]
struct DataSet<'data> {
    identifier: String,
    #[serde(borrow)]
    items: Vec<DataItem<'data>>,
}

#[derive(Deserialize, Serialize)]
#[allow(dead_code)]
struct DataItem<'data> {
    identifier: String,
    key: u32,
    #[serde(with = "serde_bytes")]
    data: &'data [u8],
}

#[allow(dead_code)]
async fn handle_matmul_checksum(
    req: Request<Incoming>,
    #[cfg(feature = "timestamp")] archive: Arc<Mutex<Vec<Record>>>,
) -> Result<Response<Full<Bytes>>, Infallible> {
    #[cfg(feature = "timestamp")]
    let mut record = Record {
        timestamps: [Instant::now(); 4],
    };
    // Parse request body
    let request_buf = req
        .collect()
        .await
        .expect("Could not read request body")
        .to_bytes();

    let LoaderRequest { name: _, sets } =
        bson::from_slice(&request_buf).expect("Should be able to deserialize matmul request");

    #[cfg(feature = "timestamp")]
    {
        record.timestamps[1] = Instant::now();
    }

    let response_data = matmul_service(sets[0].items[0].data);
    let response_struct = LoaderResponse {
        sets: vec![DataSet {
            identifier: String::from("outmatrix"),
            items: vec![DataItem {
                identifier: String::from(""),
                key: 0,
                data: &response_data[response_data.len() - 8..],
            }],
        }],
    };
    #[cfg(feature = "timestamp")]
    {
        record.timestamps[2] = Instant::now();
    }
    let response = Response::builder()
        .status(StatusCode::OK.as_u16())
        .body(bson::to_vec(&response_struct).unwrap().into())
        .unwrap();

    #[cfg(feature = "timestamp")]
    {
        record.timestamps[3] = Instant::now();
        archive.lock().unwrap().push(record);
    }
    return Ok::<_, Infallible>(response);
}

async fn handle_matmul_full_response(
    req: Request<Incoming>,
    #[cfg(feature = "timestamp")] archive: Arc<Mutex<Vec<Record>>>,
) -> Result<Response<Full<Bytes>>, Infallible> {
    #[cfg(feature = "timestamp")]
    let mut record = Record {
        timestamps: [Instant::now(); 4],
    };
    // Parse request body
    let request_buf = req
        .collect()
        .await
        .expect("Could not read request body")
        .to_bytes();

    let LoaderRequest { name: _, sets } =
        bson::from_slice(&request_buf).expect("Should be able to deserialize matmul request");

    #[cfg(feature = "timestamp")]
    {
        record.timestamps[1] = Instant::now();
    }

    let response_data = matmul_service(sets[0].items[0].data);
    let response_struct = LoaderResponse {
        sets: vec![DataSet {
            identifier: String::from("outmatrix"),
            items: vec![DataItem {
                identifier: String::from(""),
                key: 0,
                data: &response_data,
            }],
        }],
    };
    #[cfg(feature = "timestamp")]
    {
        record.timestamps[2] = Instant::now();
    }
    let response = Response::builder()
        .status(StatusCode::OK.as_u16())
        .body(bson::to_vec(&response_struct).unwrap().into())
        .unwrap();

    #[cfg(feature = "timestamp")]
    {
        record.timestamps[3] = Instant::now();
        archive.lock().unwrap().push(record);
    }
    return Ok::<_, Infallible>(response);
}

async fn handle_matmul_with_store(
    req: Request<Incoming>,
    client: reqwest::Client,
) -> Result<Response<Full<Bytes>>, Infallible> {
    // Parse request body
    let request_buf = req
        .collect()
        .await
        .expect("Could not read request body")
        .to_bytes();
    let LoaderRequest { name: _, sets } =
        bson::from_slice(&request_buf).expect("Should be able to deserialize compute request");
    let get_uri = std::str::from_utf8(sets[0].items[0].data)
        .unwrap()
        .strip_prefix("GET ")
        .unwrap()
        .strip_suffix(" HTTP/1.1")
        .unwrap()
        .to_string();
    let post_uri = std::str::from_utf8(sets[1].items[0].data)
        .unwrap()
        .strip_prefix("POST ")
        .unwrap()
        .strip_suffix(" HTTP/1.1")
        .unwrap()
        .to_string();

    // Issue GET
    let get_request_buf = client
        .get(get_uri)
        .send()
        .await
        .unwrap()
        .bytes()
        .await
        .unwrap();

    // run matmul on the data
    let post_buffer = matmul_service(&get_request_buf);

    // Issue POST request with checksum
    let _ = client
        .post(post_uri)
        .body(post_buffer)
        .send()
        .await
        .unwrap()
        .bytes()
        .await
        .unwrap();

    let response_message = "HTTP/1.1 200 OK";
    let response_struct = LoaderResponse {
        sets: vec![DataSet {
            identifier: String::from("store_body"),
            items: vec![DataItem {
                identifier: String::from("body"),
                key: 0,
                data: response_message.as_bytes(),
            }],
        }],
    };
    let response = Response::builder()
        .status(StatusCode::OK.as_u16())
        .body(bson::to_vec(&response_struct).unwrap().into())
        .unwrap();

    return Ok::<_, Infallible>(response);
}

async fn handle_io(
    req: Request<Incoming>,
    client: reqwest::Client,
) -> Result<Response<Full<Bytes>>, Infallible> {
    // Parse request body
    let request_buf = req
        .collect()
        .await
        .expect("Could not read request body")
        .to_bytes();
    let LoaderRequest {
        name: _,
        sets, // get_uri,
              // post_uri,
    } = bson::from_slice(&request_buf).expect("Should be able to deserialize compute request");
    let get_uri = std::str::from_utf8(sets[0].items[0].data)
        .unwrap()
        .strip_prefix("GET ")
        .unwrap()
        .strip_suffix(" HTTP/1.1")
        .unwrap()
        .to_string();
    let post_uri = std::str::from_utf8(sets[1].items[0].data)
        .unwrap()
        .strip_prefix("POST ")
        .unwrap()
        .strip_suffix(" HTTP/1.1\n\n")
        .unwrap()
        .to_string();

    let response_vec: Vec<u8> = io_service(client, get_uri, post_uri).await;
    let response_struct = LoaderResponse {
        sets: vec![DataSet {
            identifier: String::from("store_body"),
            items: vec![DataItem {
                identifier: String::from("body"),
                key: 0,
                data: &response_vec,
            }],
        }],
    };
    let response = Response::builder()
        .status(StatusCode::OK.as_u16())
        .body(bson::to_vec(&response_struct).unwrap().into())
        .unwrap();

    return Ok::<_, Infallible>(response);
}

async fn handle_chain(
    req: Request<Incoming>,
    client: reqwest::Client,
) -> Result<Response<Full<Bytes>>, Infallible> {
    // Parse request body
    let request_buf = req
        .collect()
        .await
        .expect("Could not read request body")
        .to_bytes();
    let LoaderRequest {
        name: _,
        sets, // get_uri,
              // post_uri,
    } = bson::from_slice(&request_buf).expect("Should be able to deserialize compute request");
    let get_uri = std::str::from_utf8(sets[0].items[0].data)
        .unwrap()
        .strip_prefix("GET ")
        .unwrap()
        .strip_suffix(" HTTP/1.1")
        .unwrap()
        .to_string();
    let post_uri = std::str::from_utf8(sets[1].items[0].data)
        .unwrap()
        .strip_prefix("POST ")
        .unwrap()
        .strip_suffix(" HTTP/1.1\n\n")
        .unwrap()
        .to_string();

    let mut layer_buf = [0u8; 8];
    layer_buf.copy_from_slice(&sets[2].items[0].data[0..8]);
    let layers = u64::from_le_bytes(layer_buf);

    // Issue GET
    let mut get_request_buf = client
        .get(&get_uri)
        .send()
        .await
        .unwrap()
        .bytes()
        .await
        .unwrap()
        .to_vec();

    for _ in 0..layers {
        let iterations = u64::from_le_bytes(get_request_buf[0..8].try_into().unwrap());
        let mut sum = 0;
        let mut min = 0;
        let mut max = 0;
        let data_items = &mut get_request_buf[8..];
        assert_eq!(0, data_items.len() % 16);
        let max_index = data_items.len() / 16;
        unsafe { busy(iterations, max_index, data_items.as_mut_ptr() as *mut i8, &mut sum, &mut min, &mut max) }

        let mut response_buffer = Vec::with_capacity(3*size_of::<i64>());
        response_buffer.extend_from_slice(&sum.to_le_bytes());
        response_buffer.extend_from_slice(&min.to_le_bytes());
        response_buffer.extend_from_slice(&max.to_le_bytes());

        get_request_buf = client
            .post(post_uri.clone())
            .body(response_buffer)
            .send()
            .await
            .unwrap()
            .bytes()
            .await
            .unwrap()
            .to_vec();
    }

    let response_struct = LoaderResponse {
        sets: vec![DataSet {
            identifier: String::from("store_body"),
            items: vec![DataItem {
                identifier: String::from("body"),
                key: 0,
                data: &get_request_buf,
            }],
        }],
    };
    let response = Response::builder()
        .status(StatusCode::OK.as_u16())
        .body(bson::to_vec(&response_struct).unwrap().into())
        .unwrap();

    return Ok::<_, Infallible>(response);
}

async fn handle_compression(req: Request<Incoming>) -> Result<Response<Full<Bytes>>, Infallible>{
    let request_buf = req
        .collect()
        .await
        .expect("Could not read request body")
        .to_bytes().to_vec().into_boxed_slice();
    let LoaderRequest { name: _, sets } =
        bson::from_slice(&request_buf).expect("Should be able to deserialize compression request");
    let qoi_picture = sets[0].items[0].data;

    let qoi_size = i32::try_from(qoi_picture.len()).unwrap();
    let mut png_pointer: *const u8 = std::ptr::null_mut();
    let png_size = unsafe {compress(qoi_picture.as_ptr(), qoi_size, &mut png_pointer)};
    assert!(png_size > 0);
    assert!(!png_pointer.is_null());
    let usize_png_size = usize::try_from(png_size).unwrap();
    let png_picture = unsafe {std::slice::from_raw_parts(png_pointer, usize_png_size)};
    
    let response_struct = LoaderResponse {
        sets: vec![DataSet {
            identifier: String::from("store_body"),
            items: vec![DataItem {
                identifier: String::from("body"),
                key: 0,
                data: png_picture,
            }],
        }],
    };
    let response = Response::builder()
        .status(StatusCode::OK.as_u16())
        .body(bson::to_vec(&response_struct).unwrap().into())
        .unwrap();

    unsafe {libc::free(png_pointer as *mut libc::c_void)};

    Ok::<_, Infallible>(response) 
}

async fn handle_stats(
    _req: Request<Incoming>,
    #[cfg(feature = "timestamp")] archive: Arc<Mutex<Vec<Record>>>,
) -> Result<Response<Full<Bytes>>, Infallible> {
    #[allow(unused_mut)]
    let mut archive_string = String::new();
    #[cfg(feature = "timestamp")]
    {
        let mut archive_guard = archive.lock().unwrap();
        for record in archive_guard.drain(0..) {
            archive_string.push_str(&format!(
                "parent:0, span:0, time:{}, point:{}, ",
                0, "Arrival",
            ));
            archive_string.push_str(&format!(
                "parent:0, span:0, time:{}, point:{}, ",
                record.timestamps[1]
                    .duration_since(record.timestamps[0])
                    .as_nanos(),
                "EngineStart",
            ));
            archive_string.push_str(&format!(
                "parent:0, span:0, time:{}, point:{}, ",
                record.timestamps[2]
                    .duration_since(record.timestamps[0])
                    .as_nanos(),
                "EngineEnd",
            ));
            archive_string.push_str(&format!(
                "parent:0, span:0, time:{}, point:{}, ",
                record.timestamps[3]
                    .duration_since(record.timestamps[0])
                    .as_nanos(),
                "EndService",
            ));
            archive_string.push_str("\n");
        }
    }

    let response = Response::builder()
        .status(StatusCode::OK.as_u16())
        .body(Full::new(archive_string.into()))
        .unwrap();
    return Ok::<_, Infallible>(response);
}

async fn handle_function(
    req: Request<Incoming>,
    client: reqwest::Client,
    #[cfg(feature = "timestamp")] archive: Arc<Mutex<Vec<Record>>>,
) -> Result<Response<Full<Bytes>>, Infallible> {
    let uri = req.uri().path();
    #[cfg(feature = "timestamp")]
    match uri {
        "/hot/matmul" | "cold/matmul" => handle_matmul_full_response(req, archive).await,
        "/hot/matmulstore" | "cold/matmulstore" => handle_matmul_with_store(req, client).await,
        "/hot/io" | "/cold/io" => handle_io(req, client).await,
        "/hot/chain_scaling_dedicated" | "/cold/chain_scaling_dedicated" => handle_chain(req, client).await,
        "/hot/compression_app" | "/cold/compression_app" => handle_compression(req).await,
        #[cfg(feature = "middleware")]
        "/hot/middleware_app" | "/cold/middleware_app" => middleware::handle(req, client).await,
        "/stats" => handle_stats(req, archive).await,
        "/stop" => std::process::exit(0),
        _ => Ok::<_, Infallible>(Response::new(format!("Hello, World\n").into())),
    }
    #[cfg(not(feature = "timestamp"))]
    match uri {
        "/hot/matmul" | "/cold/matmul" => handle_matmul_full_response(req).await,
        "/hot/matmulstore" | "cold/matmulstore" => handle_matmul_with_store(req, client).await,
        "/hot/io" | "/cold/io" => handle_io(req, client).await,
        "/hot/chain_scaling_dedicated" | "/cold/chain_scaling_dedicated" => handle_chain(req, client).await,
        "/hot/compression_app" | "/cold/compression_app" => handle_compression(req).await,
        #[cfg(feature = "middleware")]
        "/hot/middleware_app" | "/cold/middleware_app" => middleware::handle(req, client).await,
        "/stats" => handle_stats(req).await,
        "/stop" => std::process::exit(0),
        _ => Ok::<_, Infallible>(Response::new(format!("Hello, World\n").into())),
    }
}

#[cfg(feature = "register")]
async fn register_ready() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    // send out ping to signal ready
    // assumes that other end of eth0 with ip 1 bellow own is waiting for ping
    use std::net::IpAddr;
    let interfaces = pnet::datalink::interfaces();
    let eth0 = interfaces.iter().find(|e| e.name == "eth0").unwrap();
    println!("Interface [{}]", eth0.name);

    let address = eth0.ips[0].ip();
    println!("IP Address: {:?}", address);
    let bytes = if let IpAddr::V4(addr) = eth0.ips[0].ip() {
        addr.octets()
    } else {
        panic!("no valid ipv4 address");
    };
    let url = format!(
        "http://{}.{}.{}.{}:8080/register",
        bytes[0],
        bytes[1],
        bytes[2],
        bytes[3] - 1,
    );

    let id = (bytes[2] as u32 * 256 + bytes[3] as u32 - 2) / 4;
    let _response = http_request(
        url,
        Method::POST,
        Some(Full::new(id.to_be_bytes().to_vec().into())),
        &[],
    )
    .await;

    Ok(())
}

#[tokio::main]
async fn main() {
    #[cfg(feature = "middleware")]
    eprintln!("Storage host: {}", *middleware::AUTH_SERVER);

    #[cfg(feature = "timestamp")]
    let mut archive = Vec::new();
    #[cfg(feature = "timestamp")]
    archive.reserve(100000);
    #[cfg(feature = "timestamp")]
    let archive_ptr = Arc::new(Mutex::new(archive));

    // ready http endpoint
    let addr = SocketAddr::from(([0, 0, 0, 0], 8080));
    let listener = TcpListener::bind(addr).await.unwrap();

    // create client for outgoing requests
    let client = reqwest::Client::new();

    eprintln!("Started listening on {:?}", addr);

    #[cfg(feature = "register")]
    tokio::spawn(async {
        register_ready().await.expect("Register failed");
    });

    loop {
        let (stream, _) = listener.accept().await.unwrap();
        let io = hyper_util::rt::TokioIo::new(stream);
        let local_client = client.clone();
        #[cfg(feature = "timestamp")]
        let loop_archive = archive_ptr.clone();
        tokio::task::spawn(async move {
            #[cfg(feature = "timestamp")]
            let task_archive = loop_archive.clone();
            if let Err(err) = hyper::server::conn::http1::Builder::new()
                .serve_connection(
                    io,
                    service_fn(|req| {
                        handle_function(
                            req,
                            local_client.clone(),
                            #[cfg(feature = "timestamp")]
                            task_archive.clone(),
                        )
                    }),
                )
                .await
            {
                println!("Error serving connection: {:?}", err);
            }
        });
    }
}
