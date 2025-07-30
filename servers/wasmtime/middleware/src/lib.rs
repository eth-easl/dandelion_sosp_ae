use spin_sdk::http::{Request, Response, Method};
use spin_sdk::{http_component, variables};
use serde::{Deserialize, Serialize};
use futures;

#[derive(Debug, Deserialize)]
struct MiddlewareAuthResponse {
    authorized: String,
    token: String,
}

#[derive(Debug, Deserialize)]
struct MiddlewareLogsEvent {
    details: String,
    event_type: String,
    server_id: String,
    timestamp: String,
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

const LOG_SERVER_COUNT: usize = 10;

#[http_component]
async fn handle_middleware(req: Request) -> Result<Response, anyhow::Error> {

    let storage_server_ip = variables::get("storage_ip");

    let auth_server: String = match storage_server_ip {
        Ok(s) => s,
        Err(e) => {
            eprintln!("Failed to get auth server: {}", e);
            "default_server".to_string() // Provide a default value
        },
    };

    const LOGS_TEMPLATE_HEAD: &str =
        r#"<!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>Logs</title>
        </head>
        <body>
            <table>
                <tr>
                    <th>Timestamp</th>
                    <th>Server ID</th>
                    <th>Event Type</th>
                    <th>Details</th>
                </tr>"#;

    const LOGS_TEMPLATE_TAIL: &str =
    r#"
        </table>
    </body>"#;

    fn render_page(events: &[MiddlewareLogsEvent]) -> String {
        let mut page = LOGS_TEMPLATE_HEAD.to_string();
        for event in events {
            page.push_str(&format!(
            r#"
        <tr>
            <th>{}</th>
            <th>{}</th>
            <th>{}</th>
            <th>{}</th>
        <\tr>"#, 
                event.timestamp, event.server_id, event.event_type, event.details
            ));
        }
        page.push_str(LOGS_TEMPLATE_TAIL);
        return page;
    }

    let request_buf = req.body();
    let LoaderRequest {
        name: _,
        sets, // get_uri,
              // post_uri,
    } = bson::from_slice(&request_buf).expect("Should be able to deserialize compute request");

    let auth_token = {
        assert!(sets[0].items[0].identifier == "Authorization");
        let auth_header =
            std::str::from_utf8(sets[0].items[0].data).expect("invalid Authorization token");
        let mut auth_header = auth_header.split(" ");
        assert!(auth_header.next().unwrap() == "Bearer");
        let auth_token = auth_header.next().unwrap().to_string();
        auth_token
    };
    let auth_req_body = serde_json::json!({
        "token": auth_token,
    });

    let body = serde_json::to_string(&auth_req_body).unwrap();
    let url_string = format!("http://{}/authorize", auth_server);

    let auth_request = Request::builder()
        .method(Method::Post)
        .uri(url_string)
        .body(body.clone())
        .header("content-type", "application/json")
        .build();

    let auth_response: Response = spin_sdk::http::send(auth_request).await?;
    let auth_resp_bytes = auth_response.body().to_vec();
    let auth_resp: MiddlewareAuthResponse =
        serde_json::from_slice(&auth_resp_bytes).expect("invalid auth response");
    
    let log_servers = (0..LOG_SERVER_COUNT)
    .map(|e| format!("http://{}/logs/{}",auth_server, e))
    .collect::<Vec<_>>();
    let _ = &auth_resp.authorized;
    let auth_header_value = format!("Bearer {}", auth_resp.token);
    let log_requests: Vec<_> = log_servers
        .into_iter()
        .map(|log_server| {
            let auth_header_value = &auth_header_value;
            let body = body.clone();
            async move {
                let fetch_log_request = Request::builder()
                    .method(Method::Get)
                    .uri(log_server)
                    .header("Authorization", auth_header_value)
                    .body(body.clone())
                    .build();
                let fetch_log_response: Result<spin_sdk::http::Response, _> =
                    spin_sdk::http::send(fetch_log_request).await;
                match fetch_log_response {
                    Ok(response) => {
                        let bytes = response.body().to_vec();
                        Ok(bytes)
                    }
                    Err(e) => {
                        println!("Error sending request: {:?}", e);
                        Err(e)
                    }
                }
            }
        })
        .collect::<Vec<_>>();
    let mut logs = futures::future::join_all(log_requests)
        .await
        .into_iter()
        .filter_map(|result| {
            match result {
                Ok(bytes) => {
                    let log_json: serde_json::Value =
                        serde_json::from_slice(&bytes).expect("invalid log response");
                        let events = log_json.get("events").expect("invalid log response");
                        let events = events.as_array().expect("invalid log response");
                    Some(
                        events
                            .into_iter()
                            .map(|event| {
                                let event: MiddlewareLogsEvent =
                                    serde_json::from_value(event.clone()).expect("invalid log response");
                                event
                            })
                            .collect::<Vec<MiddlewareLogsEvent>>()
                    )
                }
                Err(e) => {
                    eprintln!("Request failed: {:?}", e);
                    None
                }
            }
        })
        .flatten()
        .collect::<Vec<MiddlewareLogsEvent>>();
    logs.sort_by(|a, b| a.timestamp.cmp(&b.timestamp));
    let rendered = render_page(&logs);

    let response_struct = LoaderResponse {
        sets: vec![DataSet {
            identifier: String::from("requests"),
            items: vec![DataItem {
                identifier: String::from("body"),
                key: 0,
                data: &rendered.as_bytes(),
            }],
        }],
    };

    let response = Response::builder()
        .status(200)
        .body(bson::to_vec(&response_struct).unwrap())
        .build();
    Ok(response)

}


