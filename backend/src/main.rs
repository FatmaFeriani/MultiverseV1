use std::env;
use std::fs;
use std::fs::OpenOptions;
use std::io::{self, Write};
use std::net::SocketAddr;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use caps::{CapSet, Capability};
use tonic::{transport::Server, Request, Response, Status};
use tokio::io::AsyncReadExt;
use tokio::process::{Child, Command as TokioCommand};
use tokio::sync::RwLock;
use tokio::time::sleep;


pub mod multiverse {
    tonic::include_proto!("multiverse");
}

use multiverse::multiverse_server::{Multiverse, MultiverseServer};
use multiverse::{
    ActiLineRequest, CommandReply, Empty, PcapFileReply, PcapNameRequest, PowerRequest,
    WakeUpRequest,
};

const PCU: &str = "pcu_state.txt";
const WAKEUPLINE: &str = "wakeup_state.txt";
const ACT: &str = "acti_state.txt";
const PCAP: &str = "pcap_state.txt";
const LOG_FILE: &str = "command_log.txt";

const CAPTURE_IFACE: &str = "lo";
const DEFAULT_PCAP_NAME: &str = "capture.pcap";
const CAPTURE_MAX_SIZE_MB: &str = "2048";
const CAPTURE_ROTATION_FILES: &str = "1";

fn write_state(path: &str, state: &str) -> io::Result<()> {
    let mut file = OpenOptions::new().write(true).create(true).open(path)?;
    write!(file, "- State: {}\n", state)?;
    file.flush()
}

fn append_log(entry: &str) -> io::Result<()> {
    let mut file = OpenOptions::new().append(true).create(true).open(LOG_FILE)?;
    writeln!(file, "{}", entry)
}

fn parse_bind_addr_from(args: &[String]) -> Result<SocketAddr, String> {
    let host = args
        .first()
        .cloned()
        .unwrap_or_else(|| "127.0.0.1".to_string());
    let port = args
        .get(1)
        .cloned()
        .unwrap_or_else(|| "8080".to_string());

    let port = port
        .parse::<u16>()
        .map_err(|e| format!("invalid port '{}': {}", port, e))?;

    format!("{}:{}", host, port)
        .parse::<SocketAddr>()
        .map_err(|e| format!("invalid bind address '{}:{}': {}", host, port, e))
}

fn parse_bind_addr() -> Result<SocketAddr, String> {
    let args: Vec<String> = env::args().skip(1).collect();
    parse_bind_addr_from(&args)
}

fn reply_from(res: io::Result<()>, msg: &str) -> CommandReply {
    match res {
        Ok(_) => CommandReply {
            ok: true,
            message: format!("OK {}", msg),
        },
        Err(e) => CommandReply {
            ok: false,
            message: format!("ERR {}: {}", msg, e),
        },
    }
}

fn log_and_return(entry: String, reply: CommandReply) -> CommandReply {
    let log_line = format!("{} -> {}", entry, reply.message);
    let _ = append_log(&log_line);
    println!("{}", log_line);
    reply
}

struct AppState {
    pcap_child: Arc<RwLock<Option<Child>>>,
    pcap_name: Arc<RwLock<String>>,
    pcap_name_set: Arc<RwLock<bool>>,
}

