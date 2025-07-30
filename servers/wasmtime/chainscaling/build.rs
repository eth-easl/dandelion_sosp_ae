fn main() {
  // Tell Cargo that if the given file changes, to rerun this build script.
  println!("cargo:rerun-if-changed=src/busy.c");
  // Use the `cc` crate to build a C file and statically link it.
  cc::Build::new()
    .file("src/busy.c")
    .flag("-O3")
    .static_flag(true)
    .compile("busy");
}