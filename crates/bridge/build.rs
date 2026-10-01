//! Generates the method-name table the Backend Bridge dispatches on, from the same
//! descriptors (and the same camelCase rule) Anki uses for its TypeScript client.

use std::fmt::Write;

use anki_proto_gen::{descriptors_path, get_services};
use inflections::Inflect;
use prost_reflect::DescriptorPool;

fn main() -> anyhow::Result<()> {
    println!("cargo:rerun-if-changed=proto/klaus.proto");
    prost_build::compile_protos(&["proto/klaus.proto"], &["proto"])?;

    let path = descriptors_path();
    println!("cargo:rerun-if-changed={}", path.display());
    let pool = DescriptorPool::decode(std::fs::read(&path)?.as_ref())?;
    let (_, services) = get_services(&pool);

    let mut out = String::from("pub(crate) static METHODS: &[(&str, u32, u32)] = &[\n");
    for service in services.iter().filter(|s| s.name != "BackendAnkidroidService") {
        for method in service.trait_methods.iter().chain(&service.delegating_methods) {
            let name = method.name.to_camel_case();
            writeln!(out, "    ({name:?}, {}, {}),", service.index, method.index)?;
        }
    }
    out.push_str("];\n");
    std::fs::write(std::path::Path::new(&std::env::var("OUT_DIR")?).join("methods.rs"), out)?;
    Ok(())
}