impl AppState {
    fn new() -> Self {
        AppState {
            pcap_child: Arc::new(RwLock::new(None)),
            pcap_name: Arc::new(RwLock::new(DEFAULT_PCAP_NAME.to_string())),
            pcap_name_set: Arc::new(RwLock::new(false)),
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

async fn start_pcap(state: &Arc<AppState>) -> CommandReply {
    let mut child_guard = state.pcap_child.write().await;
    if child_guard.is_some() {
        return CommandReply {
            ok: false,
            message: "ERR PCAP START: capture deja en cours".to_string(),
        };
    }

    if !*state.pcap_name_set.read().await {
        return CommandReply {
            ok: false,
            message:
                "ERR PCAP START: nom de fichier non defini, utiliser PcapSetName d'abord"
                    .to_string(),
        };
    }

    let filename = state.pcap_name.read().await.clone();
    if let Err(e) = enable_net_raw() {
        return CommandReply {
            ok: false,
            message: format!("ERR PCAP START: impossible d'activer CAP_NET_RAW: {}", e),
        };
    }

    let mut child = match TokioCommand::new("tcpdump")
        .args([
            "-i",
            CAPTURE_IFACE,
            "-w",
            &filename,
            "-C",
            CAPTURE_MAX_SIZE_MB,
            "-W",
            CAPTURE_ROTATION_FILES,
            "-U",
        ])
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(c) => c,
        Err(e) => {
            return CommandReply {
                ok: false,
                message: format!("ERR PCAP START: impossible de lancer tcpdump: {}", e),
            }
        }
    };

    sleep(Duration::from_millis(300)).await;

    match child.try_wait() {
        Ok(Some(status)) => {
            let mut stderr_output = String::new();
            if let Some(mut stderr) = child.stderr.take() {
                let _ = stderr.read_to_string(&mut stderr_output).await;
            }
            CommandReply {
                ok: false,
                message: format!(
                    "ERR PCAP START: tcpdump a quitte immediatement ({}): {}",
                    status,
                    stderr_output.trim()
                ),
            }
        }
        Ok(None) => {
            *child_guard = Some(child);
            let _ = write_state(PCAP, "START");
            CommandReply {
                ok: true,
                message: format!("OK PCAP START {}", filename),
            }
        }
        Err(e) => CommandReply {
            ok: false,
            message: format!("ERR PCAP START: erreur verification processus: {}", e),
        },
    }
}

async fn stop_pcap(state: &Arc<AppState>) -> CommandReply {
    let mut child_guard = state.pcap_child.write().await;
    match child_guard.take() {
        Some(mut child) => {
            let _ = child.kill().await;
            let _ = child.wait().await;
            let _ = write_state(PCAP, "STOP");
            *state.pcap_name_set.write().await = false;
            CommandReply {
                ok: true,
                message: "OK PCAP STOP".to_string(),
            }
        }
        None => CommandReply {
            ok: false,
            message: "ERR PCAP STOP: aucune capture en cours".to_string(),
        },
    }
}

async fn set_pcap_name(state: &Arc<AppState>, name: &str) -> CommandReply {
    if name.is_empty() {
        return CommandReply {
            ok: false,
            message: "ERR PCAP NAME: nom de fichier manquant".to_string(),
        };
    }

    let filename = if name.ends_with(".pcap") {
        name.to_string()
    } else {
        format!("{}.pcap", name)
    };

    {
        let mut child_guard = state.pcap_child.write().await;
        if let Some(mut child) = child_guard.take() {
            let _ = child.kill().await;
            let _ = child.wait().await;
            let _ = write_state(PCAP, "STOP");
        }
    }

    *state.pcap_name.write().await = filename.clone();
    *state.pcap_name_set.write().await = true;
    let _ = write_state(PCAP, "NAME");
    CommandReply {
        ok: true,
        message: format!("OK PCAP NAME {}", filename),
    }
}

async fn delete_pcap(state: &Arc<AppState>, name: &str) -> CommandReply {
    if name.is_empty() {
        return CommandReply {
            ok: false,
            message: "ERR PCAP DELETE: nom de fichier manquant".to_string(),
        };
    }

    let filename = if name.ends_with(".pcap") {
        name.to_string()
    } else {
        format!("{}.pcap", name)
    };

    match fs::remove_file(&filename) {
        Ok(_) => {
            *state.pcap_name.write().await = DEFAULT_PCAP_NAME.to_string();
            *state.pcap_name_set.write().await = false;
            let _ = write_state(PCAP, "STOP");
            CommandReply {
                ok: true,
                message: format!("OK PCAP DELETE {}", filename),
            }
        }
        Err(err) if err.kind() == io::ErrorKind::NotFound => {
            *state.pcap_name.write().await = DEFAULT_PCAP_NAME.to_string();
            *state.pcap_name_set.write().await = false;
            let _ = write_state(PCAP, "STOP");
            CommandReply {
                ok: true,
                message: format!("OK PCAP DELETE {} (already absent)", filename),
            }
        }
        Err(err) => CommandReply {
            ok: false,
            message: format!("ERR PCAP DELETE: impossible de supprimer {}: {}", filename, err),
        },
    }
}

pub struct MultiverseService {
    state: Arc<AppState>,
}

#[tonic::async_trait]
impl Multiverse for MultiverseService {
    async fn pcap_get(
        &self,
        request: Request<PcapNameRequest>,
    ) -> Result<Response<PcapFileReply>, Status> {
        let name = request.into_inner().name;
        let content = fs::read(&name).map_err(|e| {
            Status::not_found(format!("PCAP GET: could not read {}: {}", name, e))
        })?;

        Ok(Response::new(PcapFileReply {
            filename: name.clone(),
            content,
        }))
    }

    async fn set_power(
        &self,
        request: Request<PowerRequest>,
    ) -> Result<Response<CommandReply>, Status> {
        let on = request.into_inner().on;
        let label = if on { "1" } else { "0" };
        let res = write_state(PCU, if on { "ON" } else { "OFF" });
        let reply = reply_from(res, &format!("POWER {}", label));
        Ok(Response::new(log_and_return(
            format!("POWER {}", label),
            reply,
        )))
    }

    async fn set_wake_up(
        &self,
        request: Request<WakeUpRequest>,
    ) -> Result<Response<CommandReply>, Status> {
        let on = request.into_inner().on;
        let label = if on { "1" } else { "0" };
        let res = write_state(WAKEUPLINE, if on { "ON" } else { "OFF" });
        let reply = reply_from(res, &format!("WAKE-UP {}", label));
        Ok(Response::new(log_and_return(
            format!("WAKE-UP {}", label),
            reply,
        )))
    }

    async fn set_acti_line(
        &self,
        request: Request<ActiLineRequest>,
    ) -> Result<Response<CommandReply>, Status> {
        let on = request.into_inner().on;
        let label = if on { "1" } else { "0" };
        let res = write_state(ACT, if on { "ON" } else { "OFF" });
        let reply = reply_from(res, &format!("ACTI-LINE {}", label));
        Ok(Response::new(log_and_return(
            format!("ACTI-LINE {}", label),
            reply,
        )))
    }

    async fn pcap_start(
        &self,
        _request: Request<Empty>,
    ) -> Result<Response<CommandReply>, Status> {
        let reply = start_pcap(&self.state).await;
        Ok(Response::new(log_and_return("PCAP START".to_string(), reply)))
    }

    async fn pcap_stop(
        &self,
        _request: Request<Empty>,
    ) -> Result<Response<CommandReply>, Status> {
        let reply = stop_pcap(&self.state).await;
        Ok(Response::new(log_and_return("PCAP STOP".to_string(), reply)))
    }

    async fn pcap_set_name(
        &self,
        request: Request<PcapNameRequest>,
    ) -> Result<Response<CommandReply>, Status> {
        let name = request.into_inner().name;
        let reply = set_pcap_name(&self.state, name.trim()).await;
        Ok(Response::new(log_and_return(
            format!("PCAP NAME {}", name),
            reply,
        )))
    }

    async fn pcap_delete(
        &self,
        request: Request<PcapNameRequest>,
    ) -> Result<Response<CommandReply>, Status> {
        let name = request.into_inner().name;
        let reply = delete_pcap(&self.state, name.trim()).await;
        Ok(Response::new(log_and_return(
            format!("PCAP DELETE {}", name),
            reply,
        )))
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let addr = parse_bind_addr().map_err(|err| {
        std::io::Error::new(std::io::ErrorKind::InvalidInput, err)
    })?;
    let state = Arc::new(AppState::new());
    let service = MultiverseService { state };

    println!("Backend gRPC en ecoute sur {}", addr);

    Server::builder()
        .add_service(MultiverseServer::new(service))
        .serve(addr)
        .await?;

    Ok(())
}

