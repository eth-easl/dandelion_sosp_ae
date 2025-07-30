fn main() {
  // Tell Cargo that if the given file changes, to rerun this build script.
  println!("cargo:rerun-if-changed=src/matmul.c");
  // Use the `cc` crate to build a C file and statically link it.
  cc::Build::new()
    .file("src/matmul.c")
    .flag("-O3")
    .static_flag(true)
    .compile("matmul");
}