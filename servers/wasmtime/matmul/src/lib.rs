use spin_sdk::http::{IntoResponse, Request, Response};
use spin_sdk::http_component;
use serde::{Deserialize, Serialize};
use bson::{from_slice, to_vec, doc};
use std::{mem::size_of, vec};


#[link(name = "matmul")]
extern "C" {
    fn matmul(in_mat: *const i64, out_mat: *mut i64, rows: usize, cols: usize) -> ();
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

/// A simple Spin HTTP component.
#[http_component]
fn handle_request(req: Request) -> anyhow::Result<impl IntoResponse> {
    handle_matmul(req)
}

fn handle_matmul(req: Request) -> Result<Response, anyhow::Error> {
    let body_bytes = req.body();
    if body_bytes.is_empty() {
        return Ok(Response::builder()
            .status(400)
            .body("Request body is empty")
            .build());
    }
    let LoaderRequest { name: _, sets } =
        from_slice::<LoaderRequest>(body_bytes).expect("Should deserialize matmul request");

    // Perform matrix multiplication
    let response_data = matmul_service(sets[0].items[0].data);

    // Construct the response structure
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

    // Serialize the response structure back to BSON
    let response_bson = to_vec(&response_struct)?;

    Ok(Response::builder()
        .status(200)
        .header("Content-Type", "application/bson")
        .body(response_bson)
        .build())
}