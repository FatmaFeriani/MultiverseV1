use std::fs::OpenOptions;
use std::io::{self, Write};
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;
use caps::{CapSet, Capability};
use tokio::net::{TcpListener, TcpStream};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, Command as TokioCommand};
use tokio::sync::Mutex;
use tokio::time::sleep;

const PCU :&str = "pcu_state.txt";
const WAKEUPLINE: &str = "wakeup_state.txt";
const ACT: &str = "acti_state.txt";
const PCAP: &str = "pcap_state.txt";
const LOG_FILE: &str = "command_log.txt";

fn write(path: &str, state: &str) -> io::Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create(true)
        .open(path)?;
    write!(file, "- State: {}\n", state)?;
    file.flush()
}

fn append_log(entry: &str) -> io::Result<()> {
    let mut file = OpenOptions::new()
        .append(true)
        .create(true)
        .open(LOG_FILE)?;
    writeln!(file, "{}", entry)
}

fn res(res: io::Result<()>, msg: &str) -> String {
    match res {
        Ok(_) => format!("OK {}", msg),
        Err(e) => format!("ERR {}", e),
    }
}


const CAPTURE_IFACE: &str = "lo";
const DEFAULT_PCAP_NAME: &str = "capture.pcap";

struct AppState {
    pcap_child: Mutex<Option<Child>>,
    pcap_name: Mutex<String>,
    pcap_name_set: Mutex<bool>,
}

impl AppState {
    fn new() -> Self {
        AppState {
            pcap_child: Mutex::new(None),
            pcap_name: Mutex::new(DEFAULT_PCAP_NAME.to_string()),
            pcap_name_set: Mutex::new(false),
        }
    }
}

fn enable_net_raw() -> io::Result<()> {
    caps::raise(None, CapSet::Inheritable, Capability::CAP_NET_RAW)
        .map_err(|e| io::Error::new(io::ErrorKind::Other, e))?;

   unsafe {
    if libc::prctl(
        libc::PR_CAP_AMBIENT,
        libc::PR_CAP_AMBIENT_RAISE,
        Capability::CAP_NET_RAW as libc::c_ulong,
        0,
        0,
    ) != 0
    {
        return Err(io::Error::last_os_error());
    }
}

    Ok(())
}


async fn start_pcap(state: &Arc<AppState>) -> String {
    let mut child_guard = state.pcap_child.lock().await;
    if child_guard.is_some() {
        return "ERR PCAP START: capture deja en cours".to_string();
    }

    if !*state.pcap_name_set.lock().await {
        return "ERR PCAP START: nom de fichier non defini, utiliser PCAP NAME <fichier> d'abord".to_string();
    }

    let filename = state.pcap_name.lock().await.clone();
    if let Err(e) = enable_net_raw() {
        return format!("ERR PCAP START: impossible d'activer CAP_NET_RAW: {}", e);
    }

    let mut child = match TokioCommand::new("tcpdump")
        .args(["-i", CAPTURE_IFACE, "-w", &filename, "-U"])
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(c) => c,
        Err(e) => return format!("ERR PCAP START: impossible de lancer tcpdump: {}", e),
    };

    sleep(Duration::from_millis(300)).await;

    match child.try_wait() {
        Ok(Some(status)) => {
            let mut stderr_output = String::new();
            if let Some(mut stderr) = child.stderr.take() {
                let _ = stderr.read_to_string(&mut stderr_output).await;
            }
            format!(
                "ERR PCAP START: tcpdump a quitte immediatement ({}): {}",
                status,
                stderr_output.trim()
            )
        }
        Ok(None) => {
            *child_guard = Some(child);
            let _ = write(PCAP, "START");
            format!("OK PCAP START {}", filename)
        }
        Err(e) => format!("ERR PCAP START: erreur verification processus: {}", e),
    }
}

