use spin_sdk::http::{Request, Method, Response};
use spin_sdk::http_component;
use serde::{Deserialize, Serialize};
use std::mem::size_of;


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

#[http_component]
async fn handle_chainscaling(req: Request) -> Result<Response, anyhow::Error> {

    let body_bytes = req.body();
    if body_bytes.is_empty() {
        return Ok(Response::builder()
            .status(400)
            .body("Request body is empty")
            .build());
    }

    let LoaderRequest {
        name: _,
        sets, // get_uri,
              // post_uri,
    } = bson::from_slice(&body_bytes).expect("Should be able to deserialize compute request");

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

    let get_request = Request::builder()
        .method(Method::Get)
        .uri(get_uri)
        .build();

    let get_request_response: Response = spin_sdk::http::send(get_request).await?;
    let mut get_request_buf = get_request_response.body().to_vec(); 

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

        let post_request = Request::builder()
            .method(Method::Post)
            .uri(post_uri.clone())
            .body(response_buffer)
            .build();

        let get_request_response: Response = spin_sdk::http::send(post_request).await?;
        get_request_buf = get_request_response.body().to_vec();
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
        .status(200)
        .body(bson::to_vec(&response_struct).unwrap())
        .build();

    return Ok(response);
}