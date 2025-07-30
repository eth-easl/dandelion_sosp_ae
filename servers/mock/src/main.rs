
fn handle_http<'r>(req: &'r rocket::Request, _: rocket::Data<'r>) -> rocket::route::BoxFuture<'r> {
    rocket::route::Outcome::from(req, &[0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01][..]).pin() // 8 bytes
}

#[rocket::launch]
fn rocket() -> _ {
    use rocket::http::Method::*;
    let mut routes = vec![];
    for method in &[Get, Put, Post, Delete, Options, Head, Trace, Connect, Patch] {
        routes.push(rocket::Route::new(*method, "/<path..>", handle_http));
    }
    let mut config = rocket::Config::default();
    config.port = 8080;
    rocket::build().configure(config).mount("/", routes)
}