async fn stop_pcap(state: &Arc<AppState>) -> String {
    let mut child_guard = state.pcap_child.lock().await;
    match child_guard.take() {
        Some(mut child) => {
            let _ = child.kill().await;
            let _ = child.wait().await;
            let _ = write(PCAP, "STOP");
            // On force un nouveau nom pour la prochaine capture, pour eviter
            // d'ecraser le fichier par erreur.
            *state.pcap_name_set.lock().await = false;
            "OK PCAP STOP".to_string()
        }
        None => "ERR PCAP STOP: aucune capture en cours".to_string(),
    }
}

async fn set_pcap_name(state: &Arc<AppState>, name: &str) -> String {
    if name.is_empty() {
        return "ERR PCAP NAME: nom de fichier manquant".to_string();
    }
   
    let filename = if name.ends_with(".pcap") {
        name.to_string()
    } else {
        format!("{}.pcap", name)
    };
    *state.pcap_name.lock().await = filename.clone();
    *state.pcap_name_set.lock().await = true;
    let _ = write(PCAP, "NAME");
    format!("OK PCAP NAME {}", filename)
}

async fn command(cmd: &str, state: &Arc<AppState>) -> String {
    let mut split = cmd.trim().splitn(2, ' ');
    let command = split.next().unwrap_or("");
    let arg = split.next().unwrap_or("");

    match command {
        "POWER" => match arg {
            "1" => res(write(PCU, "ON"), "POWER 1"),
            "0" => res(write(PCU, "OFF"), "POWER 0"),
            _ => "ERR POWER: argument invalide".to_string(),
        },
        "WAKE-UP" => match arg {
            "1" => res(write(WAKEUPLINE, "ON"), "WAKE-UP 1"),
            "0" => res(write(WAKEUPLINE, "OFF"), "WAKE-UP 0"),
            _ => "ERR WAKE-UP: argument invalide".to_string(),
        },
        "ACTI-LINE" => match arg {
            "1" => res(write(ACT, "ON"), "ACTI-LINE 1"),
            "0" => res(write(ACT, "OFF"), "ACTI-LINE 0"),
            _ => "ERR ACTI-LINE: argument invalide".to_string(),
        },
        "PCAP" => {
            let mut pcap_split = arg.splitn(2, ' ');
            let sub = pcap_split.next().unwrap_or("");
            let sub_arg = pcap_split.next().unwrap_or("").trim();
            match sub {
                "START" => start_pcap(state).await,
                "STOP" => stop_pcap(state).await,
                "NAME" => set_pcap_name(state, sub_arg).await,
                _ => "ERR PCAP: argument invalide".to_string(),
            }
        }
        _ => "ERR UNKNOWN COMMAND".to_string(),
    }
}

async fn handle_client(socket: TcpStream, addr: std::net::SocketAddr, state: Arc<AppState>) {
    let (reader, mut writer) = socket.into_split();
    let mut lines = BufReader::new(reader).lines();

    loop {
        match lines.next_line().await {
            Ok(Some(line)) => {
                let response = command(&line, &state).await;
                let log_entry = format!("{} -> {}", line.trim(), response);
                let _ = append_log(&log_entry);
                println!("{}", log_entry);

                if writer.write_all(response.as_bytes()).await.is_err() {
                    break;
                }
                if writer.write_all(b"\n").await.is_err() {
                    break;
                }
            }
            Ok(None) => {
                println!("[{}] connexion fermee", addr);
                break;
            }
            Err(e) => {
                eprintln!("[{}] erreur lecture: {}", addr, e);
                break;
            }
        }
    }
}

#[tokio::main]
async fn main() {
    let listener = TcpListener::bind("127.0.0.1:1234").await.unwrap();
    println!("Backend TCP en ecoute sur 127.0.0.1:1234");

    let state = Arc::new(AppState::new());

    loop {
        let (socket, addr) = match listener.accept().await {
            Ok(pair) => pair,
            Err(e) => {
                eprintln!("Erreur accept: {}", e);
                continue;
            }
        };
        println!("Nouvelle connexion: {}", addr);

        let state = Arc::clone(&state);
        tokio::spawn(async move {
            handle_client(socket, addr, state).await;
        });
    }
}