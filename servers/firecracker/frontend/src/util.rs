use std::ffi::OsStr;
use tokio::process::Command;

pub async fn sudo<I, S>(command: I)
where
    I: IntoIterator<Item = S>,
    S: AsRef<OsStr>,
{
    let mut cmd = Command::new("sudo");
    cmd.args(command);
    let out = cmd.output().await.unwrap();
    if !out.status.success() {
        panic!(
            "command {:?} failed: {}",
            cmd.as_std()
                .get_args()
                .collect::<Vec<_>>()
                .join(OsStr::new(" ")),
            &String::from_utf8_lossy(&out.stderr),
        );
    }
}

pub async fn sudo_unchecked<I, S>(command: I)
where
    I: IntoIterator<Item = S>,
    S: AsRef<OsStr>,
{
    let _out = Command::new("sudo").args(command).output().await.unwrap();
}
