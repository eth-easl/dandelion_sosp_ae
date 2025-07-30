fn main() {
    // Tell Cargo that if the given file changes, to rerun this build script.
    println!("cargo:rerun-if-changed=src/matmul.c");
    println!("cargo:rerun-if-changed=src/busy.c");
    println!("cargo:rerun-if-changed=src/compress.c");
    println!("cargo:rerun-if-changed=src/qoi.h");
    println!("cargo:rerun-if-changed=src/std_image_write.h");
    // Use the `cc` crate to build a C file and statically link it.
    cc::Build::new()
        .file("src/matmul.c")
        .flag("-O3")
        .static_flag(true)
        .compile("matmul");
    cc::Build::new()
        .file("src/busy.c")
        .flag("-O3")
        .static_flag(true)
        .compile("busy");
    cc::Build::new()
        .file("src/compression.c")
        .flag("-O3")
        .static_flag(true)
        .compile("compress");
}
